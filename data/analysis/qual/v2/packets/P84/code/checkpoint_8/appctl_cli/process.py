"""Execution of external commands, including appctl itself."""

import json
import os
import shlex
import subprocess
import sys
import time
from dataclasses import dataclass, field

from . import PROGRAM_NAME
from .config_loader import CONFIG_PATH_ENV
from .errors import AppctlError
from .runtime_config import GLOBAL_PARAMETERS

OBFUSCATED = "******"
SIGNAL_EXIT_CODE = -1
TIMEOUT_EXIT_CODE = 124
SIGNAL_WARNING = ("Spawned process returned exit code -1, which could be caused by the "
                  "signal handling configuration of the runtime (e.g. a custom SIGCHLD or "
                  "SIGHUP handler).")
SCRIPT_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                           f"{PROGRAM_NAME}.py")


@dataclass
class ProcessRun:
    """Outcome of one external command."""

    stdout: str
    stderr: str
    return_code: int
    command: object
    cwd: str = None
    env: dict = field(default=None, repr=False)
    run_time: float = 0.0

    @property
    def succeeded(self):
        return self.return_code == 0


def command_to_string(command):
    if isinstance(command, (list, tuple)):
        return shlex.join(str(part) for part in command)
    return str(command)


def obfuscate(text, secrets=()):
    """Replace every listed substring of ``text`` with ``******``."""
    text = str(text)
    for secret in sorted({str(s) for s in secrets or () if s not in (None, "")},
                         key=len, reverse=True):
        quoted = shlex.quote(secret)
        if quoted != secret:
            text = text.replace(quoted, OBFUSCATED)
        text = text.replace(secret, OBFUSCATED)
    return text


def _debug(output, text, secrets):
    if output is not None:
        output.debug(obfuscate(text, secrets))


def warn_signal_exit(return_code, output=None):
    """Non-halting warning for processes exiting with code -1."""
    if return_code != SIGNAL_EXIT_CODE:
        return
    if output is not None:
        output.warning(SIGNAL_WARNING)
    else:
        print(f"Warning: {SIGNAL_WARNING}", file=sys.stderr)


def run_command(command, output=None, obfuscate_list=(), cwd=None, env=None, stdin=None,
                timeout=None):
    """Run ``command`` (a shell string or an argv list) and return a :class:`ProcessRun`.

    The command is logged at debug level before it runs; non-empty STDOUT and
    STDERR and then the return code are logged afterwards. Every substring in
    ``obfuscate_list`` is masked in the log, never in the command itself. A
    command still running after ``timeout`` seconds is killed (return code 124).
    """
    shell = not isinstance(command, (list, tuple))
    argv = command if shell else [str(part) for part in command]
    _debug(output, f"COMMAND: {command_to_string(command)}", obfuscate_list)
    started = time.monotonic()
    try:
        completed = subprocess.run(argv, shell=shell, cwd=cwd, env=env, input=stdin,
                                   capture_output=True, text=True, errors="replace",
                                   timeout=timeout)
        stdout, stderr, return_code = completed.stdout, completed.stderr, completed.returncode
    except subprocess.TimeoutExpired:
        stdout, stderr, return_code = "", f"Timed out after {timeout} seconds.\n", TIMEOUT_EXIT_CODE
    except OSError as exc:
        stdout, stderr, return_code = "", f"{exc.strerror or exc}\n", 127
    run_time = time.monotonic() - started
    for label, text in (("STDOUT", stdout), ("STDERR", stderr)):
        if text:
            _debug(output, f"{label}: " + text.strip("\r\n"), obfuscate_list)
    _debug(output, f"RETURN CODE: {return_code}", obfuscate_list)
    warn_signal_exit(return_code, output)
    return ProcessRun(stdout=stdout, stderr=stderr, return_code=return_code, command=command,
                      cwd=cwd, env=env, run_time=run_time)


def exec_command(command, output=None, obfuscate_list=(), cwd=None, env=None, stdin=None):
    """Run ``command`` and return whether it succeeded."""
    return run_command(command, output, obfuscate_list, cwd=cwd, env=env, stdin=stdin).succeeded


