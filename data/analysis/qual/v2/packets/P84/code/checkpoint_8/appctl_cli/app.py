"""Top-level orchestration: config, aliases, rewrite, parse, resolve, validate, run."""

import os
import sys
import time

from . import config_loader, database, self_update, system
from .arguments import END_OF_OPTIONS, is_assoc_token, parse_argv
from .commands import build_command_tree
from .context import Context
from .errors import AppctlError, MultiLineError, UsageError
from .file_cache import get_cache
from .help import render_root_help, render_usage
from .logger import FileLogger, log_path
from .output import Output
from .remote import run_remote
from .resolver import resolve, try_resolve
from .rewrites import apply_rewrites
from .runtime_config import build_runtime_config, deprecation_warnings, is_strict_mode
from .startup import Startup, is_machine_readable
from .suggest import get_suggestion
from .validator import ArgumentValidator


def extract_alias(argv):
    """Return ``(alias, argv_without_alias)``; the alias is the first non-flag token."""
    for index, token in enumerate(argv):
        if token == END_OF_OPTIONS:
            break
        if is_assoc_token(token):
            continue
        if config_loader.is_alias(token):
            return token, argv[:index] + argv[index + 1:]
        break
    return None, list(argv)


def _unique(items):
    seen = []
    for item in items:
        if item not in seen:
            seen.append(item)
    return seen


def check_disabled(command, typed, disabled):
    """Raise if the command or one of its parents is disabled."""
    disabled = {" ".join(str(entry).split()) for entry in disabled}
    for path in (command.path, typed[:len(command.path)]):
        for depth in range(1, len(path) + 1):
            name = " ".join(path[:depth])
            if name in disabled:
                raise AppctlError(f"The '{name}' command has been disabled.")


def guarded(output, action, *args):
    """Run ``action`` and report user-facing errors; return the exit code."""
    try:
        return int(action(*args) or 0)
    except UsageError as exc:
        output.line(exc.usage)
        return exc.exit_code
    except MultiLineError as exc:
        output.error_multi_line(exc.lines, sensitive=exc.sensitive)
        return exc.exit_code
    except AppctlError as exc:
        output.error(exc.message, sensitive=exc.sensitive)
        return exc.exit_code


def is_completion_request(positional):
    """Tab completion runs ``cli completions``; it is never logged."""
    return list(positional[:2]) == ["cli", "completions"]


def runs_startup(positional):
    """First-run setup and the version comparison run for everything but tab completion."""
    return not is_completion_request(positional)


# Commands that never trigger the automatic update check.
NO_AUTO_UPDATE = ("cli check-update", "cli completions", "cli has-command", "cli self-uninstall",
                  "cli update")


