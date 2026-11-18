"""Tumbling windows.

Secret: the duration units and the epoch-aligned window arithmetic.
"""

from . import timestamps
from .errors import DslError

_UNIT_SECONDS = {"m": 60, "h": 3600, "d": 86400}


class TumblingWindow:
    def __init__(self, amount, unit):
        if unit not in _UNIT_SECONDS or amount <= 0:
            raise DslError("invalid window duration %s%s" % (amount, unit))
        self._width = amount * _UNIT_SECONDS[unit] * 1000000

    def bounds(self, instant):
        """(start, end) instants of the window containing `instant`."""
        start = timestamps.to_epoch_micros(instant) // self._width * self._width
        return timestamps.from_epoch_micros(start), timestamps.from_epoch_micros(start + self._width)
