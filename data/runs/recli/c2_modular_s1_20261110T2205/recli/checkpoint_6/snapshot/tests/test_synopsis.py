import unittest

from appctl_cli.command import Command
from appctl_cli.errors import SynopsisError
from appctl_cli.synopsis import classify_token, parse_synopsis


class ClassifyTokenTest(unittest.TestCase):
    def test_positional(self):
        token = classify_token("<site-name>")
        self.assertEqual((token.type, token.name, token.optional), ("positional", "site-name", False))

    def test_optional_repeating_positional(self):
        token = classify_token("[<plugin>...]")
        self.assertEqual((token.type, token.optional, token.repeating), ("positional", True, True))

    def test_keyed_parameter(self):
        token = classify_token("--type=<type>")
        self.assertEqual((token.type, token.name, token.value_name), ("assoc", "type", "type"))

    def test_flags(self):
        self.assertEqual(classify_token("[--force]").type, "flag")
        negatable = classify_token("[--[no-]color]")
        self.assertEqual((negatable.type, negatable.name, negatable.negatable), ("flag", "color", True))

    def test_mandatory_flag_is_malformed(self):
        self.assertEqual(classify_token("--force").type, "unknown")

    def test_generic(self):
        self.assertEqual(classify_token("[--<field>=<value>]").type, "generic")

    def test_malformed(self):
        for token in ("site", "<bad name", "--type=type", "-f", "--[no-]x=<v>"):
            self.assertEqual(classify_token(token).type, "unknown", token)

    def test_parse(self):
        types = [t.type for t in parse_synopsis("<a> [--b=<b>] [--c] [--<field>=<value>]")]
        self.assertEqual(types, ["positional", "assoc", "flag", "generic"])

    def test_malformed_synopsis_rejected_at_registration(self):
        with self.assertRaises(SynopsisError):
            Command("bad", synopsis="<ok> nonsense")


if __name__ == "__main__":
    unittest.main()
