import unittest

from physical_agent.intelligence.perception.vlm_client import build_messages, parse_json_response


class VlmClientTest(unittest.TestCase):
    def test_build_messages_contains_image_url(self):
        messages = build_messages(
            question="松手后它会怎样运动？",
            image_data_url="data:image/png;base64,abc",
            context="直径约 20 cm",
        )

        self.assertEqual(messages[1]["content"][0]["type"], "text")
        self.assertEqual(
            messages[1]["content"][1]["image_url"]["url"],
            "data:image/png;base64,abc",
        )

    def test_parse_json_response_accepts_markdown_fence(self):
        parsed = parse_json_response('```json\n{"hello": "world"}\n```')

        self.assertEqual(parsed, {"hello": "world"})


if __name__ == "__main__":
    unittest.main()