def launch(command, output=None, exit_on_error=True, return_detailed=True, obfuscate_list=(),
           cwd=None, env=None):
    """Run ``command``; optionally fail on a non-zero exit.

    Returns the :class:`ProcessRun` or, with ``return_detailed=False``, the
    return code.
    """
    result = run_command(command, output, obfuscate_list, cwd=cwd, env=env)
    if exit_on_error and result.return_code != 0:
        raise AppctlError(_failure_message(result, obfuscate_list),
                          exit_code=result.return_code if result.return_code > 0 else 1)
    return result if return_detailed else result.return_code


def _failure_message(result, secrets=()):
    message = result.stderr.strip()
    if message.startswith("Error: "):
        message = message[len("Error: "):]
    if not message:
        message = (f"Command '{obfuscate(command_to_string(result.command), secrets)}' "
                   f"failed with exit code {result.return_code}.")
    return message


# -- re-dispatching appctl itself ---------------------------------------------


def _flag(name, value):
    if value is True:
        return f"--{name}"
    if value is False:
        return f"--no-{name}"
    return f"--{name}={value}"


def runtime_flags(runtime):
    """Global flags reproducing the current runtime configuration."""
    flags = []
    for name, param in GLOBAL_PARAMETERS.items():
        if not param.runtime or name not in (runtime or {}):
            continue
        value = runtime[name]
        if value is None or value == param.default:
            continue
        if isinstance(value, (list, tuple)):
            flags.extend(_flag(name, item) for item in value)
        else:
            flags.append(_flag(name, value))
    return flags


def self_command(command, args=(), assoc=None, runtime=None):
    """argv that runs appctl ``command`` with the current runtime flags."""
    words = shlex.split(command) if isinstance(command, str) else list(command)
    words += [str(a) for a in args]
    words += [_flag(k, v) for k, v in (assoc or {}).items()]
    from .system import binary_path, runtime_binary
    return [runtime_binary(), binary_path() or SCRIPT_PATH] + runtime_flags(runtime) + words


def self_environment(config_path=None, environ=None):
    """Child environment; it records the runtime binary used to launch appctl."""
    from .system import RUNTIME_BIN_USED_ENV, runtime_binary
    env = dict(os.environ if environ is None else environ)
    env[RUNTIME_BIN_USED_ENV] = runtime_binary(env)
    if config_path:
        env[CONFIG_PATH_ENV] = str(config_path)
    return env


def launch_self(ctx, command, args=(), assoc=None, exit_on_error=True, return_detailed=False,
                parse=None, obfuscate_list=(), cwd=None):
    """Run an appctl command in a child process, preserving the runtime config.

    Returns the :class:`ProcessRun` (``return_detailed``) or the return code.
    With ``parse="json"`` the child's STDOUT is decoded as JSON first.
    """
    runtime = getattr(ctx, "runtime", None) or {}
    config = getattr(ctx, "config", None)
    argv = self_command(command, args, assoc, runtime)
    env = self_environment(getattr(config, "global_path", None))
    result = launch(argv, getattr(ctx, "output", None), exit_on_error=exit_on_error,
                    obfuscate_list=obfuscate_list, cwd=cwd, env=env)
    if parse == "json":
        result.stdout = parse_json(result.stdout)
    return result if return_detailed else result.return_code


def runcommand(ctx, command, return_=True, parse=None, exit_error=True, obfuscate_list=()):
    """Run an appctl command and return its result.

    ``return_`` selects ``"all"`` (the :class:`ProcessRun`), ``"stdout"`` (or
    ``True``), ``"stderr"`` or ``"return_code"``. ``parse="json"`` decodes
    STDOUT as JSON before it is returned.
    """
    result = launch_self(ctx, command, exit_on_error=exit_error, return_detailed=True,
                         parse=parse, obfuscate_list=obfuscate_list)
    if return_ == "all":
        return result
    if return_ == "stderr":
        return result.stderr.strip()
    if return_ == "return_code":
        return result.return_code
    if parse == "json":
        return result.stdout
    return result.stdout.strip()


def parse_json(text):
    """Decode JSON output; ``None`` when it is not valid JSON."""
    try:
        return json.loads(text)
    except (TypeError, ValueError):
        return None
