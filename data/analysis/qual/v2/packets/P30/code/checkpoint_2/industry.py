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
REVERSE_ENGINEERING = 7
INVENTION = 8
REACTIONS = 11
INVENTION_ACTIVITIES = (INVENTION, REVERSE_ENGINEERING)
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

        # Invention / reverse engineering data, keyed by (sourceTypeID, activityID).
        self.inv_products = {}
        # inventedBlueprintID -> list of (sourceTypeID, activityID)
        self.inv_sources = {}
        for row in read_csv(path, "industryActivityProducts.csv.bz2"):
            tid = to_int(row.get("typeID"))
            aid = to_int(row.get("activityID"))
            pid = to_int(row.get("productTypeID"))
            if tid is None or aid not in INVENTION_ACTIVITIES or pid is None:
                continue
            key = (tid, aid)
            prods = self.inv_products.setdefault(key, {})
            if pid not in prods:
                self.inv_sources.setdefault(pid, []).append(key)
            prods[pid] = to_int(row.get("quantity"), 1)

        # (sourceTypeID, activityID, productID) -> probability
        self.inv_probability = {}
        for row in read_csv(path, "industryActivityProbabilities.csv.bz2"):
            tid = to_int(row.get("typeID"))
            aid = to_int(row.get("activityID"))
            pid = to_int(row.get("productTypeID"))
            prob = row.get("probability")
            if tid is None or aid not in INVENTION_ACTIVITIES or pid is None:
                continue
            try:
                self.inv_probability[(tid, aid, pid)] = float(prob)
            except (TypeError, ValueError):
                continue

        # (sourceTypeID, activityID) -> list of (materialID, quantity)
        self.inv_materials = {}
        for row in read_csv(path, "industryActivityMaterials.csv.bz2"):
            tid = to_int(row.get("typeID"))
            aid = to_int(row.get("activityID"))
            mid = to_int(row.get("materialTypeID"))
            if tid is None or aid not in INVENTION_ACTIVITIES or mid is None:
                continue
            self.inv_materials.setdefault((tid, aid), []).append((mid, to_int(row.get("quantity"), 0)))

        # (sourceTypeID, activityID) -> {skillID: level}
        self.inv_skills = {}
        for row in read_csv(path, "industryActivitySkills.csv.bz2"):
            tid = to_int(row.get("typeID"))
            aid = to_int(row.get("activityID"))
            sid = to_int(row.get("skillID"))
            if tid is None or aid not in INVENTION_ACTIVITIES or sid is None:
                continue
            skills = self.inv_skills.setdefault((tid, aid), {})
            skills[sid] = max(skills.get(sid, 0), to_int(row.get("level"), 0))

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


DECRYPTORS = [
    # name, probability multiplier (%), runs, ME, TE
    ("None", 0, 0, 0, 0),
    ("Accelerant Decryptor", 20, 1, 2, 10),
    ("Attainment Decryptor", 80, 4, -1, 4),
    ("Augmentation Decryptor", -40, 9, -2, 2),
    ("Optimized Attainment Decryptor", 90, 2, 1, -2),
    ("Optimized Augmentation Decryptor", -10, 7, 2, 0),
    ("Parity Decryptor", 50, 3, 1, -2),
    ("Process Decryptor", 10, 0, 3, 6),
    ("Symmetry Decryptor", 0, 2, 1, 8),
]

# Relic quality prefix -> (base chance, base runs), in output order.
RELIC_BASELINES = [
    ("Intact", 0.26, 20),
    ("Malfunctioning", 0.21, 10),
    ("Wrecked", 0.14, 3),
]

BASE_ME = 2
BASE_TE = 4


def relic_quality(name):
    for idx, (prefix, chance, runs) in enumerate(RELIC_BASELINES):
        if name.startswith(prefix):
            return idx, chance, runs
    return None


def sorted_decryptors():
    rest = sorted((d for d in DECRYPTORS if d[0] != "None"), key=lambda d: (d[0].lower(), d[0]))
    return [DECRYPTORS[0]] + rest


def is_encryption_skill(name):
    return "encryption" in name.lower()


def success_chance(base, science_levels, encryption_levels, multiplier):
    factor = 1
    for lvl in science_levels:
        factor += lvl / 30
    for lvl in encryption_levels:
        factor += lvl / 40
    chance = base * factor * (1 + multiplier / 100)
    return min(1.0, max(0.0, chance))


def format_chance(chance):
    return "%.2f" % round(chance * 100, 2)


def resolve_invention(sde, name):
    """Return (productID, blueprintID) for an invention target name."""
    candidates = sorted(sde.by_name.get(name, []))
    if not candidates:
        raise LookupError(f"No published item named '{name}' found in SDE")

    def invented(bp):
        return any(sde.is_published(src) for src, _ in sde.inv_sources.get(bp, []))

    # Blueprint names.
    for tid in candidates:
        if not invented(tid):
            continue
        prods = sorted(p for p, _ in sde.products.get((tid, MANUFACTURING), []) if sde.is_published(p))
        if not prods:
            prods = sorted(p for aid in BUILD_ACTIVITIES for p, _ in sde.products.get((tid, aid), [])
                           if sde.is_published(p))
        if prods:
            return prods[0], tid

    # Product names.
    for tid in candidates:
        bps = sorted(bp for bp, aid in sde.producers.get(tid, [])
                     if sde.is_published(bp) and invented(bp))
        if bps:
            return tid, bps[0]

    raise LookupError(f"'{name}' cannot be obtained via Invention or Reverse Engineering")