class Runner:
    def __init__(self, argv, parsed, environ, output, strict, loaded, cwd=None):
        self.argv = argv
        self.cwd = cwd
        self.parsed = parsed
        self.environ = environ
        self.output = output
        self.strict = strict
        self.loaded = loaded
        self._root = None
        self._requirements_met = False

    @property
    def root(self):
        if self._root is None:
            self._root = build_command_tree()
        return self._root

    def target_command(self):
        """The command the positional arguments resolve to, or ``None``."""
        resolved = try_resolve(self.root, self.parsed.positional)
        return resolved[0] if resolved else None

    def ensure_requirements(self, command):
        if self._requirements_met or not system.requires_system_check(command):
            return
        system.ensure_requirements(self.environ, self.output)
        self._requirements_met = True

    def auto_update(self, command):
        """Periodic update check; an exit code when it ran an update."""
        if command is None or command.full_name in NO_AUTO_UPDATE:
            return None
        if is_machine_readable(command, self.parsed.assoc):
            return None
        return self_update.auto_check_update(self.environ, self.output)

    # -- aliases ----------------------------------------------------------

    def run_alias(self, name, stack=()):
        aliases = self.loaded.aliases
        if name == config_loader.ALL_ALIAS and not aliases:
            raise AppctlError("Cannot use '@all' when no aliases are registered.")
        if name not in aliases:
            message = f"Alias '{name}' not found."
            suggestion = get_suggestion(name, list(aliases))
            if suggestion:
                message += f"\nDid you mean '{suggestion}'?"
            raise AppctlError(message)
        definition = aliases[name]
        if name == config_loader.ALL_ALIAS and definition is None:
            members = sorted((a for a, d in aliases.items() if a != name and not isinstance(d, list)),
                             key=config_loader.alias_sort_key)
            return self.run_group(name, members, stack)
        if isinstance(definition, list):
            members = _unique(definition)
            invalid = [m for m in members if m not in aliases]
            if invalid:
                raise AppctlError(
                    f"Group '{name}' contains one or more invalid aliases: {', '.join(invalid)}."
                )
            return self.run_group(name, members, stack)
        return self.run(name, definition if isinstance(definition, dict) else {})

    def run_group(self, name, members, stack):
        stack = stack + (name,)
        result = 0
        for member in members:
            if member in stack:
                continue
            self.output.log(member)
            self.output.stdout.flush()
            code = guarded(self.output, self.run_alias, member, stack)
            self.output.stdout.flush()
            if code:
                result = code
        return result

    # -- a single execution ----------------------------------------------

    def run(self, alias=None, alias_params=None):
        runtime = build_runtime_config(self.parsed.runtime, self.loaded.merged, alias_params)
        self.output.set_color(runtime.get("color"))
        if runtime.get("ssh"):
            return run_remote(runtime["ssh"], self.argv, self.environ, self.output,
                              alias=alias, alias_params=alias_params,
                              skip_tty=bool(runtime.get("skip-tty")))
        positional = self.parsed.positional
        if not positional:
            self.output.line(render_root_help(self.root))
            return 0
        command, remaining = resolve(self.root, positional)
        check_disabled(command, positional, runtime["disabled_commands"])
        self.ensure_requirements(command)
        if not command.is_runnable:
            self.output.line(render_usage(command))
            return 0
        self.output.debug(f"Running command: {command.full_name}")
        args, assoc = ArgumentValidator(command).validate(
            remaining, self.parsed.assoc, warn=self.output.warning,
            read_stdin=self.output.read_stdin,
        )
        context = Context(root=self.root, command=command, output=self.output,
                          runtime=runtime, strict=self.strict, config=self.loaded,
                          alias=alias, cwd=self.cwd or os.getcwd(), environ=self.environ,
                          argv=list(self.argv))
        return command.handler(context, args, assoc)


def main(argv=None, environ=None, stdout=None, stderr=None, cwd=None, stdin=None):
    started = time.monotonic()
    argv = sys.argv[1:] if argv is None else list(argv)
    environ = os.environ if environ is None else environ
    strict = is_strict_mode(environ)

    invocation = list(argv)
    alias, argv = extract_alias(argv)
    parsed = parse_argv(apply_rewrites(argv), strict=strict)
    logger = FileLogger(log_path(config_loader.root_dir(environ)),
                        enabled=not is_completion_request(parsed.positional))
    logger.start_invocation(invocation)
    output = Output(quiet=bool(parsed.runtime.get("quiet")), debug=parsed.runtime.get("debug", False),
                    stdout=stdout, stderr=stderr, stdin=stdin,
                    color=parsed.runtime.get("color", "auto"), logger=logger, start_time=started)
    for warning in deprecation_warnings(parsed.runtime):
        print(warning, file=output.stderr)

    def start():
        db = database.get_db(environ)
        loaded = config_loader.load(environ, cwd)
        output.set_color(build_runtime_config(parsed.runtime, loaded.merged)["color"])
        runner = Runner(argv, parsed, environ, output, strict, loaded, cwd)
        target = runner.target_command()
        if runs_startup(parsed.positional):
            Startup(environ, output, db, target, parsed.assoc).run()
            updated = runner.auto_update(target)
            if updated is not None:
                return updated
        output.debug(f"Using global config: {loaded.global_path}", group="bootstrap")
        if loaded.project_path:
            output.debug(f"Using project config: {loaded.project_path}", group="bootstrap")
        else:
            output.debug("No project config found.", group="bootstrap")
        if alias:
            return runner.run_alias(alias)
        return runner.run()

    code = guarded(output, start)
    database.close_all()
    # After a self-uninstall the root directory is gone; do not recreate it.
    if not is_completion_request(parsed.positional) and os.path.isdir(
            config_loader.root_dir(environ)):
        clean_cache(environ, output)
    return code


def clean_cache(environ, output):
    """Deterministic end-of-invocation cache cleanup (expiry, then LRU size limit)."""
    try:
        get_cache(environ, output).clean()
    except Exception:  # cleanup must never affect the command's outcome
        pass
