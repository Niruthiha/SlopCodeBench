#!/usr/bin/env python3
"""EVE Online industry recipe planner using the Static Data Export (SDE)."""

import argparse
import bz2
import csv
import math
import os
import sys
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from fractions import Fraction

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

    def recipe_for(self, tid):
        """Preferred (blueprintID, activityID) building a product."""
        prods = self.producers_of(tid)
        prods.sort(key=lambda x: (BUILD_ACTIVITIES.index(x[1]), x[0]))
        return prods[0]

    def output_quantity(self, bp, aid, tid):
        for pid, qty in self.products.get((bp, aid), []):
            if pid == tid:
                return max(1, qty)
        return 1

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


def invention_sources(sde, product, bp):
    """Return (tech, t3, relics, primary) describing how a blueprint is invented."""
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
            raise LookupError(f"No invention source found for '{type_name(sde, product)}'")
        primary = sources[0]
    return tech, t3, relics, primary


def render_invention(sde, product, bp, skill):
    t = sde.types[product]
    category, group = sde.category_group(product)
    tech, t3, relics, primary = invention_sources(sde, product, bp)

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


MAX_ME = 10


def material_amount(qty, me, runs=1):
    """Amount needed = ceil(max(1, qty * (1 - ME/100) * runs)), computed exactly."""
    return math.ceil(max(1, Fraction(qty) * (100 - me) / 100 * runs))


def efficiency_arg(name, upper, even=False):
    def parse(value):
        try:
            num = int(value)
        except ValueError:
            raise argparse.ArgumentTypeError(f"{name} must be an integer, got '{value}'")
        if not 0 <= num <= upper:
            raise argparse.ArgumentTypeError(f"{name} must be in range [0,{upper}], got {num}")
        if even and num % 2:
            raise argparse.ArgumentTypeError(f"{name} must be an even integer, got {num}")
        return num
    return parse


def render(sde, product, bp, aid, me=0, te=0, waste=False):
    t = sde.types[product]
    category, group = sde.category_group(product)
    qty = 1
    for pid, q in sde.products.get((bp, aid), []):
        if pid == product:
            qty = q
            break
    if aid != MANUFACTURING:
        me = te = 0
    seconds = sde.activity_time.get((bp, aid), 0) or 0
    minutes = math.ceil(Fraction(seconds) * (100 - te) / 100 / 60)

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
    ]
    if waste:
        lines += ["| Item | Quantity | Waste | Buildable |", "|:-:|:---:|:---:|---:|"]
    else:
        lines += ["| Item | Quantity | Buildable |", "|:-:|:---:|---:|"]
    rows = []
    for mid, mqty in sde.materials.get((bp, aid), {}).items():
        mt = sde.types.get(mid)
        mname = mt["name"] if mt else str(mid)
        rows.append((mname.lower(), mname, mid, mqty))
    rows.sort(key=lambda r: (r[0], r[1], r[2]))
    for _, mname, mid, mqty in rows:
        buildable = "Yes" if sde.is_buildable(mid) else "No"
        needed = material_amount(mqty, me)
        if waste:
            extra = needed - material_amount(mqty, MAX_ME if aid == MANUFACTURING else 0)
            lines.append(f"| {mname} | {needed} | {extra} | {buildable} |")
        else:
            lines.append(f"| {mname} | {needed} | {buildable} |")
    return "\n".join(lines)


SECONDS_PER_DAY = 86400
MAX_TE = 20
MAX_SPLIT_DAYS = 30
CAPITAL_GROUPS = {"Capital Industrial Ship", "Carrier", "Dreadnought", "Force Auxiliary", "Freighter",
                  "Supercarrier", "Titan"}


class PlanError(Exception):
    pass


