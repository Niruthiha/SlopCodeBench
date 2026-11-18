"""Pipeline wiring.

Secret: the order in which the stages run (alias split, lex, rewrite,
extract globals, load config, expand aliases, resolve, bind, run or hand
off to a remote transport) and how failures map to output and exit codes.
"""

import os

from . import (aliases, binding, catalog, config_files, dispatch, help_text,
               remote, rewrites, runtime_config, tokens)
from .command_tree import CommandTree
from .errors import CliError, MissingPositional
from .output import Output


class CommandContext:
    """Everything a command handler may use."""

    def __init__(self, command, args, out, config, tree):
        self.command = command
        self.args = args
        self.out = out
        self.config = config
        self.tree = tree


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


class _Invocation:
    def __init__(self, argv, env, stdout, stderr, tree, cwd):
        self.argv = argv
        self.env = env
        self.stdout = stdout
        self.stderr = stderr
        self.tree = tree
        self.cwd = cwd

    def start(self, alias):
        out = Output(self.stdout, self.stderr)
        try:
            items = rewrites.apply(tokens.lex(self.argv))
            self.runtime, self.items = runtime_config.extract(items, self.env)
        except CliError as exc:
            out.error(exc.message)
            return exc.exit_code
        self.out = out = Output(self.stdout, self.stderr,
                                quiet=self.runtime.quiet(), debug=self.runtime.debug())
        for warning in self.runtime.warnings:
            out.warning(warning)
        try:
            self.locations = config_files.Locations(self.env)
            self.loaded = config_files.load(self.locations, self.cwd)
            self.registry = aliases.AliasRegistry(
                self.loaded.aliases, aliases.runtime_aliases(self.env))
            for path in self.loaded.files:
                out.debug(f"Loaded config file: {path}")
            return self.execute(alias, ())
        except CliError as exc:
            out.error(exc.message)
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
                self.out.error(exc.message)
                result = exc.exit_code
            code = result or code
        return code

    def invoke(self, connection):
        config = runtime_config.layer(
            self.runtime, self.loaded.values, connection,
            locations=self.locations, loaded=self.loaded, aliases=self.registry)
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
            out.debug(f"Resolved command '{node.path}' with arguments {remaining}")
            if not node.is_runnable():
                out.usage(help_text.composite_usage(node))
                return 0
            bound = binding.bind(node.path, node.synopsis, node.defaults(),
                                 remaining, options)
            result = node.run(CommandContext(node, bound, out, config, tree))
            return int(result or 0)
        except MissingPositional:
            out.usage(help_text.usage_line(node))
            return 1


def run(argv, env, stdout, stderr, tree=None, cwd=None):
    """Run one invocation and return its exit code."""
    alias, argv = _split_alias(list(argv))
    invocation = _Invocation(argv, env, stdout, stderr, tree,
                             cwd if cwd is not None else os.getcwd())
    return invocation.start(alias)
