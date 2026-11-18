"""Execution of a command on a remote endpoint (SSH, Docker, Vagrant)."""

import json
import os
import re
import shlex
import subprocess
import sys

from . import PROGRAM_NAME
from .arguments import END_OF_OPTIONS, is_assoc_token, parse_assoc_token
from .errors import AppctlError

SSH_PRE_CMD_ENV = "APPCTL_SSH_PRE_CMD"
SSH_BINARY_ENV = "APPCTL_SSH_BINARY"
CONNECTION_FAILED = 255

SSH_URL_RE = re.compile(
    r"^(?:(?P<scheme>docker|docker-compose|docker-compose-run|ssh|vagrant):(?://)?)?"
    r"(?:(?P<user>[^@:/]+)@)?"
    r"(?P<host>[^:/~]+)"
    r"(?::(?P<port>\d*))?"
    r"(?P<path>[/~].*)?$"
)


def parse_ssh_url(url):
    """Split ``[scheme:][user@]host[:port][path]`` into its components."""
    match = SSH_URL_RE.match(str(url).strip())
    if not match:
        raise AppctlError(f"Invalid SSH connection string '{url}'.")
    return {k: v for k, v in match.groupdict().items() if v}


def _strip_ssh_flags(argv):
    stripped = []
    end_of_options = False
    for token in argv:
        if token == END_OF_OPTIONS:
            end_of_options = True
        elif not end_of_options and is_assoc_token(token) and parse_assoc_token(token)[0] == "ssh":
            continue
        stripped.append(token)
    return stripped


def build_remote_command(argv, environ, alias=None, alias_params=None, path=None):
    """The shell command run on the remote side."""
    binary = environ.get(SSH_BINARY_ENV) or PROGRAM_NAME
    prefix = ""
    pre_cmd = (environ.get(SSH_PRE_CMD_ENV) or "").strip().rstrip(";").strip()
    if pre_cmd:
        prefix = pre_cmd + "; "
    words = []
    if alias:
        forwarded = {k: v for k, v in (alias_params or {}).items() if k != "ssh"}
        if forwarded:
            encoded = json.dumps({alias: forwarded}, separators=(",", ":"))
            prefix += f"APPCTL_RUNTIME_ALIAS={shlex.quote(encoded)} "
            words.append(alias)
    words.extend(_strip_ssh_flags(argv))
    if path:
        words.append(f"--path={path}")
    return prefix + " ".join([binary] + [shlex.quote(w) for w in words])


def build_transport(bits, remote_command, tty=False, proxyjump=None, key=None):
    """argv of the local process that carries ``remote_command``."""
    scheme = bits.get("scheme", "ssh")
    host = bits["host"]
    user = bits.get("user")
    if scheme == "docker":
        argv = ["docker", "exec"]
        if user:
            argv += ["--user", user]
        argv += ["-it" if tty else "-i", host, "sh", "-c", remote_command]
        return argv
    if scheme in ("docker-compose", "docker-compose-run"):
        argv = ["docker-compose", "exec" if scheme == "docker-compose" else "run"]
        if user:
            argv += ["--user", user]
        if not tty:
            argv.append("-T")
        if scheme == "docker-compose-run":
            argv.append("--rm")
        argv += [host, "sh", "-c", remote_command]
        return argv
    if scheme == "vagrant":
        return ["vagrant", "ssh", "-c", remote_command, host]
    argv = ["ssh", "-q"]
    if proxyjump:
        argv += ["-J", str(proxyjump)]
    if key:
        argv += ["-i", str(key)]
    if bits.get("port"):
        argv += ["-p", str(int(bits["port"]))]
    argv.append("-t" if tty else "-T")
    argv.append(f"{user}@{host}" if user else host)
    argv.append(remote_command)
    return argv


def _real_stream(stream, default):
    return stream is None or stream is default


def run_remote(ssh, argv, environ, output, alias=None, alias_params=None, skip_tty=False):
    """Run the command remotely and return its exit code."""
    bits = parse_ssh_url(ssh)
    alias_params = alias_params or {}
    remote_command = build_remote_command(argv, environ, alias, alias_params, bits.get("path"))
    passthrough = _real_stream(output.stdout, sys.stdout) and _real_stream(output.stderr, sys.stderr)
    tty = bool(passthrough and not skip_tty and sys.stdout.isatty() and sys.stdin.isatty())
    transport = build_transport(bits, remote_command, tty=tty,
                                proxyjump=alias_params.get("proxyjump"),
                                key=alias_params.get("key"))
    output.debug("Running SSH command: " + " ".join(shlex.quote(a) for a in transport))
    output.stdout.flush()
    output.stderr.flush()
    try:
        if passthrough:
            code = subprocess.run(transport, env=dict(environ)).returncode
        else:
            result = subprocess.run(transport, env=dict(environ), capture_output=True, text=True)
            output.stdout.write(result.stdout)
            output.stderr.write(result.stderr)
            code = result.returncode
    except OSError:
        code = CONNECTION_FAILED
    if code == CONNECTION_FAILED:
        raise AppctlError("Cannot connect over SSH using provided configuration.", CONNECTION_FAILED)
    return code
