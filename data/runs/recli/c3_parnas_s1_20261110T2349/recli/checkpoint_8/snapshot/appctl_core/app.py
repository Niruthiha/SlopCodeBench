"""Pipeline wiring.

Secret: the order in which the stages run (alias split, lex, rewrite,
extract globals, load config, expand aliases, resolve, bind, run or hand
off to a remote transport) and how failures map to output and exit codes.
"""

import os
import time

from . import (aliases, binding, catalog, config_files, db, dispatch, file_cache,
               help_text, logfile, process, remote, rewrites, runtime_config,
               startup, tokens, values)
from .command_tree import CommandTree
from .errors import CliError, Halt, MissingPositional
from .output import Output, color_enabled

_COMPLETION_WORDS = ("completions", "completion")


class CommandContext:
    """Everything a command handler may use."""

    def __init__(self, command, args, out, config, tree, cwd=None, cache=None,
                 launcher=None, db=None, env=None, raw_options=()):
        self.command = command
        self.args = args
        # ``(name, value)`` pairs in command-line order.
        self.raw_options = list(raw_options)
        self.out = out
        self.config = config
        self.tree = tree
        self.cwd = cwd if cwd is not None else os.getcwd()
        self.cache = cache
        self.launcher = launcher
        self.db = db
        self.env = dict(env) if env is not None else dict(os.environ)

    def run_process(self, command, **kwargs):
        """Run an external command (see ``process.run``)."""
        kwargs.setdefault("out", self.out)
        kwargs.setdefault("cwd", self.cwd)
        return process.run(command, **kwargs)

    def launch_self(self, command, *args, **kwargs):
        """Re-dispatch an appctl command in a child process (see
        ``process.Launcher.launch_self``)."""
        return self.launcher.launch_self(command, *args, **kwargs)

    def runcommand(self, command, **kwargs):
        """Run an appctl command in a child process and return its output
        (see ``process.Launcher.runcommand``)."""
        return self.launcher.runcommand(command, **kwargs)

    def read_value(self, index):
        """Positional ``index``, or STDIN when it was not given, decoded
        according to ``--format``; ``None`` when neither is available."""
        raw = self.args.positional(index)
        if raw is None:
            raw = self.out.read_stdin()
            if raw is None:
                return None
        return values.read_value(raw, self.args.option("format"))


def build_tree():
    tree = CommandTree()
    catalog.register_all(tree)
    return tree


def _split_alias(argv):
    """Remove a leading ``@alias`` word; return ``(alias, argv)``."""
    for index, raw in enumerate(argv):
        if raw == "--":
            break
        if raw.startswith("--") and len(raw) > 2:
            continue
        if aliases.is_alias_name(raw):
            return raw, argv[:index] + argv[index + 1:]
        break
    return None, argv


def _is_completion(argv):
    """Tab-completion invocations are never written to the log file."""
    words = []
    for raw in argv:
        if raw == "--":
            break
        if not raw.startswith("--"):
            words.append(raw)
    return len(words) >= 2 and words[0] == "cli" and words[1] in _COMPLETION_WORDS


def _last_option(options, name):
    found = None
    for key, value in options:
        if key == name:
            found = value
    return found


