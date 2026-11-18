"""Canonical build plan CSV files.

Secret: file names, headers, column order, row sorting, and number
formatting of the plan outputs.
"""

import csv
import os
from decimal import ROUND_HALF_UP, Decimal

_MATERIALS_FILE = "materials.csv"
_JOBS_FILE = "jobs.csv"
_MATERIALS_HEADER = ("name", "to_buy", "buy_volume", "start_amount", "end_amount")
_JOBS_HEADER = ("name", "runs", "days", "count")


def _days_text(days):
    value = (Decimal(days.numerator) / Decimal(days.denominator)).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP
    )
    return repr(float(value))


def _write(path, header, rows):
    with open(path, "w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(header)
        writer.writerows(rows)


def write(plan, output_dir):
    os.makedirs(output_dir, exist_ok=True)
    materials = sorted(plan.purchases, key=lambda p: p.name)
    _write(
        os.path.join(output_dir, _MATERIALS_FILE),
        _MATERIALS_HEADER,
        [(p.name, p.quantity, repr(float(p.volume)), 0, 0) for p in materials],
    )
    merged = {}
    for job in plan.jobs:
        key = (job.name, job.runs, job.days)
        merged[key] = merged.get(key, 0) + job.count
    jobs = sorted(
        ((name, runs, count, days) for (name, runs, days), count in merged.items()),
        key=lambda j: (j[0], j[1], j[2], j[3]),
    )
    _write(
        os.path.join(output_dir, _JOBS_FILE),
        _JOBS_HEADER,
        [(name, runs, _days_text(days), count) for name, runs, count, days in jobs],
    )
