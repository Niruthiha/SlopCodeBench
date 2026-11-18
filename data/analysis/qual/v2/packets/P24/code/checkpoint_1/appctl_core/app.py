"""Pipeline wiring.

Secret: the order in which the stages run (lex, rewrite, extract globals,
resolve, bind, run) and how failures map to output and exit codes.
"""

from . import binding, catalog, dispatch, help_text, rewrites, runtime_config, tokens
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


def run(argv, env, stdout, stderr, tree=None):
    """Run one invocation and return its exit code."""
    out = Output(stdout, stderr)
    try:
        items = rewrites.apply(tokens.lex(argv))
        config, items = runtime_config.extract(items, env)
    except CliError as exc:
        out.error(exc.message)
        return exc.exit_code
    out = Output(stdout, stderr, quiet=config.quiet(), debug=config.debug())
    tree = tree if tree is not None else build_tree()

    words = [t.text for t in items if not t.is_option()] or ["help"]
    options = [(t.name, t.value) for t in items if t.is_option()]
    node = None
    try:
        node, remaining = dispatch.resolve(tree, words)
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
    except CliError as exc:
        out.error(exc.message)
        return exc.exit_code
