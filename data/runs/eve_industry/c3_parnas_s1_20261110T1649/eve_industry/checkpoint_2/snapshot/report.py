"""Canonical recipe report text.

Secret: the exact layout of the report -- labels, ordering, number
formatting, time rounding, and how the materials table is sorted and drawn.
"""

import math
from dataclasses import dataclass


@dataclass(frozen=True)
class ReportInput:
    item_name: str
    type_id: int
    category: str
    group: str
    market_path: tuple  # market group names, root to leaf
    tech_level: str
    volume: float
    volume_is_packaged: bool
    activity: str
    output_quantity: int
    seconds: int
    materials: tuple  # of (name, quantity, buildable)


def _volume_text(volume, packaged):
    if packaged:
        return "%.2f" % volume
    text = repr(float(volume))
    if "e" in text or "E" in text:
        text = format(volume, "f").rstrip("0")
        text = text + "0" if text.endswith(".") else text
    return text


def render(data):
    market = " > ".join(data.market_path) if data.market_path else "None"
    lines = [
        "ITEM: %s (%d)" % (data.item_name, data.type_id),
        "Group: %s > %s" % (data.category, data.group),
        "Market Group: %s" % market,
        "Tech Level: %s" % data.tech_level,
        "Volume: %s" % _volume_text(data.volume, data.volume_is_packaged),
        "",
        "Recipe:",
        "Activity: %s" % data.activity,
        "Output Quantity: %d" % data.output_quantity,
        "Run Time: %d" % math.ceil(data.seconds / 60),
        "| Item | Quantity | Buildable |",
        "|:-:|:---:|---:|",
    ]
    for name, quantity, buildable in sorted(data.materials, key=lambda m: (m[0].lower(), m[0])):
        lines.append("| %s | %d | %s |" % (name, quantity, "Yes" if buildable else "No"))
    return "\n".join(lines)
