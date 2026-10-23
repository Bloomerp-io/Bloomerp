"""Bound model-request retries using HTTP semantics, independently of provider SDKs."""

import math
import random
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime

MAX_MODEL_RETRIES = 3
MAX_RETRY_WAIT_SECONDS = 30.0
TRANSIENT_HTTP_STATUSES = frozenset({408, 429, 500, 502, 503, 504, 529})


def retry_after_seconds(error: Exception) -> float | None:
    """Read a standard Retry-After header from a wrapped SDK HTTP exception."""
    current: BaseException | None = error
    seen: set[int] = set()
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        response = getattr(current, "response", None)
        headers = getattr(response, "headers", {})
        value = headers.get("retry-after")
        if value is not None:
            try:
                seconds = float(value)
            except (ValueError, TypeError):
                try:
                    timestamp = parsedate_to_datetime(value)
                    if timestamp.tzinfo is None:
                        timestamp = timestamp.replace(tzinfo=UTC)
                    seconds = (timestamp - datetime.now(UTC)).total_seconds()
                except (ValueError, TypeError, OverflowError):
                    return None
            return max(0.0, seconds) if math.isfinite(seconds) else None
        current = current.__cause__ or current.__context__
    return None


def model_retry_delay(retries: int, retry_after: float | None) -> float | None:
    """Use bounded exponential backoff with jitter, never shortening a server wait."""
    if retries >= MAX_MODEL_RETRIES:
        return None
    if retry_after is not None and retry_after > MAX_RETRY_WAIT_SECONDS:
        return None
    return max(2.0 * 2**retries + random.uniform(0.0, 1.0), retry_after or 0.0)
