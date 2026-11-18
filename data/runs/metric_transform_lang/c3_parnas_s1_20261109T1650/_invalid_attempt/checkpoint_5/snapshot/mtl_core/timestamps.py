"""Timestamps.

Secret: how timestamp text is parsed (ISO 8601 or an explicit strptime
format, with a default zone for naive values) and how instants are
represented and rendered.  Callers may rely only on the functions below and
on instants being totally ordered by the comparison operators.
"""

import re
from datetime import datetime, timedelta, timezone

from .errors import ExecutionError, InputError

try:
    from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
except ImportError:  # pragma: no cover
    ZoneInfo = None
    ZoneInfoNotFoundError = Exception

_EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)
_ISO_SHAPE = re.compile(r"^\s*\d{4}-?\d{2}-?\d{2}([T ]\d{2}(:?\d{2}(:?\d{2}([.,]\d+)?)?)?"
                        r"\s*(Z|z|[+-]\d{2}(:?\d{2}(:?\d{2})?)?)?)?\s*$")


def _resolve_zone(name):
    if name in ("UTC", "utc", "Z", "Etc/UTC"):
        return timezone.utc
    if ZoneInfo is None:
        raise InputError("timezone support unavailable for %r" % name)
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError, OSError):
        raise InputError("unknown timezone %r" % name)


class TimestampParser:
    """Turns timestamp text into instants; raises ValueError on bad text."""

    def __init__(self, tz_name="UTC", fmt=None):
        self._zone = _resolve_zone(tz_name)
        self._fmt = fmt

    def parse(self, text):
        text = text.strip()
        if self._fmt is not None:
            moment = datetime.strptime(text, self._fmt)
        else:
            if not text:
                raise ValueError("empty timestamp")
            if text[-1] in "zZ":
                text = text[:-1] + "+00:00"
            moment = datetime.fromisoformat(text)
        if moment.tzinfo is None:
            moment = moment.replace(tzinfo=self._zone)
        return moment.astimezone(timezone.utc)

    def localize(self, moment):
        """UTC instant of a datetime; naive values are taken in the default zone."""
        if moment.tzinfo is None:
            moment = moment.replace(tzinfo=self._zone)
        return moment.astimezone(timezone.utc)

    def iso_only(self):
        """A parser with the same default zone that ignores any explicit format."""
        twin = TimestampParser.__new__(TimestampParser)
        twin._zone = self._zone
        twin._fmt = None
        return twin

    def looks_like_timestamp(self, text):
        """Heuristic used for inferring the type of extra CSV columns."""
        if self._fmt is None and not _ISO_SHAPE.match(text):
            return False
        try:
            self.parse(text)
        except (ValueError, OverflowError):
            return False
        return True


def to_epoch_micros(instant):
    delta = instant - _EPOCH
    return (delta.days * 86400 + delta.seconds) * 1000000 + delta.microseconds


def from_epoch_micros(micros):
    try:
        return _EPOCH + timedelta(microseconds=micros)
    except OverflowError:
        raise ExecutionError("timestamp out of range")


def format_utc(instant):
    utc = instant.astimezone(timezone.utc)
    text = utc.strftime("%Y-%m-%dT%H:%M:%S")
    if utc.year < 1000:
        text = "%04d%s" % (utc.year, text[len(str(utc.year)):])
    if utc.microsecond:
        text += (".%06d" % utc.microsecond).rstrip("0")
    return text + "Z"


def calendar_part(instant, part):
    """Return 'day', 'month' or 'year' of the instant, taken in UTC."""
    utc = instant.astimezone(timezone.utc)
    return {"day": utc.day, "month": utc.month, "year": utc.year}[part]
