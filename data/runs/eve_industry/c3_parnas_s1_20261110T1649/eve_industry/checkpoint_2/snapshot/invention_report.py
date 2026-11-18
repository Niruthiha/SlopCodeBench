"""Canonical invention report text.

Secret: the exact layout of the invention report -- labels, ordering,
number formatting, time and probability rounding, and how the
probabilities table is drawn.
"""

import math
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal


@dataclass(frozen=True)
class InventionReportInput:
    item_name: str
    type_id: int
    category: str
    group: str
    market_path: tuple  # market group names, root to leaf
    tech_level: str
    base_blueprint: tuple  # (name, type_id), or None to omit the line
    datacores: tuple  # of names, display order
    quantity_per_run: int
    skills: tuple  # of names, display order
    seconds: int
    with_source: bool  # show the "Invented From" column
    rows: tuple  # of (invented_from, decryptor, percent, runs, me, te), display order


_SOURCE_COLUMN = ("Invented From", 30)
_COLUMNS = (
    ("Decryptor", 33),
    ("Probability", 13),
    ("Runs", 6),
    ("ME", 4),
    ("TE", 4),
)


def _percent_text(percent):
    return str(Decimal(repr(percent)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def _table_line(cells, widths):
    return "|" + "".join(" " + str(c).ljust(w - 1) + "|" for c, w in zip(cells, widths))


def render(data):
    market = " > ".join(data.market_path) if data.market_path else "None"
    lines = [
        "ITEM: %s (%d)" % (data.item_name, data.type_id),
        "Group: %s > %s" % (data.category, data.group),
        "Market Group: %s" % market,
        "Tech Level: %s" % data.tech_level,
        "",
        "Invention:",
    ]
    if data.base_blueprint is not None:
        lines.append("Base: %s (%d)" % data.base_blueprint)
    lines += [
        "Datacores: %s" % ", ".join(data.datacores),
        "Required Per Run: %d" % data.quantity_per_run,
        "Skills: %s" % ", ".join(data.skills),
        "Time: %d" % math.ceil(data.seconds / 60),
        "Probabilities:",
    ]

    columns = ((_SOURCE_COLUMN,) if data.with_source else ()) + _COLUMNS
    titles = [title for title, _ in columns]
    widths = [width for _, width in columns]
    lines.append(_table_line(titles, widths))
    lines.append("|" + "".join("-" * w + "|" for w in widths))
    for source, decryptor, percent, runs, me, te in data.rows:
        cells = [decryptor, _percent_text(percent), runs, me, te]
        if data.with_source:
            cells.insert(0, source)
        lines.append(_table_line(cells, widths))
    return "\n".join(lines)
