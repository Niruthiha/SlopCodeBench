import unittest

from appctl_cli.suggest import get_suggestion, levenshtein


class SuggestTest(unittest.TestCase):
    def test_levenshtein(self):
        self.assertEqual(levenshtein("kitten", "sitting"), 3)
        self.assertEqual(levenshtein("", "abc"), 3)

    def test_close_match(self):
        self.assertEqual(get_suggestion("sitee", ["site", "user"]), "site")

    def test_no_match(self):
        self.assertIsNone(get_suggestion("zzzzzz", ["site", "user"]))

    def test_synonym_only_when_registered(self):
        self.assertEqual(get_suggestion("new", ["create", "list"]), "create")
        self.assertIsNone(get_suggestion("new", ["make", "list"]))

    def test_deterministic_ties(self):
        options = ["cat", "bat", "hat"]
        results = {get_suggestion("at", list(reversed(options))) for _ in range(5)}
        self.assertEqual(results, {"bat"})
        self.assertEqual(get_suggestion("at", options), "bat")


if __name__ == "__main__":
    unittest.main()
