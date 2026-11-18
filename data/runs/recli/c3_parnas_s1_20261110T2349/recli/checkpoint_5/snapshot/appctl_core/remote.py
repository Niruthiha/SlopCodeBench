"""Remote execution.

Secret: the syntax of ``ssh`` connection strings, how each transport
(ssh, docker, docker-compose, docker-compose-run, vagrant) builds its
command line, how the remote appctl command is assembled (pre-command,
working directory, forwarded arguments) and how transport failures are
reported.
"""

import re
import shlex
import shutil
import subprocess

from . import messages as _messages

_REMOTE_BINARY = "appctl"
_PRE_CMD_ENV = "APPCTL_SSH_PRE_CMD"
_STRICT_ENV = "APPCTL_STRICT_ARGS_MODE"
_CONNECT_FAILURE = 255
_SSH_URL = re.compile(
    r"^((?P<scheme>docker|docker-compose|docker-compose-run|ssh|vagrant):)?"
    r"(//)?((?P<user>[^@:]+)@)?(?P<host>[^:/~]+)(:(?P<port>\d*))?"
    r"(?P<path>[/~].*)?$")
# Connection keys forwarded to the remote invocation as runtime flags.
_FORWARDED = ("path", "url", "user")


def parse(url):
    """Split a connection string into its parts (missing parts are None)."""
    match = _SSH_URL.match(url or "")
    if not match:
        return {"scheme": None, "user": None, "host": url, "port": None, "path": None}
    bits = match.groupdict()
    return {key: (value or None) for key, value in bits.items()}


def _quote_path(path):
    if path == "~":
        return path
    if path.startswith("~/"):
        return "~/" + shlex.quote(path[2:])
    return shlex.quote(path)


def remote_command(args, bits, env):
    """The shell command run on the remote side."""
    parts = []
    pre = (env.get(_PRE_CMD_ENV) or "").strip().rstrip(";").strip()
    if pre:
        parts.append(pre + ";")
    if bits.get("path"):
        parts.append(f"cd {_quote_path(bits['path'])};")
    if env.get(_STRICT_ENV):
        parts.append(f"{_STRICT_ENV}=1")
    parts.append(_REMOTE_BINARY)
    parts.extend(shlex.quote(a) for a in args)
    return " ".join(parts)


def transport_argv(bits, command, args, tty, debug):
    """The local command line that runs ``command`` remotely."""
    scheme = bits.get("scheme") or "ssh"
    host, user, port = bits.get("host") or "", bits.get("user"), bits.get("port")
    if scheme == "docker":
        argv = ["docker", "exec"]
        if user:
            argv += ["--user", user]
        if tty:
            argv.append("-t")
        return argv + [host, "sh", "-c", command]
    if scheme == "docker-compose":
        argv = ["docker-compose", "exec"]
        if user:
            argv += ["--user", user]
        if not tty:
            argv.append("-T")
        return argv + [host, "sh", "-c", command]
    if scheme == "docker-compose-run":
        argv = ["docker-compose", "run"]
        if user:
            argv += ["--user", user]
        if not tty:
            argv.append("-T")
        return argv + [host] + list(args)
    if scheme == "vagrant":
        return ["vagrant", "ssh", "-c", command, host]
    argv = ["ssh"]
    if port:
        argv += ["-p", str(int(port))]
    argv.append("-t" if tty else "-T")
    argv.append("-vvv" if debug else "-q")
    argv.append(f"{user}@{host}" if user else host)
    return argv + [command]


def _fileno(stream):
    try:
        return stream.fileno()
    except (AttributeError, OSError, ValueError):
        return None


def _isatty(stream):
    try:
        return stream.isatty()
    except (AttributeError, ValueError):
        return False


def forwarded_args(raw_args, connection, runtime_values):
    """Arguments for the remote appctl: the local ones minus ``--ssh``, plus
    connection parameters that were not given at runtime."""
    args = [a for a in raw_args if not (a == "--ssh" or a.startswith("--ssh="))]
    for key in _FORWARDED:
        value = connection.get(key)
        if value not in (None, "") and key not in runtime_values:
            args.append(f"--{key}={value}")
    return args


def run(ssh, raw_args, connection, runtime_values, config, env, out, stdout, stderr):
    """Run the command through the configured transport; return exit code."""
    bits = parse(ssh)
    args = forwarded_args(raw_args, connection, runtime_values)
    tty = not config.get("skip-tty") and _isatty(stdout)
    command = remote_command(args, bits, env)
    argv = transport_argv(bits, command, args, tty, config.debug())
    out.debug(f"Running remote command: {shlex.join(argv)}", group="ssh")
    for stream in (stdout, stderr):
        if hasattr(stream, "flush"):
            stream.flush()
    executable = shutil.which(argv[0], path=env.get("PATH"))
    if executable is None:
        out.error(_messages.ssh_connection_failed())
        return _CONNECT_FAILURE
    out_fd, err_fd = _fileno(stdout), _fileno(stderr)
    try:
        proc = subprocess.run(
            [executable] + argv[1:], env=dict(env),
            stdout=out_fd if out_fd is not None else subprocess.PIPE,
            stderr=err_fd if err_fd is not None else subprocess.PIPE)
    except OSError:
        out.error(_messages.ssh_connection_failed())
        return _CONNECT_FAILURE
    if out_fd is None and proc.stdout:
        stdout.write(proc.stdout.decode(errors="replace"))
    if err_fd is None and proc.stderr:
        stderr.write(proc.stderr.decode(errors="replace"))
    if proc.returncode == _CONNECT_FAILURE:
        out.error(_messages.ssh_connection_failed())
    return proc.returncode