def load_plan_config(path):
    if not os.path.exists(path):
        raise PlanError(f"Config file not found: {path}")
    with open(path, "r", encoding="utf-8") as fh:
        text = fh.read()
    if yaml is not None:
        try:
            data = yaml.safe_load(text)
        except yaml.YAMLError as exc:
            raise PlanError(f"Invalid config file: {exc}")
    else:
        data = {}
        for line in text.splitlines():
            line = line.split("#", 1)[0].strip()
            if ":" in line:
                key, _, val = line.partition(":")
                data[key.strip()] = val.strip()
    if data is None:
        data = {}
    if not isinstance(data, dict):
        raise PlanError("Config file must be a mapping")

    def get_int(key, default, low, high, source=data):
        value = source.get(key, default)
        if value is None:
            value = default
        if isinstance(value, bool):
            raise PlanError(f"{key} must be an integer")
        try:
            num = int(value) if isinstance(value, int) else int(str(value).strip())
        except ValueError:
            raise PlanError(f"{key} must be an integer, got '{value}'")
        if not low <= num <= high:
            raise PlanError(f"{key} must be in range [{low},{high}], got {num}")
        return num

    def get_float(key, default):
        value = data.get(key, default)
        if value is None:
            value = default
        if isinstance(value, bool):
            raise PlanError(f"{key} must be a number")
        try:
            num = float(value) if isinstance(value, (int, float)) else float(str(value).strip())
        except ValueError:
            raise PlanError(f"{key} must be a number, got '{value}'")
        if not (num > 0 and math.isfinite(num)):
            raise PlanError(f"{key} must be a positive number, got '{value}'")
        return num

    defaults = data.get("component_bpo_defaults")
    if defaults is None:
        defaults = {}
    if not isinstance(defaults, dict):
        raise PlanError("component_bpo_defaults must be a mapping")
    return {
        "te_bonus": get_int("te_bonus", 0, 0, 30),
        "invention_skill": get_int("invention_skill", 5, 1, 5),
        "split_days": min(MAX_SPLIT_DAYS, get_float("split_days", 3.0)),
        "component_me": get_int("me", 10, 0, MAX_ME, defaults),
        "component_te": get_int("te", 20, 0, MAX_TE, defaults),
    }


def _decryptor_suffix(tokens):
    """Yield (decryptor, remaining tokens) for decryptor names ending the tokens."""
    for dec in DECRYPTORS:
        words = dec[0].split()
        n = len(words)
        if len(tokens) > n and [t.lower() for t in tokens[-n:]] == [w.lower() for w in words]:
            yield dec, tokens[:-n]


def _int_token(token):
    return token.isdigit()


def parse_build_string(sde, text):
    """Parse a build string into a request dict."""
    tokens = text.split()
    if not tokens:
        raise PlanError("Empty build string")
    jobs = 1
    if len(tokens) > 1 and len(tokens[-1]) > 1 and tokens[-1][0] in "xX" and tokens[-1][1:].isdigit():
        jobs = int(tokens[-1][1:])
        tokens = tokens[:-1]

    relic_names = {}
    for (src, aid) in sde.inv_products:
        name = type_name(sde, src)
        if aid in INVENTION_ACTIVITIES and sde.is_published(src) and relic_quality(name) is not None:
            relic_names.setdefault(name.lower(), src)

    candidates = []
    # Reverse engineering: {Item} {Runs} {Decryptor|None} {Relic}
    for n in range(1, len(tokens)):
        relic = relic_names.get(" ".join(tokens[-n:]).lower())
        if relic is None:
            continue
        for dec, rest in _decryptor_suffix(tokens[:-n]):
            if len(rest) > 1 and _int_token(rest[-1]):
                candidates.append(dict(kind="invention", name=" ".join(rest[:-1]), runs=int(rest[-1]),
                                       decryptor=dec, relic=relic))
            candidates.append(dict(kind="invention", name=" ".join(rest), runs=None,
                                   decryptor=dec, relic=relic))
    # Invention: {Item} {Runs} {Decryptor|None}
    for dec, rest in _decryptor_suffix(tokens):
        if len(rest) > 1 and _int_token(rest[-1]):
            candidates.append(dict(kind="invention", name=" ".join(rest[:-1]), runs=int(rest[-1]),
                                   decryptor=dec, relic=None))
        candidates.append(dict(kind="invention", name=" ".join(rest), runs=None,
                               decryptor=dec, relic=None))
    # Normal: {Item} {Runs} {ME} {TE}
    if len(tokens) > 3 and all(_int_token(t) for t in tokens[-3:]):
        candidates.append(dict(kind="normal", name=" ".join(tokens[:-3]), runs=int(tokens[-3]),
                               me=int(tokens[-2]), te=int(tokens[-1])))
    # Item: {Item} {Runs}
    if len(tokens) > 1 and _int_token(tokens[-1]):
        candidates.append(dict(kind="normal", name=" ".join(tokens[:-1]), runs=int(tokens[-1]), me=0, te=0))
    # Item: {Item}
    candidates.append(dict(kind="normal", name=" ".join(tokens), runs=1, me=0, te=0))

    first_error = None
    for cand in candidates:
        cand["jobs"] = jobs
        try:
            if cand["kind"] == "invention":
                cand["product"], cand["bp"] = resolve_invention(sde, cand["name"])
                cand["aid"] = MANUFACTURING
            else:
                cand["product"], cand["bp"], cand["aid"] = sde.resolve(cand["name"])
        except LookupError as exc:
            if first_error is None:
                first_error = exc
            continue
        return cand
    raise PlanError(str(first_error) if first_error else f"Could not parse build string '{text}'")


