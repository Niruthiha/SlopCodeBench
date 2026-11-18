import unittest

from appctl_cli.arguments import parse_argv
from appctl_cli.errors import AppctlError, CommandNotFoundError, UsageError
from appctl_cli.registry import CommandRegistry
from appctl_cli.resolver import resolve
from appctl_cli.rewrites import apply_rewrites
from appctl_cli.validator import ArgumentValidator


def handler(ctx, args, assoc):
    return 0


class ArgumentParsingTest(unittest.TestCase):
    def test_split(self):
        parsed = parse_argv(["site", "create", "x", "--type=a", "--force", "--no-color", "--url=u"])
        self.assertEqual(parsed.positional, ["site", "create", "x"])
        self.assertEqual(parsed.assoc, {"type": "a", "force": True})
        self.assertEqual(parsed.runtime, {"color": False, "url": "u"})

    def test_strict_mode(self):
        parsed = parse_argv(["--url=a", "site", "--url=b"], strict=True)
        self.assertEqual(parsed.runtime, {"url": "a"})
        self.assertEqual(parsed.assoc, {"url": "b"})

    def test_end_of_options(self):
        parsed = parse_argv(["db", "query", "--", "--weird"])
        self.assertEqual(parsed.positional, ["db", "query", "--weird"])


class RewriteTest(unittest.TestCase):
    def test_help(self):
        self.assertEqual(apply_rewrites(["site", "create", "--help"]), ["help", "site", "create"])
        self.assertEqual(apply_rewrites(["--help"]), ["help"])

    def test_version(self):
        self.assertEqual(apply_rewrites(["--version"]), ["cli", "version"])
        self.assertEqual(apply_rewrites(["plugin", "install", "x", "--version=1"]),
                         ["plugin", "install", "x", "--version=1"])


class ResolverTest(unittest.TestCase):
    def setUp(self):
        registry = CommandRegistry()
        registry.add("site", description="Sites")
        registry.add("site create", handler, synopsis="<name>", alias="make")
        registry.add("tool", handler, synopsis="[<arg>]")
        registry.add("tool sub", handler)
        self.root = registry.root

    def test_deepest_match(self):
        command, rest = resolve(self.root, ["site", "create", "x"])
        self.assertEqual((command.full_name, rest), ("site create", ["x"]))

    def test_alias(self):
        command, _ = resolve(self.root, ["site", "make", "x"])
        self.assertEqual(command.full_name, "site create")

    def test_runnable_parent_keeps_unmatched_tokens(self):
        command, rest = resolve(self.root, ["tool", "value"])
        self.assertEqual((command.full_name, rest), ("tool", ["value"]))

    def test_unknown(self):
        with self.assertRaises(CommandNotFoundError) as ctx:
            resolve(self.root, ["sit"])
        self.assertIn("Did you mean 'site'?", ctx.exception.message)
        with self.assertRaises(CommandNotFoundError) as ctx:
            resolve(self.root, ["site", "creat"])
        self.assertIn("is not a registered subcommand of 'site'", ctx.exception.message)


class ValidatorTest(unittest.TestCase):
    def make(self, synopsis, defaults=None):
        registry = CommandRegistry()
        return ArgumentValidator(registry.add("cmd", handler, synopsis=synopsis, defaults=defaults))

    def test_missing_positional(self):
        with self.assertRaises(UsageError) as ctx:
            self.make("<a> <b>").validate(["x"], {})
        self.assertEqual(ctx.exception.usage, "usage: appctl cmd <a> <b>")

    def test_too_many(self):
        with self.assertRaises(AppctlError) as ctx:
            self.make("<a>").validate(["x", "y", "z"], {})
        self.assertEqual(ctx.exception.message, "Too many positional arguments: y z")

    def test_repeating_accepts_extra(self):
        self.make("<a>...").validate(["x", "y", "z"], {})

    def test_assoc_errors_collected(self):
        with self.assertRaises(AppctlError) as ctx:
            self.make("--req=<v> [--force]").validate([], {"req": "", "forse": True})
        self.assertEqual(
            ctx.exception.message,
            "Parameter errors:\n missing --req parameter\n unknown --forse parameter\n"
            "Did you mean '--force'?",
        )

    def test_generic_accepts_unknown(self):
        self.make("[--<field>=<value>]").validate([], {"anything": "x"})

    def test_defaults(self):
        args, assoc = self.make("[<a>] [--b=<b>] [--c]", {"a": "A", "b": "B", "c": True}).validate([], {})
        self.assertEqual((args, assoc), (["A"], {"b": "B", "c": True}))
        args, assoc = self.make("[<a>] [--b=<b>]", {"a": "A", "b": "B"}).validate(["x"], {"b": "y"})
        self.assertEqual((args, assoc), (["x"], {"b": "y"}))


if __name__ == "__main__":
    unittest.main()