def type_name(sde, tid):
    t = sde.types.get(tid)
    return t["name"] if t else str(tid)


def render_invention(sde, product, bp, skill):
    t = sde.types[product]
    category, group = sde.category_group(product)
    tech = sde.tech_level(product)

    sources = [(src, aid) for src, aid in sde.inv_sources.get(bp, []) if sde.is_published(src)]
    relics = []
    for src, aid in sources:
        q = relic_quality(type_name(sde, src))
        if q is not None:
            relics.append((q, src, aid))
    if tech != "Tech III" and tech != "Tech II":
        tech = "Tech III" if relics and len(relics) == len(sources) else "Tech II"
    # Relic-based layout; Tech III items invented from ordinary blueprints
    # (e.g. tactical destroyers) use the Tech II layout instead.
    t3 = bool(relics) and (tech == "Tech III" or len(relics) == len(sources))

    if t3:
        relics.sort(key=lambda r: (r[0][0], type_name(sde, r[1]).lower(), r[1]))
        primary = (relics[0][1], relics[0][2])
    else:
        relic_ids = {r[1] for r in relics}
        sources = [s for s in sources if s[0] not in relic_ids] or sources
        sources.sort(key=lambda s: (INVENTION_ACTIVITIES.index(s[1]), s[0]))
        if not sources:
            raise LookupError(f"No invention source found for '{t['name']}'")
        primary = sources[0]

    mats = sde.inv_materials.get(primary, [])
    datacores = [(mid, q) for mid, q in mats if type_name(sde, mid).startswith("Datacore")]
    if not datacores:
        datacores = list(mats)
    dc_names = sorted({type_name(sde, mid) for mid, _ in datacores}, key=lambda n: (n.lower(), n))
    per_run = datacores[0][1] if datacores else 0

    skills = sde.inv_skills.get(primary, {})
    skill_names = sorted({type_name(sde, sid) for sid in skills}, key=lambda n: (n.lower(), n))
    science = [skill for sid in skills if not is_encryption_skill(type_name(sde, sid))]
    encryption = [skill for sid in skills if is_encryption_skill(type_name(sde, sid))]

    seconds = sde.activity_time.get(primary, 0) or 0
    minutes = math.ceil(seconds / 60)

    lines = [
        f"ITEM: {t['name']} ({product})",
        f"Group: {category} > {group}",
        f"Market Group: {sde.market_path(product)}",
        f"Tech Level: {tech}",
        "",
        "Invention:",
    ]
    if not t3:
        lines.append(f"Base: {type_name(sde, primary[0])} ({primary[0]})")
    lines += [
        f"Datacores: {', '.join(dc_names)}",
        f"Required Per Run: {per_run}",
        f"Skills: {', '.join(skill_names)}",
        f"Time: {minutes}",
        "Probabilities:",
    ]

    def cells(values, widths):
        return "|" + "|".join(" " + str(v).ljust(w - 1) for v, w in zip(values, widths)) + "|"

    if t3:
        widths = [30, 33, 13, 6, 4, 4]
        lines.append(cells(["Invented From", "Decryptor", "Probability", "Runs", "ME", "TE"], widths))
        lines.append("|" + "|".join("-" * w for w in widths) + "|")
        for (_, base, base_runs), src, _ in relics:
            for dname, mult, druns, dme, dte in sorted_decryptors():
                chance = success_chance(base, science, encryption, mult)
                lines.append(cells([type_name(sde, src), dname, format_chance(chance),
                                    base_runs + druns, BASE_ME + dme, BASE_TE + dte], widths))
    else:
        base = sde.inv_probability.get((primary[0], primary[1], bp))
        if base is None:
            base = 0.0
        base_runs = sde.inv_products.get(primary, {}).get(bp, 1)
        widths = [33, 13, 6, 4, 4]
        lines.append(cells(["Decryptor", "Probability", "Runs", "ME", "TE"], widths))
        lines.append("|" + "|".join("-" * w for w in widths) + "|")
        for dname, mult, druns, dme, dte in sorted_decryptors():
            chance = success_chance(base, science, encryption, mult)
            lines.append(cells([dname, format_chance(chance),
                                base_runs + druns, BASE_ME + dme, BASE_TE + dte], widths))
    return "\n".join(lines)


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
    ip = sub.add_parser("invention", help="Plan invention / reverse engineering for a product or blueprint")
    ip.add_argument("name", nargs="+", help="Exact product or blueprint typeName")
    ip.add_argument("--sde", required=True, help="Path to SDE directory")
    ip.add_argument("--skill", type=int, default=5, choices=range(1, 6), metavar="{1-5}",
                    help="Level for all relevant skills (default 5)")
    args = parser.parse_args(argv)

    if args.command == "invention":
        name = " ".join(args.name)
        if not os.path.isdir(args.sde):
            print(f"Error: SDE directory not found: {args.sde}", file=sys.stderr)
            return 2
        sde = SDE(args.sde)
        try:
            product, bp = resolve_invention(sde, name)
            out = render_invention(sde, product, bp, args.skill)
        except LookupError as exc:
            print(f"Error: {exc}", file=sys.stderr)
            return 1
        sys.stdout.write(out + "\n")
        return 0

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