def job_material_amount(qty, me, runs):
    """Materials for one job: max(runs, ceil(qty * runs * (1 - ME/100)))."""
    return max(runs, math.ceil(Fraction(qty) * runs * (100 - me) / 100))


def format_decimal(value):
    """Round to two decimals and print like a float (at least one decimal)."""
    text = format(Decimal(value).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP), "f")
    whole, _, frac = text.partition(".")
    frac = frac.rstrip("0") or "0"
    if whole in ("-0", ""):
        whole = "0"
    return f"{whole}.{frac}"


def invention_plan(sde, req, skill):
    """Return (bp ME, bp TE, max runs, {typeID: quantity}) for the invention step."""
    product, bp = req["product"], req["bp"]
    dname, mult, druns, dme, dte = req["decryptor"]
    if req["relic"] is not None:
        sources = [(src, aid) for src, aid in sde.inv_sources.get(bp, []) if src == req["relic"]]
        if not sources:
            raise PlanError(f"'{type_name(sde, req['relic'])}' cannot be reverse engineered into "
                            f"'{type_name(sde, bp)}'")
        primary = sources[0]
    else:
        _, _, _, primary = invention_sources(sde, product, bp)

    quality = relic_quality(type_name(sde, primary[0]))
    if quality is not None:
        _, base, base_runs = quality
    else:
        base = sde.inv_probability.get((primary[0], primary[1], bp), 0.0)
        base_runs = sde.inv_products.get(primary, {}).get(bp, 1)

    skills = sde.inv_skills.get(primary, {})
    factor = Fraction(1)
    for sid in skills:
        factor += Fraction(skill, 40 if is_encryption_skill(type_name(sde, sid)) else 30)
    chance = min(Fraction(1), Fraction(str(base)) * factor * (100 + mult) / 100)
    if chance <= 0:
        raise PlanError(f"Invention of '{type_name(sde, bp)}' has no chance of success")

    max_runs = base_runs + druns
    if max_runs <= 0:
        raise PlanError(f"Invented '{type_name(sde, bp)}' would have no runs")
    runs, jobs = req["runs"], req["jobs"]
    if runs <= max_runs:
        # One invented blueprint can be used for several jobs.
        copies = math.ceil(Fraction(jobs, max_runs // runs))
    else:
        copies = jobs * math.ceil(Fraction(runs, max_runs))
    attempts = math.ceil(copies / chance)

    mats = {}
    for mid, qty in sde.inv_materials.get(primary, []):
        mats[mid] = mats.get(mid, 0) + qty * attempts
    if quality is not None:
        mats[primary[0]] = mats.get(primary[0], 0) + attempts
    if dname != "None":
        ids = sorted(sde.by_name.get(dname, []))
        if ids:
            mats[ids[0]] = mats.get(ids[0], 0) + attempts
    return BASE_ME + dme, BASE_TE + dte, max_runs, mats


def split_runs(runs, days_per_run, split_days):
    """Split a job into [(runs, count)] so every part finishes within split_days."""
    if runs <= 1 or days_per_run <= 0:
        return [(runs, 1)]
    limit = Fraction(str(split_days))
    # Most runs a single job may take while staying under the limit.
    max_runs = max(1, math.ceil(limit / days_per_run) - 1)
    if runs <= max_runs:
        return [(runs, 1)]
    parts = -(-runs // max_runs)
    base, extra = divmod(runs, parts)
    if base + 1 == max_runs and extra > parts / 2 and runs // (parts + 1) + 1 < max_runs:
        parts += 1
        base, extra = divmod(runs, parts)
    return [(r, c) for r, c in ((base + 1, extra), (base, parts - extra)) if c > 0]


def is_t1_capital(sde, tid):
    category, group = sde.category_group(tid)
    if category != "Ship" or sde.tech_level(tid) != "Tech I":
        return False
    return group in CAPITAL_GROUPS or sde.market_path(tid).startswith("Ships > Capital Ships")


def component_efficiency(sde, tid, aid, config):
    """ME/TE used for the blueprint building a component."""
    if aid != MANUFACTURING or is_t1_capital(sde, tid):
        return 0, 0
    return config["component_me"], config["component_te"]


def component_order(sde, roots, exclude):
    """Buildable components reachable from roots, every consumer before its inputs."""
    order = []
    state = {tid: 2 for tid in exclude}
    for root in roots:
        if root in state or not sde.is_buildable(root):
            continue
        state[root] = 1
        stack = [(root, iter(sorted(sde.materials.get(sde.recipe_for(root), {}))))]
        while stack:
            tid, children = stack[-1]
            for child in children:
                if child not in state and sde.is_buildable(child):
                    state[child] = 1
                    stack.append((child, iter(sorted(sde.materials.get(sde.recipe_for(child), {})))))
                    break
            else:
                stack.pop()
                state[tid] = 2
                order.append(tid)
    order.reverse()
    return order


def build_plan(sde, req, config, build_all=False):
    """Return (materials rows, jobs rows) for a parsed build request."""
    product, bp, aid = req["product"], req["bp"], req["aid"]
    jobs = req["jobs"]
    if jobs < 1:
        raise PlanError("Number of jobs must be at least 1")

    mats = {}
    if req["kind"] == "invention":
        if req["runs"] is None:
            req["runs"] = 1
        if req["runs"] < 1:
            raise PlanError("Runs per job must be at least 1")
        me, te, _, inv_mats = invention_plan(sde, req, config["invention_skill"])
        for mid, qty in inv_mats.items():
            mats[mid] = mats.get(mid, 0) + qty
    else:
        me, te = req["me"], req["te"]
        if req["runs"] < 1:
            raise PlanError("Runs per job must be at least 1")
        if not 0 <= me <= MAX_ME:
            raise PlanError(f"Material efficiency must be in range [0,{MAX_ME}], got {me}")
        if not 0 <= te <= MAX_TE:
            raise PlanError(f"Time efficiency must be in range [0,{MAX_TE}], got {te}")
    if aid != MANUFACTURING:
        me = te = 0

    te_bonus = config["te_bonus"]
    job_counts = {}

    def add_jobs(job_bp, job_aid, runs, job_me, job_te, count):
        """Split a job of `runs` runs, queue its materials and record the job rows."""
        seconds = sde.activity_time.get((job_bp, job_aid), 0) or 0
        per_run = Fraction(seconds) * (100 - job_te) / 100 * (100 - te_bonus) / 100 / SECONDS_PER_DAY
        for part_runs, part_count in split_runs(runs, per_run, config["split_days"]):
            for mid, qty in sde.materials.get((job_bp, job_aid), {}).items():
                if qty <= 0:
                    continue
                amount = job_material_amount(qty, job_me, part_runs) * part_count * count
                mats[mid] = mats.get(mid, 0) + amount
            days = per_run * part_runs
            days = Decimal(days.numerator) / Decimal(days.denominator)
            key = (type_name(sde, job_bp), part_runs, format_decimal(days))
            job_counts[key] = job_counts.get(key, 0) + part_count * count

    add_jobs(bp, aid, req["runs"], me, te, jobs)

    surplus = {}
    if build_all:
        for mid in component_order(sde, list(mats), {product}):
            need = mats.pop(mid, 0)
            if need <= 0:
                continue
            cbp, caid = sde.recipe_for(mid)
            out_qty = sde.output_quantity(cbp, caid, mid)
            runs = -(-need // out_qty)
            cme, cte = component_efficiency(sde, mid, caid, config)
            add_jobs(cbp, caid, runs, cme, cte, 1)
            surplus[mid] = surplus.get(mid, 0) + runs * out_qty - need

    by_name = {}
    for mid, qty in mats.items():
        name = type_name(sde, mid)
        vol = (sde.volume(mid) if mid in sde.types else Decimal(0)) * qty
        prev = by_name.get(name, (0, Decimal(0), 0))
        by_name[name] = (prev[0] + qty, prev[1] + vol, prev[2])
    for mid, extra in surplus.items():
        if extra <= 0:
            continue
        name = type_name(sde, mid)
        prev = by_name.get(name, (0, Decimal(0), 0))
        by_name[name] = (prev[0], prev[1], prev[2] + extra)
    material_rows = [[name, qty, format_decimal(vol), 0, end]
                     for name, (qty, vol, end) in sorted(by_name.items())]

    job_rows = [[name, runs, days, count] for (name, runs, days), count in job_counts.items()]
    job_rows.sort(key=lambda r: (r[0], r[1], r[3], Decimal(r[2])))
    return material_rows, job_rows


def write_plan(output, material_rows, job_rows):
    os.makedirs(output, exist_ok=True)
    with open(os.path.join(output, "materials.csv"), "w", encoding="utf-8", newline="") as fh:
        writer = csv.writer(fh, lineterminator="\n")
        writer.writerow(["name", "to_buy", "buy_volume", "start_amount", "end_amount"])
        writer.writerows(material_rows)
    with open(os.path.join(output, "jobs.csv"), "w", encoding="utf-8", newline="") as fh:
        writer = csv.writer(fh, lineterminator="\n")
        writer.writerow(["name", "runs", "days", "count"])
        writer.writerows(job_rows)


def main(argv=None):
    parser = argparse.ArgumentParser(description="EVE Online industry planner")
    sub = parser.add_subparsers(dest="command", required=True)
    rp = sub.add_parser("recipe", help="Show the recipe for a product or blueprint")
    rp.add_argument("name", nargs="+", help="Exact product or blueprint typeName")
    rp.add_argument("--sde", required=True, help="Path to SDE directory")
    rp.add_argument("--material-efficiency", "-me", dest="me", default=0, metavar="ME",
                    type=efficiency_arg("Material efficiency", 10),
                    help="Material efficiency, integer in [0,10] (default 0)")
    rp.add_argument("--time-efficiency", "-te", dest="te", default=0, metavar="TE",
                    type=efficiency_arg("Time efficiency", 20, even=True),
                    help="Time efficiency, even integer in [0,20] (default 0)")
    rp.add_argument("--display-waste", "-waste", dest="waste", action="store_true",
                    help="Display material waste due to ME not being max")
    ip = sub.add_parser("invention", help="Plan invention / reverse engineering for a product or blueprint")
    ip.add_argument("name", nargs="+", help="Exact product or blueprint typeName")
    ip.add_argument("--sde", required=True, help="Path to SDE directory")
    ip.add_argument("--skill", type=int, default=5, choices=range(1, 6), metavar="{1-5}",
                    help="Level for all relevant skills (default 5)")
    pp = sub.add_parser("plan", help="Create a build plan for an item")
    pp.add_argument("build", nargs="+", help="Build string, e.g. 'Barrage L 10 None x10'")
    pp.add_argument("--config", required=True, help="YAML build config file")
    pp.add_argument("--sde", required=True, help="Path to SDE directory")
    pp.add_argument("--output", required=True, help="Output directory")
    pp.add_argument("--build-all", dest="build_all", action="store_true",
                    help="Build every buildable component in the tree instead of buying it")
    args = parser.parse_args(argv)

    if args.command == "plan":
        if not os.path.isdir(args.sde):
            print(f"Error: SDE directory not found: {args.sde}", file=sys.stderr)
            return 2
        try:
            config = load_plan_config(args.config)
            sde = SDE(args.sde)
            req = parse_build_string(sde, " ".join(args.build))
            material_rows, job_rows = build_plan(sde, req, config, args.build_all)
        except (PlanError, LookupError) as exc:
            print(f"Error: {exc}", file=sys.stderr)
            return 1
        write_plan(args.output, material_rows, job_rows)
        return 0

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
        sys.stdout.write(render(sde, product, bp, aid, args.me, args.te, args.waste) + "\n")
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())
