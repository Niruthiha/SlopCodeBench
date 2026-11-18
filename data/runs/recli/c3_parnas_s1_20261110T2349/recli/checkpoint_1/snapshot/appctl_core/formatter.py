"""Record rendering.

Secret: how a list of records is rendered in each supported output format.
"""

import csv
import io
import json

_FORMATS = ("table", "json", "csv", "yaml", "ids", "count")


def supported_formats():
    return list(_FORMATS)


def _table(records, fields):
    rows = [[str(r.get(f, "")) for f in fields] for r in records]
    widths = [max([len(f)] + [len(row[i]) for row in rows])
              for i, f in enumerate(fields)]
    lines = ["  ".join(c.ljust(w) for c, w in zip(fields, widths)).rstrip()]
    lines += ["  ".join(c.ljust(w) for c, w in zip(row, widths)).rstrip()
              for row in rows]
    return "\n".join(lines)


def _csv(records, fields):
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(fields)
    for record in records:
        writer.writerow([record.get(f, "") for f in fields])
    return buffer.getvalue().rstrip("\n")


def _yaml(records, fields):
    lines = ["---"]
    for record in records:
        for index, field in enumerate(fields):
            lead = "- " if index == 0 else "  "
            lines.append(f"{lead}{field}: {json.dumps(record.get(field, ''))}")
    return "\n".join(lines)


def render(records, fields, fmt):
    """Render ``records`` (dicts) restricted to ``fields`` in format ``fmt``.

    Raises ``ValueError`` for an unsupported format.
    """
    fields = list(fields)
    if fmt == "table":
        return _table(records, fields)
    if fmt == "json":
        return json.dumps([{f: r.get(f) for f in fields} for r in records])
    if fmt == "csv":
        return _csv(records, fields)
    if fmt == "yaml":
        return _yaml(records, fields)
    if fmt == "ids":
        return " ".join(str(r.get(fields[0], "")) for r in records)
    if fmt == "count":
        return str(len(records))
    raise ValueError(fmt)


_MAPPING_FORMATS = ("list", "json", "yaml")


def supported_mapping_formats():
    return list(_MAPPING_FORMATS)


def render_mapping(mapping, fmt):
    """Render a single key/value mapping. Raises ``ValueError`` for an
    unsupported format."""
    if fmt == "list":
        width = max((len(k) for k in mapping), default=0)
        return "\n".join(f"{k.ljust(width)}  {v}" for k, v in mapping.items())
    if fmt == "json":
        return json.dumps(mapping)
    if fmt == "yaml":
        return "\n".join(["---"] + [f"{k}: {json.dumps(v)}" for k, v in mapping.items()])
    raise ValueError(fmt)
