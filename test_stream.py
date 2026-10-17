import json
import unittest
from unittest.mock import Mock

import requests
from Stream import Stream


def response(status=200, payload=None, raw=None):
    result = requests.Response()
    result.status_code = status
    result.url = "https://example.invalid/test"
    result._content = (raw if raw is not None else json.dumps(payload)).encode()
    return result


class StreamTests(unittest.TestCase):
    def setUp(self):
        self.client = Stream("unit-account-token")
        self.client.s = Mock()

    def prepared(self):
        self.client.s.post.return_value = response(payload={
            "id": "session-1", "rtmp": "rtmps://example.invalid/app", "key": "unit-key"})
        return self.client.start("Test", "")

    def test_start_retains_session_and_blocks_duplicate(self):
        self.assertEqual(self.prepared(), ("rtmps://example.invalid/app", "unit-key"))
        self.assertEqual(self.client.id, "session-1")
        self.assertEqual(self.client.start("Again", ""), (None, None))
        self.assertEqual(self.client.s.post.call_count, 1)

    def test_partial_start_keeps_id_for_end(self):
        self.client.s.post.return_value = response(payload={"id": "session-1"})
        self.assertEqual(self.client.start("Test", ""), (None, None))
        self.assertEqual(self.client.id, "session-1")
        self.assertTrue(self.client.session_uncertain)

    def test_timeout_start_is_uncertain_and_cannot_duplicate(self):
        self.client.s.post.side_effect = requests.Timeout("PRIVATE VALUE")
        self.client.start("Test", "")
        self.assertTrue(self.client.session_uncertain)
        self.client.start("Again", "")
        self.assertEqual(self.client.s.post.call_count, 1)
        self.assertNotIn("PRIVATE VALUE", self.client.last_error)

    def test_unauthorized_start_has_useful_safe_error(self):
        self.client.s.post.return_value = response(401, {"token": "PRIVATE VALUE"})
        self.client.start("Test", "")
        self.assertFalse(self.client.session_uncertain)
        self.assertIn("401", self.client.last_error)
        self.assertNotIn("PRIVATE VALUE", self.client.last_error)

    def test_server_error_start_requires_manual_reconciliation(self):
        self.client.s.post.return_value = response(503, {})
        self.client.start("Test", "")
        self.assertTrue(self.client.session_uncertain)

    def test_end_success_clears_session(self):
        self.prepared()
        self.client.s.post.return_value = response(payload={"success": True})
        self.assertTrue(self.client.end())
        self.assertIsNone(self.client.id)
        self.assertFalse(self.client.session_uncertain)

    def test_end_no_content_is_confirmed(self):
        self.prepared()
        self.client.s.post.return_value = response(204, raw="")
        self.assertTrue(self.client.end())
        self.assertIsNone(self.client.id)

    def test_end_timeout_retains_session_for_retry(self):
        self.prepared()
        self.client.s.post.side_effect = requests.Timeout()
        self.assertFalse(self.client.end())
        self.assertEqual(self.client.id, "session-1")
        self.assertTrue(self.client.session_uncertain)

    def test_404_does_not_claim_offline(self):
        self.prepared()
        self.client.s.post.return_value = response(404, {})
        self.assertFalse(self.client.end())
        self.assertEqual(self.client.id, "session-1")

    def test_empty_success_does_not_falsely_confirm_end(self):
        self.prepared()
        self.client.s.post.return_value = response(payload={})
        self.assertFalse(self.client.end())
        self.assertTrue(self.client.last_error)
        self.assertEqual(self.client.id, "session-1")

    def test_rejected_remote_body_never_leaks_secret(self):
        self.client.s.post.return_value = response(payload={"success": False, "message": "PRIVATE VALUE"})
        self.client.start("Test", "")
        self.assertNotIn("PRIVATE VALUE", self.client.last_error)

    def test_explicit_rejection_is_not_uncertain_and_allows_retry(self):
        self.client.s.post.return_value = response(payload={"success": False})
        self.assertEqual(self.client.start("Test", ""), (None, None))
        self.assertFalse(self.client.session_uncertain)
        self.assertTrue(self.client.last_error)
        self.client.s.post.return_value = response(
            payload={"id": "session-2", "rtmp": "rtmps://example.invalid/app", "key": "key"}
        )
        self.assertEqual(
            self.client.start("Test", ""),
            ("rtmps://example.invalid/app", "key"),
        )
        self.assertEqual(self.client.id, "session-2")

    def test_bad_json_drops_stale_payload(self):
        self.client.last_response = {"id": "old"}
        self.client.s.get.return_value = response(raw="not-json")
        self.assertEqual(self.client.getInfo(), {})
        self.assertEqual(self.client.last_response, {})
        self.assertTrue(self.client.last_error)

    def test_categories_use_encoded_params_and_handle_missing_data(self):
        self.client.s.get.return_value = response(payload={"categories": None})
        self.assertEqual(self.client.search("a&b"), [])
        self.assertEqual(self.client.s.get.call_args.kwargs["params"], {"category": "a&b"})

    def test_category_shape_is_bounded_to_valid_items(self):
        self.client.s.get.return_value = response(payload={"categories": [None, {}, {"full_name": "Game", "game_mask_id": "12"}]})
        self.assertEqual(self.client.search("Game"), [{"full_name": "Game", "game_mask_id": "12"}, {"full_name": "Other", "game_mask_id": ""}])

    def test_invalid_credentials_remain_recoverable_by_id(self):
        self.client.s.post.return_value = response(payload={"id": "session-1", "rtmp": 42, "key": ["bad"]})
        self.assertEqual(self.client.start("Test", ""), (None, None))
        self.assertEqual(self.client.id, "session-1")
        self.assertTrue(self.client.session_uncertain)


if __name__ == "__main__":
    unittest.main()
