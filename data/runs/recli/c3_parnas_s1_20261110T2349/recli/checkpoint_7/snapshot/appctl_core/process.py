"""External command execution.

Secret: how child processes are spawned, timed and logged, how sensitive
substrings are hidden from debug output, the wording of the exit code -1
warning, and how appctl re-invokes itself with the current runtime
configuration.
"""

import json
import os
import shlex
import subprocess
import sys
import time

from . import messages as _messages
from .errors import Halt
from .output import Output

_GROUP = "process"
_MASK = "******"
_SIGNAL_EXIT = -1
_ENTRY_POINT = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "appctl.py")
# Environment variables describing the runtime that a child appctl inherits.
_CONFIG_PATH_ENV = "APPCTL_CONFIG_PATH"


class ProcessRun:
    """Outcome of one external command."""

    def __init__(self, command, stdout, stderr, return_code, run_time, cwd=None, env=None):
        self.command = command
        self.stdout = stdout
        self.stderr = stderr
        self.return_code = return_code
        self.run_time = run_time
        self.cwd = cwd
        self.env = env

    @property
    def succeeded(self):
        return self.return_code == 0

    def __repr__(self):
        return (f"ProcessRun(command={self.command!r}, return_code={self.return_code}, "
                f"run_time={self.run_time:.3f})")


def _default_output():
    return Output(sys.stdout, sys.stderr)


def command_text(command):
    """The command as a single shell-style string."""
    if isinstance(command, (list, tuple)):
        return shlex.join(str(part) for part in command)
    return str(command)


def obfuscate(text, secrets):
    """Replace every listed substring of ``text`` with ``******``."""
    text = str(text)
    for secret in sorted({str(s) for s in secrets or () if s not in (None, "")},
                         key=len, reverse=True):
        text = text.replace(secret, _MASK)
    return text


def _decode(data):
    if data is None:
        return ""
    if isinstance(data, bytes):
        return data.decode(errors="replace")
    return data


def run(command, *, cwd=None, env=None, out=None, obfuscate_list=(), stdin=None):
    """Run ``command`` and return a ``ProcessRun``.

    ``command`` is either a shell command string or an argument list. The
    command is logged at debug level before it runs (with every substring in
    ``obfuscate_list`` masked); afterwards non-empty STDOUT and STDERR and the
    return code are logged. The returned result always holds the real values.
    """
    out = out or _default_output()
    text = command_text(command)

    def debug(message):
        out.debug(obfuscate(message, obfuscate_list), group=_GROUP)

    debug(f"Running command: {text}")
    started = time.monotonic()
    try:
        proc = subprocess.run(
            command, shell=isinstance(command, str), cwd=cwd,
            env=dict(env) if env is not None else None,
            input=stdin.encode() if isinstance(stdin, str) else stdin,
            stdin=None if stdin is not None else subprocess.DEVNULL,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        stdout, stderr, code = _decode(proc.stdout), _decode(proc.stderr), proc.returncode
    except OSError as exc:
        stdout, stderr, code = "", f"{getattr(exc, 'strerror', None) or exc}\n", 127
    result = ProcessRun(text, stdout, stderr, code, time.monotonic() - started,
                        cwd=cwd, env=env)
    if stdout:
        debug(f"STDOUT: {stdout.rstrip(chr(10))}")
    if stderr:
        debug(f"STDERR: {stderr.rstrip(chr(10))}")
    debug(f"Return code: {code}")
    if code == _SIGNAL_EXIT:
        out.warning(_messages.spawned_exit_minus_one())
    return result


def run_check(command, **kwargs):
    """Run ``command`` and return whether it exited successfully."""
    return run(command, **kwargs).succeeded


# --- re-dispatching appctl -------------------------------------------------

def _flag(name, value):
    if value is True:
        return f"--{name}"
    if value is False:
        return f"--no-{name}" if name == "color" else None
    if value is None:
        return None
    return f"--{name}={value}"


def runtime_flags(runtime_values):
    """Global flags reproducing ``runtime_values`` on a command line."""
    flags = []
    for name, value in runtime_values.items():
        flag = _flag(name, value)
        if flag is not None:
            flags.append(flag)
    return flags


def _args_list(command):
    if isinstance(command, str):
        return shlex.split(command)
    return [str(part) for part in command]


def _assoc_flags(assoc_args):
    flags = []
    for key, value in (assoc_args or {}).items():
        flag = _flag(key, value)
        if flag is not None:
            flags.append(flag)
    return flags


class Launcher:
    """Runs appctl as a child process with the current runtime configuration:
    the same interpreter and entry point, the same global flags, config file
    path, environment and working directory."""

    def __init__(self, runtime_values, env, cwd, out, config_path=None):
        self.runtime_values = dict(runtime_values or {})
        self.env = dict(env or {})
        self.cwd = cwd
        self.out = out or _default_output()
        self.config_path = config_path

    def argv(self, command, args=(), assoc_args=None, runtime_args=None):
        values = dict(self.runtime_values)
        values.update(runtime_args or {})
        return ([sys.executable, _ENTRY_POINT] + runtime_flags(values)
                + _args_list(command) + [str(a) for a in args]
                + _assoc_flags(assoc_args))

    def environment(self):
        env = dict(self.env)
        if self.config_path and not env.get(_CONFIG_PATH_ENV):
            env[_CONFIG_PATH_ENV] = self.config_path
        return env

    def launch(self, command, args=(), assoc_args=None, *, runtime_args=None,
               obfuscate_list=(), stdin=None):
        """Run appctl ``command`` and return the ``ProcessRun``."""
        return run(self.argv(command, args, assoc_args, runtime_args),
                   cwd=self.cwd, env=self.environment(), out=self.out,
                   obfuscate_list=obfuscate_list, stdin=stdin)

    def launch_self(self, command, args=(), assoc_args=None, *, exit_on_error=True,
                    return_detailed=False, runtime_args=None, obfuscate_list=()):
        """Run appctl ``command``; return the ``ProcessRun`` when
        ``return_detailed`` or else its return code. A failure halts the
        current invocation with the same code when ``exit_on_error``."""
        result = self.launch(command, args, assoc_args, runtime_args=runtime_args,
                             obfuscate_list=obfuscate_list)
        if return_detailed:
            return result
        if result.return_code and exit_on_error:
            raise Halt(result.return_code)
        return result.return_code

    def runcommand(self, command, *, return_="stdout", parse=None, exit_error=True,
                   obfuscate_list=(), stdin=None):
        """Run appctl ``command`` and return part of its outcome.

        ``return_`` is ``"stdout"``, ``"stderr"``, ``"return_code"`` or
        ``"all"``; with ``parse="json"`` STDOUT is decoded as JSON (``None``
        when it is not valid JSON).
        """
        result = self.launch(command, obfuscate_list=obfuscate_list, stdin=stdin)
        if result.return_code and exit_error:
            if result.stderr:
                self.out.write_stderr(result.stderr)
            raise Halt(result.return_code)
        if return_ == "all":
            return result
        if return_ == "return_code":
            return result.return_code
        if return_ == "stderr":
            return result.stderr.rstrip("\r\n")
        stdout = result.stdout.rstrip("\r\n")
        if parse == "json":
            try:
                return json.loads(stdout)
            except ValueError:
                return None
        return stdout
