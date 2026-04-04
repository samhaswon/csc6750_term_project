import unittest

from ollama_proxy.main import extract_tool_error, format_user_confirmation


class ToolResultHandlingTests(unittest.TestCase):
    def test_extract_tool_error_for_list_data_does_not_crash(self):
        tool_result = {"status": 200, "data": [{"id": "a"}, {"id": "b"}]}
        self.assertIsNone(extract_tool_error(tool_result))

    def test_extract_tool_error_from_batch_result(self):
        tool_result = {
            "status": 207,
            "data": [
                {"status": 200, "data": {"id": "light_kitchen"}},
                {"status": 404, "data": {"error": "device not found"}},
            ],
        }
        self.assertEqual(extract_tool_error(tool_result), "device not found")

    def test_format_confirmation_for_batch_calls(self):
        tool_call = {"batch": [{"action": "get", "id": "a"}, {"action": "get", "id": "b"}]}
        tool_result = {"status": 207, "data": []}
        self.assertEqual(format_user_confirmation(tool_call, tool_result), "Processed 2 tool calls.")


if __name__ == "__main__":
    unittest.main()
