#!/usr/bin/env python3
"""EVE Online industry recipe planner using the Static Data Export (SDE)."""

import argparse
import bz2
import csv
import math
import os
import sys
from decimal import Decimal, InvalidOperation

try:
    import yaml
except ImportError:  # pragma: no cover - fallback for minimal environments
    yaml = None

MANUFACTURING = 1
REACTIONS = 11
BUILD_ACTIVITIES = (MANUFACTURING, REACTIONS)
ACTIVITY_NAMES = {MANUFACTURING: "Manufacturing", REACTIONS: "Reactions"}

csv.field_size_limit(sys.maxsize)


def read_csv(sde, name):
    path = os.path.join(sde, name)
    if not os.path.exists(path):
        alt = path[:-4] if path.endswith(".bz2") else path + ".bz2"
        if os.path.exists(alt):
            path = alt
        else:
            return []
    opener = bz2.open if path.endswith(".bz2") else open
    with opener(path, "rt", encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


def to_int(value, default=None):
    if value is None:
        return default
    value = value.strip()
    if value == "" or value == "None":
        return default
    try:
        return int(value)
    except ValueError:
        try:
            return int(Decimal(value))
        except (InvalidOperation, ValueError):
            return default


def to_decimal(value):
    if value is None:
        return None
    value = str(value).strip()
    if value in ("", "None"):
        return None
    try:
        return Decimal(value)
    except InvalidOperation:
        return None


def load_ship_volumes(sde):
    path = os.path.join(sde, "ship_volumes.yaml")
    if not os.path.exists(path):
        return {}
    with open(path, "r", encoding="utf-8") as fh:
        text = fh.read()
    data = None
    if yaml is not None:
        try:
            data = yaml.safe_load(text)
        except yaml.YAMLError:
            data = None
    if data is None:
        data = {}
        for line in text.splitlines():
            line = line.split("#", 1)[0].rstrip()
            if not line or ":" not in line:
                continue
            key, _, val = line.rpartition(":")
            data[key.strip().strip("'\"")] = val.strip().strip("'\"")
    result = {}
    if isinstance(data, dict):
        for key, val in data.items():
            dec = to_decimal(val)
            if dec is not None:
                result[str(key).strip()] = dec
    return result


def format_volume(vol):
    """Format with at least two decimals, dropping further trailing zeros."""
    if vol is None:
        vol = Decimal(0)
    text = format(vol, "f")
    if "." in text:
        whole, frac = text.split(".", 1)
    else:
        whole, frac = text, ""
    frac = frac.rstrip("0")
    if len(frac) < 2:
        frac = frac.ljust(2, "0")
    if whole in ("-0", ""):
        whole = "0"
    return f"{whole}.{frac}"


class SDE:
    def __init__(self, path):
        self.path = path
        self.types = {}
        for row in read_csv(path, "invTypes.csv.bz2"):
            tid = to_int(row.get("typeID"))
            if tid is None:
                continue
            self.types[tid] = {
                "id": tid,
                "name": row.get("typeName") or "",
                "group": to_int(row.get("groupID")),
                "volume": to_decimal(row.get("volume")),
                "published": to_int(row.get("published"), 0) == 1,
                "market": to_int(row.get("marketGroupID")),
            }

        self.groups = {}
        for row in read_csv(path, "invGroups.csv.bz2"):
            gid = to_int(row.get("groupID"))
            if gid is not None:
                self.groups[gid] = (to_int(row.get("categoryID")), row.get("groupName") or "")

        self.categories = {}
        for row in read_csv(path, "invCategories.csv.bz2"):
            cid = to_int(row.get("categoryID"))
            if cid is not None:
                self.categories[cid] = row.get("categoryName") or ""

        self.market_groups = {}
        for row in read_csv(path, "invMarketGroups.csv.bz2"):
            mid = to_int(row.get("marketGroupID"))
            if mid is not None:
                self.market_groups[mid] = (to_int(row.get("parentGroupID")), row.get("marketGroupName") or "")

        self.meta_groups = {}
        for row in read_csv(path, "invMetaGroups.csv.bz2"):
            mid = to_int(row.get("metaGroupID"))
            if mid is not None:
                self.meta_groups[mid] = row.get("metaGroupName") or ""

        self.meta_types = {}
        for row in read_csv(path, "invMetaTypes.csv.bz2"):
            tid = to_int(row.get("typeID"))
            if tid is not None:
                self.meta_types[tid] = to_int(row.get("metaGroupID"))

        # (blueprintID, activityID) -> time in seconds
        self.activity_time = {}
        for row in read_csv(path, "industryActivity.csv.bz2"):
            tid = to_int(row.get("typeID"))
            aid = to_int(row.get("activityID"))
            if tid is None or aid is None:
                continue
            self.activity_time[(tid, aid)] = to_int(row.get("time"), 0)

        # (blueprintID, activityID) -> list of (productID, quantity)
        self.products = {}
        # productID -> list of (blueprintID, activityID)
        self.producers = {}
        for row in read_csv(path, "industryActivityProducts.csv.bz2"):
            tid = to_int(row.get("typeID"))
            aid = to_int(row.get("activityID"))
            pid = to_int(row.get("productTypeID"))
            if tid is None or aid not in BUILD_ACTIVITIES or pid is None:
                continue
            qty = to_int(row.get("quantity"), 1)
            self.products.setdefault((tid, aid), []).append((pid, qty))
            self.producers.setdefault(pid, []).append((tid, aid))

        # (blueprintID, activityID) -> {materialID: quantity}
        self.materials = {}
        for row in read_csv(path, "industryActivityMaterials.csv.bz2"):
            tid = to_int(row.get("typeID"))
            aid = to_int(row.get("activityID"))
            mid = to_int(row.get("materialTypeID"))
            if tid is None or aid not in BUILD_ACTIVITIES or mid is None:
                continue
            mats = self.materials.setdefault((tid, aid), {})
            mats[mid] = mats.get(mid, 0) + to_int(row.get("quantity"), 0)

        self.ship_volumes = load_ship_volumes(path)

        self.by_name = {}
        for t in self.types.values():
            if t["published"]:
                self.by_name.setdefault(t["name"], []).append(t["id"])

    # ----- helpers -------------------------------------------------------
    def is_published(self, tid):
        t = self.types.get(tid)
        return bool(t and t["published"])

    def valid_recipe(self, bp, aid):
        """A recipe is valid when its blueprint and products are published."""
        if not self.is_published(bp):
            return False
        return any(self.is_published(pid) for pid, _ in self.products.get((bp, aid), []))

    def blueprint_activities(self, bp):
        return [aid for aid in BUILD_ACTIVITIES if (bp, aid) in self.products]

    def producers_of(self, pid):
        return [(bp, aid) for bp, aid in self.producers.get(pid, []) if self.valid_recipe(bp, aid)]

    def is_buildable(self, tid):
        return bool(self.producers_of(tid))

    def category_group(self, tid):
        t = self.types[tid]
        cat_id, group_name = self.groups.get(t["group"], (None, ""))
        return self.categories.get(cat_id, ""), group_name

    def market_path(self, tid):
        mid = self.types[tid]["market"]
        names = []
        seen = set()
        while mid is not None and mid in self.market_groups and mid not in seen:
            seen.add(mid)
            parent, name = self.market_groups[mid]
            names.append(name)
            mid = parent
        if not names:
            return "None"
        return " > ".join(reversed(names))

    def tech_level(self, tid):
        mg = self.meta_types.get(tid)
        name = self.meta_groups.get(mg, "") if mg is not None else ""
        if mg == 14 or "Tech III" in name:
            return "Tech III"
        if mg == 2 or "Tech II" in name:
            return "Tech II"
        return "Tech I"

    def volume(self, tid):
        t = self.types[tid]
        category, group = self.category_group(tid)
        if category == "Ship":
            if group in self.ship_volumes:
                return self.ship_volumes[group]
            lowered = {k.lower(): v for k, v in self.ship_volumes.items()}
            if group.lower() in lowered:
                return lowered[group.lower()]
        return t["volume"] if t["volume"] is not None else Decimal(0)

    # ----- resolution ----------------------------------------------------
    def resolve(self, name):
        """Return (productID, blueprintID, activityID) for a name."""
        candidates = sorted(self.by_name.get(name, []))
        if not candidates:
            raise LookupError(f"No published item named '{name}' found in SDE")

        # Blueprint names: the type itself carries a build activity.
        for tid in candidates:
            for aid in self.blueprint_activities(tid):
                if not self.valid_recipe(tid, aid):
                    continue
                prods = [(p, q) for p, q in self.products[(tid, aid)] if self.is_published(p)]
                prods.sort()
                return prods[0][0], tid, aid

        # Product names: find a blueprint/formula producing it.
        for tid in candidates:
            prods = self.producers_of(tid)
            if prods:
                prods.sort(key=lambda x: (BUILD_ACTIVITIES.index(x[1]), x[0]))
                bp, aid = prods[0]
                return tid, bp, aid

        raise LookupError(f"'{name}' cannot be built via Manufacturing or Reactions")


def render(sde, product, bp, aid):
    t = sde.types[product]
    category, group = sde.category_group(product)
    qty = 1
    for pid, q in sde.products.get((bp, aid), []):
        if pid == product:
            qty = q
            break
    seconds = sde.activity_time.get((bp, aid), 0) or 0
    minutes = math.ceil(seconds / 60)

    lines = [
        f"ITEM: {t['name']} ({product})",
        f"Group: {category} > {group}",
        f"Market Group: {sde.market_path(product)}",
        f"Tech Level: {sde.tech_level(product)}",
        f"Volume: {format_volume(sde.volume(product))}",
        "",
        "Recipe:",
        f"Activity: {ACTIVITY_NAMES[aid]}",
        f"Output Quantity: {qty}",
        f"Run Time: {minutes}",
        "| Item | Quantity | Buildable |",
        "|:-:|:---:|---:|",
    ]
    rows = []
    for mid, mqty in sde.materials.get((bp, aid), {}).items():
        mt = sde.types.get(mid)
        mname = mt["name"] if mt else str(mid)
        rows.append((mname.lower(), mname, mid, mqty))
    rows.sort(key=lambda r: (r[0], r[1], r[2]))
    for _, mname, mid, mqty in rows:
        buildable = "Yes" if sde.is_buildable(mid) else "No"
        lines.append(f"| {mname} | {mqty} | {buildable} |")
    return "\n".join(lines)


def main(argv=None):
    parser = argparse.ArgumentParser(description="EVE Online industry planner")
    sub = parser.add_subparsers(dest="command", required=True)
    rp = sub.add_parser("recipe", help="Show the recipe for a product or blueprint")
    rp.add_argument("name", nargs="+", help="Exact product or blueprint typeName")
    rp.add_argument("--sde", required=True, help="Path to SDE directory")
    args = parser.parse_args(argv)

    if args.command == "recipe":
        name = " ".join(args.name)
        if not os.path.isdir(args.sde):
            print(f"Error: SDE directory not found: {args.sde}", file=sys.stderr)
            return 2
        sde = SDE(args.sde)
        try:
            product, bp, aid = sde.resolve(name)
        except LookupError as exc:
            print(f"Error: {exc}", file=sys.stderr)
            return 1
        sys.stdout.write(render(sde, product, bp, aid) + "\n")
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())