class _Invocation:
    def __init__(self, argv, env, stdout, stderr, tree, cwd, stdin, started):
        self.argv = argv
        self.env = env
        self.stdout = stdout
        self.stderr = stderr
        self.tree = tree
        self.cwd = cwd
        self.stdin = stdin
        self.started = started

    def _color(self, setting):
        return color_enabled(setting, self.stdout)

    def start(self, alias):
        self.locations = config_files.Locations(self.env)
        log = logfile.LogFile(logfile.log_path(self.locations.root_dir),
                              enabled=not _is_completion(self.argv))
        log.start_invocation()
        self.out = out = Output(self.stdout, self.stderr, stdin=self.stdin, log=log,
                                start=self.started, color=self._color("auto"))
        try:
            items = rewrites.apply(tokens.lex(self.argv))
            self.runtime, self.items = runtime_config.extract(items, self.env)
        except CliError as exc:
            out.report(exc)
            return exc.exit_code
        runtime_values = self.runtime.values
        out.configure(quiet=self.runtime.quiet(),
                      debug=runtime_values.get("debug", False),
                      color=self._color(runtime_values.get("color", "auto")))
        for warning in self.runtime.warnings:
            out.warning(warning)
        self.cache = file_cache.from_env(self.env, self.locations.root_dir,
                                         warn=out.warning)
        try:
            self.db = db.open_database(self.locations.root_dir)
        except CliError as exc:
            out.report(exc)
            return exc.exit_code
        try:
            return self.load_and_execute(alias)
        finally:
            self.db.close()
            if not _is_completion(self.argv):
                try:
                    self.cache.clean()
                except OSError:
                    pass

    def load_and_execute(self, alias):
        out = self.out
        try:
            self.loaded = config_files.load(self.locations, self.cwd)
            if "color" not in self.runtime.values:
                out.configure(color=self._color(self.loaded.values.get("color", "auto")))
            self.registry = aliases.AliasRegistry(
                self.loaded.aliases, aliases.runtime_aliases(self.env))
            for path in self.loaded.files:
                out.debug(f"Loaded config file: {path}", group="bootstrap")
            return self.execute(alias, ())
        except CliError as exc:
            out.report(exc)
            return exc.exit_code
        except Halt as exc:
            return exc.exit_code

    def execute(self, alias, stack):
        if alias is None:
            return self.invoke({})
        target = self.registry.resolve(alias)
        if not target.is_group():
            return self.invoke(target.connection)
        code = 0
        for member in target.members:
            if member == alias or member in stack:
                continue
            self.out.log(member)
            try:
                result = self.execute(member, stack + (alias,))
            except CliError as exc:
                self.out.report(exc)
                result = exc.exit_code
            code = result or code
        return code

    def invoke(self, connection):
        config = runtime_config.layer(
            self.runtime, self.loaded.values, connection,
            locations=self.locations, loaded=self.loaded, aliases=self.registry)
        self.out.configure(color=self._color(config.color()))
        if config.ssh():
            return remote.run(config.ssh(), self.argv, connection,
                              self.runtime.values, config, self.env, self.out,
                              self.stdout, self.stderr)
        return self.run_local(config)

    def run_local(self, config):
        out = self.out
        if self.tree is None:
            self.tree = build_tree()
        tree = self.tree
        items = self.items
        words = [t.text for t in items if not t.is_option()] or ["help"]
        options = [(t.name, t.value) for t in items if t.is_option()]
        node = None
        try:
            node, remaining = dispatch.resolve(tree, words, config.disabled_commands())
            out.debug(f"Resolved command '{node.path}' with arguments {remaining}",
                      group="bootstrap")
            out.log_only(f"Command: {node.path}")
            self.start_command(node, options, config)
            if not node.is_runnable():
                out.usage(help_text.composite_usage(node))
                return 0
            remaining = self.stdin_fallback(node.synopsis, remaining, options)
            bound = binding.bind(node.path, node.synopsis, node.defaults(),
                                 remaining, options)
            launcher = process.Launcher(
                self.runtime.values, self.env, self.cwd, out,
                config_path=self.locations.global_config_path)
            result = node.run(CommandContext(node, bound, out, config, tree,
                                             cwd=self.cwd, cache=self.cache,
                                             launcher=launcher, db=self.db,
                                             env=self.env, raw_options=options))
            return int(result or 0)
        except MissingPositional:
            out.usage(help_text.usage_line(node))
            return 1

    def start_command(self, node, options, config):
        """Check the host, set up a first run or migrate after a version
        change, and check for updates: once per invocation."""
        if getattr(self, "startup_done", False):
            return
        self.startup_done = True
        from . import cli_commands
        startup.Startup(node, options, self.out, self.env, self.db, config, self.stdout,
                        cache=self.cache,
                        update=lambda: cli_commands.self_update(self.out, self.env)).run()

    def stdin_fallback(self, synopsis, words, options):
        """Read a missing required positional from STDIN, if any is piped."""
        if len(words) >= synopsis.required_positional_count():
            return words
        raw = self.out.read_stdin()
        if raw is None:
            return words
        fmt = (_last_option(options, "format")
               if "format" in synopsis.option_names() else None)
        return list(words) + [values.read_value(raw, fmt)]


def run(argv, env, stdout, stderr, tree=None, cwd=None, stdin=None):
    """Run one invocation and return its exit code.

    ``stdin`` defaults to ``sys.stdin`` at the time input is needed.
    """
    started = time.monotonic()
    alias, argv = _split_alias(list(argv))
    invocation = _Invocation(argv, env, stdout, stderr, tree,
                             cwd if cwd is not None else os.getcwd(), stdin, started)
    return invocation.start(alias)
