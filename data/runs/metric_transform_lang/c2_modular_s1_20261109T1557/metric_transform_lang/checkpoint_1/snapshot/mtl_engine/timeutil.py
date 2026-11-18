"""Timestamp parsing, timezone handling, epoch arithmetic and UTC formatting."""
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)
ONE_MICROSECOND = timedelta(microseconds=1)


def resolve_timezone(name):
    """Return a tzinfo for an IANA name; raise ValueError when unknown."""
    if name in ("UTC", "Z", "utc"):
        return timezone.utc
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError, OSError) as exc:
        raise ValueError(f"unknown timezone '{name}'") from exc


class TimestampParser:
    """Parses raw timestamp strings into timezone-aware UTC datetimes."""

    def __init__(self, default_tz, fmt=None):
        self.default_tz = default_tz
        self.fmt = fmt

    def parse(self, text):
        """Parse text; raise ValueError when it is not a valid timestamp."""
        raw = text.strip()
        if not raw:
            raise ValueError("empty timestamp")
        if self.fmt is not None:
            dt = datetime.strptime(raw, self.fmt)
        else:
            dt = _parse_iso(raw)
        if dt.tzinfo is None or dt.tzinfo.utcoffset(dt) is None:
            dt = dt.replace(tzinfo=self.default_tz)
        return dt.astimezone(timezone.utc)


def _parse_iso(raw):
    candidate = raw
    if candidate[-1] in "zZ":
        candidate = candidate[:-1] + "+00:00"
    return datetime.fromisoformat(candidate)


def epoch_micros(dt):
    return (dt - EPOCH) // ONE_MICROSECOND


def from_epoch_micros(micros):
    return EPOCH + timedelta(microseconds=micros)


def format_utc(dt):
    """ISO 8601 in UTC with a trailing Z."""
    dt = dt.astimezone(timezone.utc)
    if dt.microsecond:
        return dt.strftime("%Y-%m-%dT%H:%M:%S.%f") + "Z"
    return dt.strftime("%Y-%m-%dT%H:%M:%S") + "Z"
