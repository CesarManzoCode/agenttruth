"""Local-time helpers for the generator and the ledger (project timezone, millisecond UTC epochs)."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

__all__ = ["DAY_MS", "Clock"]

DAY_MS = 86_400_000
_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)


class Clock:
    """Conversions between naive local datetimes, local dates and UTC epoch milliseconds."""

    def __init__(self, timezone: str) -> None:
        self.tz = ZoneInfo(timezone)

    def local_ms(self, local: datetime) -> int:
        """UTC epoch ms of a naive local datetime (interpreted in the project timezone)."""
        aware = local.replace(tzinfo=self.tz)
        return (aware - _EPOCH) // timedelta(milliseconds=1)

    def day_start_ms(self, day: date) -> int:
        """UTC epoch ms of local midnight starting ``day``."""
        return self.local_ms(datetime(day.year, day.month, day.day))

    def local_datetime(self, ms: int) -> datetime:
        """Naive local datetime of a UTC epoch ms."""
        return (_EPOCH + timedelta(milliseconds=ms)).astimezone(self.tz).replace(tzinfo=None)

    def local_date(self, ms: int) -> date:
        """Local calendar date of a UTC epoch ms."""
        return self.local_datetime(ms).date()


def format_ts(ms: int) -> str:
    """ISO-8601 UTC with milliseconds and ``Z`` (the emitted timestamp format, §5.2)."""
    moment = _EPOCH + timedelta(milliseconds=ms)
    return moment.strftime("%Y-%m-%dT%H:%M:%S.") + f"{ms % 1000:03d}Z"


def parse_ts(text: str) -> int:
    """Inverse of :func:`format_ts`. Raises ``ValueError`` for another format."""
    if len(text) != 24 or not text.endswith("Z"):
        raise ValueError(f"not an AgentTruth timestamp: {text!r}")
    moment = datetime.strptime(text[:-1], "%Y-%m-%dT%H:%M:%S.%f").replace(tzinfo=UTC)
    return (moment - _EPOCH) // timedelta(milliseconds=1)


__all__ += ["format_ts", "parse_ts"]
