import unittest
from unittest.mock import Mock, patch

import quality_v2


class GeminiTransportTests(unittest.TestCase):
    def test_quota_error_issues_one_http_request(self):
        response = Mock(status_code=429)
        response.text = '{"error":{"message":"Quota exceeded for metric"}}'
        with patch.object(quality_v2.requests, "post", return_value=response) as post:
            with self.assertRaisesRegex(RuntimeError, "HTTP 429"):
                quality_v2.gemini("dummy", "model", "prompt")
        post.assert_called_once()

    def test_server_error_issues_one_http_request(self):
        response = Mock(status_code=503)
        response.text = '{"error":{"message":"unavailable"}}'
        with patch.object(quality_v2.requests, "post", return_value=response) as post:
            with self.assertRaisesRegex(RuntimeError, "HTTP 503"):
                quality_v2.gemini("dummy", "model", "prompt")
        post.assert_called_once()

    def test_successful_api_response_parses_text_once(self):
        response = Mock(status_code=200)
        response.json.return_value = {
            "candidates": [{
                "content": {"parts": [{"text": "回答です"}]},
                "groundingMetadata": {},
            }]
        }
        with patch.object(quality_v2.requests, "post", return_value=response) as post:
            text, sources, queries = quality_v2.gemini(
                "dummy", "model", "prompt", json_mode=True
            )
        self.assertEqual(text, "回答です")
        self.assertEqual(sources, [])
        self.assertEqual(queries, [])
        post.assert_called_once()


if __name__ == "__main__":
    unittest.main()
