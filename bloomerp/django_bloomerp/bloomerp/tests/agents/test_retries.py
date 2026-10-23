"""Verify bounded HTTP retry policy independently of provider implementations."""

from datetime import UTC, datetime, timedelta
from email.utils import format_datetime
from unittest import TestCase
from unittest.mock import patch

import httpx

from bloomerp.agents.retries import model_retry_delay, retry_after_seconds


class ModelRetryPolicyTests(TestCase):
    """Cover server-directed waits, fallback delays and finite retry limits."""

    def wrapped_error(self, header: str) -> Exception:
        """Build a generic wrapped HTTP failure with no dependency on a provider SDK."""
        request = httpx.Request("POST", "https://example.test/model")
        response = httpx.Response(429, request=request, headers={"Retry-After": header})
        error = RuntimeError("SDK wrapper")
        error.__cause__ = httpx.HTTPStatusError("busy", request=request, response=response)
        return error

    def test_retry_after_and_backoff(self) -> None:
        """Respect numeric and HTTP-date headers, falling back for malformed values."""
        self.assertEqual(retry_after_seconds(self.wrapped_error("12")), 12)
        future = format_datetime(datetime.now(UTC) + timedelta(seconds=20), usegmt=True)
        delay = retry_after_seconds(self.wrapped_error(future))
        self.assertGreater(delay, 18)
        self.assertLessEqual(delay, 20)
        for invalid in ("invalid", "nan", "inf"):
            with self.subTest(header=invalid):
                self.assertIsNone(retry_after_seconds(self.wrapped_error(invalid)))
        with patch("bloomerp.agents.retries.random.uniform", return_value=0.5):
            self.assertEqual([model_retry_delay(i, None) for i in range(3)], [2.5, 4.5, 8.5])
            self.assertEqual(model_retry_delay(0, 12), 12)
        self.assertIsNone(model_retry_delay(3, None))
        self.assertIsNone(model_retry_delay(0, 60))

