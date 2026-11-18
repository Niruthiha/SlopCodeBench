"""Parsing of stockpile and stock target lists.

Secret: the textual format of a list -- one "{Item Name} {Quantity}" entry
per line with anything allowed after it, blank and comment lines, how the
item name is told apart from the quantity when names contain numbers, and
how repeated entries combine.
"""

import re

_QUANTITY = re.compile(r"^\d[\d,_]*$")


def _quantity(token):
    if not _QUANTITY.match(token):
        return None
    return int(token.replace(",", "").replace("_", ""))


def parse_line(line, canonical_name):
    """(item name, quantity) for one entry, or None for a blank/comment line.

    canonical_name maps a candidate name to the known item name, or None.
    The longest known item name followed by a quantity wins.
    """
    tokens = line.split()
    if not tokens or tokens[0].startswith("#"):
        return None
    found = None
    for end in range(1, len(tokens)):
        quantity = _quantity(tokens[end])
        if quantity is None:
            continue
        name = canonical_name(" ".join(tokens[:end]))
        if name is not None:
            found = (name, quantity)
    if found is None:
        raise LookupError("Cannot parse stock entry %r" % line.strip())
    return found


def read(path, canonical_name):
    """{item name: quantity} from a list file; repeated items are summed."""
    amounts = {}
    with open(path, encoding="utf-8-sig") as handle:
        for line in handle:
            entry = parse_line(line, canonical_name)
            if entry is not None:
                name, quantity = entry
                amounts[name] = amounts.get(name, 0) + quantity
    return amounts
