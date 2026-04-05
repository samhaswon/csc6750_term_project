import unittest

from ollama_proxy.main import parse_positive_int, parse_wake_words


class WakeWordConfigTests(unittest.TestCase):
    def test_parse_wake_words_normalizes_values(self):
        parsed = parse_wake_words("Hey Home,  OK HOME, , Jarvis")
        self.assertEqual(parsed, ["hey home", "ok home", "jarvis"])

    def test_parse_wake_words_falls_back_when_empty(self):
        parsed = parse_wake_words(" , , ")
        self.assertEqual(parsed, ["hey home"])

    def test_parse_positive_int_accepts_positive_numbers(self):
        parsed = parse_positive_int("1500", 8000)
        self.assertEqual(parsed, 1500)

    def test_parse_positive_int_falls_back_for_invalid_values(self):
        self.assertEqual(parse_positive_int(None, 8000), 8000)
        self.assertEqual(parse_positive_int("not-a-number", 8000), 8000)
        self.assertEqual(parse_positive_int("0", 8000), 8000)
        self.assertEqual(parse_positive_int("-3", 8000), 8000)


if __name__ == "__main__":
    unittest.main()
