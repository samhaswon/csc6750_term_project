import unittest

from ollama_proxy.main import _decode_response_payload


class ResponsePayloadParsingTests(unittest.TestCase):
    def test_decodes_regular_json_object(self):
        payload = b'{"status":"success"}'
        result = _decode_response_payload(payload)
        self.assertEqual(result, {"status": "success"})

    def test_decodes_ndjson_and_returns_last_entry(self):
        payload = (
            b'{"status":"pulling manifest"}\n'
            b'{"status":"downloading","completed":10,"total":100}\n'
            b'{"status":"success"}\n'
        )
        result = _decode_response_payload(payload)
        self.assertEqual(result, {"status": "success"})

    def test_ignores_invalid_lines_in_ndjson(self):
        payload = b'{"status":"pulling"}\nnot-json\n{"status":"success"}\n'
        result = _decode_response_payload(payload)
        self.assertEqual(result, {"status": "success"})


if __name__ == "__main__":
    unittest.main()
