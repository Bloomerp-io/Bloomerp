"""Validate message text formats independently of Django and the database."""

from unittest import TestCase

from pydantic import ValidationError

from bloomerp.agents.definition import MessageContent


class MessageFormatTests(TestCase):
    """Keep text format explicit while accepting existing plain-text messages."""

    def test_missing_format_defaults_to_plain(self) -> None:
        """Normalize earlier text blocks to an explicit plain-text format."""
        content = MessageContent.model_validate([{"type": "text", "text": "Hello"}])
        self.assertEqual(
            content.model_dump(mode="json"),
            [{"type": "text", "format": "plain", "text": "Hello"}],
        )

    def test_supported_formats_round_trip_in_mixed_messages(self) -> None:
        """Preserve formatted text and artifact references without converting markup."""
        for text_format, text in (
            ("plain", "<p>Literal markup</p>"),
            ("html", "<p>Hello <strong>world</strong></p>"),
            ("markdown", "Hello **world**"),
        ):
            with self.subTest(format=text_format):
                blocks = [
                    {"type": "text", "format": text_format, "text": text},
                    {"type": "artifact", "position": 0},
                ]
                content = MessageContent.model_validate(blocks)
                self.assertEqual(content.model_dump(mode="json"), blocks)

    def test_invalid_formats_are_rejected(self) -> None:
        """Reject unknown formats and malformed values instead of guessing rendering."""
        for text_format in ("xml", "HTML", "", None, 42):
            with self.subTest(format=text_format), self.assertRaises(ValidationError):
                MessageContent.model_validate(
                    [{"type": "text", "format": text_format, "text": "Hello"}]
                )
