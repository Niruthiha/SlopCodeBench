"""Invention (Tech II) and reverse engineering (Tech III) planning."""

import math
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

from . import constants as C
from .industry_data import ActivityKey, IndustryData
from .inventory import Inventory
from .models import InvType, ItemInfo
from .sde_loader import iter_csv, parse_float, parse_int

SCIENCE_GROUP_NAME = "Science"
ENCRYPTION_SUFFIX = "Encryption Methods"

BASE_ME = 2
BASE_TE = 4

# (name, probability multiplier in % from 100%, runs, ME, TE)
DECRYPTORS: Tuple[Tuple[str, int, int, int, int], ...] = (
    ("None", 0, 0, 0, 0),
    ("Accelerant Decryptor", 20, 1, 2, 10),
    ("Attainment Decryptor", 80, 4, -1, 4),
    ("Augmentation Decryptor", -40, 9, -2, 2),
    ("Optimized Attainment Decryptor", 90, 2, 1, -2),
    ("Optimized Augmentation Decryptor", -10, 7, 2, 0),
    ("Parity Decryptor", 50, 3, 1, -2),
    ("Process Decryptor", 10, 0, 3, 6),
    ("Symmetry Decryptor", 0, 2, 1, 8),
)

# Relic quality -> (base chance, base runs), in display order.
RELIC_QUALITIES: Tuple[Tuple[str, float, int], ...] = (
    ("Intact", 0.26, 20),
    ("Malfunctioning", 0.21, 10),
    ("Wrecked", 0.14, 3),
)


class InventionError(Exception):
    """Raised when no invention plan can be resolved for the requested name."""


@dataclass(frozen=True)
class ProbabilityRow:
    invented_from: Optional[str]
    decryptor: str
    probability: float
    runs: int
    me: int
    te: int


@dataclass
class InventionPlan:
    product: InvType
    tech_level: str
    base_blueprint: Optional[InvType]
    datacores: List[str]
    required_per_run: int
    skills: List[str]
    time_minutes: int
    rows: List[ProbabilityRow] = field(default_factory=list)


class InventionData:
    """Indexes the invention / reverse engineering rows of the industry tables."""

    def __init__(self, sde_dir: Path, published_type_ids: Set[int]):
        self.times: Dict[ActivityKey, int] = {}
        # blueprint/product made by invention -> list of (source, activity)
        self.sources: Dict[int, List[ActivityKey]] = defaultdict(list)
        # (source, activity, product) -> runs / probability
        self.quantities: Dict[Tuple[int, int, int], int] = {}
        self.probabilities: Dict[Tuple[int, int, int], float] = {}
        # (source, activity) -> {materialTypeID: quantity}
        self.materials: Dict[ActivityKey, Dict[int, int]] = defaultdict(dict)
        # (source, activity) -> {skillID: level}
        self.skills: Dict[ActivityKey, Dict[int, int]] = defaultdict(dict)
        self._load(sde_dir, published_type_ids)

    def _load(self, sde_dir: Path, published: Set[int]) -> None:
        wanted = set(C.INVENTION_ACTIVITIES)

        for row in iter_csv(sde_dir, C.INDUSTRY_ACTIVITY):
            key = (int(row["typeID"]), int(row["activityID"]))
            if key[1] in wanted:
                self.times[key] = parse_int(row["time"]) or 0

        for row in iter_csv(sde_dir, C.INDUSTRY_PRODUCTS):
            key = (int(row["typeID"]), int(row["activityID"]))
            if key[1] not in wanted or key[0] not in published:
                continue
            product_id = int(row["productTypeID"])
            self.sources[product_id].append(key)
            self.quantities[(key[0], key[1], product_id)] = parse_int(row["quantity"]) or 0

        for row in iter_csv(sde_dir, C.INDUSTRY_PROBABILITIES):
            activity_id = int(row["activityID"])
            if activity_id not in wanted:
                continue
            triple = (int(row["typeID"]), activity_id, int(row["productTypeID"]))
            self.probabilities[triple] = parse_float(row["probability"])

        for row in iter_csv(sde_dir, C.INDUSTRY_MATERIALS):
            key = (int(row["typeID"]), int(row["activityID"]))
            if key[1] not in wanted:
                continue
            material_id = int(row["materialTypeID"])
            bucket = self.materials[key]
            bucket[material_id] = bucket.get(material_id, 0) + (parse_int(row["quantity"]) or 0)

        for row in iter_csv(sde_dir, C.INDUSTRY_SKILLS):
            key = (int(row["typeID"]), int(row["activityID"]))
            if key[1] not in wanted:
                continue
            self.skills[key][int(row["skillID"])] = parse_int(row["level"]) or 0

    def sources_of(self, blueprint_id: int) -> List[ActivityKey]:
        return sorted(set(self.sources.get(blueprint_id, [])), key=lambda k: (k[0], k[1]))


def relic_quality(name: str) -> Optional[int]:
    """Index into RELIC_QUALITIES for a relic name, or None if it is not a relic."""
    words = name.split()
    for index, (quality, _, _) in enumerate(RELIC_QUALITIES):
        if quality in words:
            return index
    return None


def success_chance(base: float, science_levels: List[int], encryption_levels: List[int],
                   multiplier: int) -> float:
    skill_factor = 1.0
    for level in science_levels:
        skill_factor += level / 30
    for level in encryption_levels:
        skill_factor += level / 40
    chance = base * skill_factor * (1 + multiplier / 100)
    return min(1.0, max(0.0, chance))


class InventionPlanner:
    def __init__(self, inventory: Inventory, industry: IndustryData, invention: InventionData):
        self.inventory = inventory
        self.industry = industry
        self.invention = invention

    # --- resolution --------------------------------------------------------

    def _resolve_target(self, name: str) -> Tuple[InvType, int, List[ActivityKey]]:
        """Return (product, invented blueprint ID, invention sources)."""
        candidates = self.inventory.published_by_name(name)
        if not candidates:
            raise InventionError(f"No published item named '{name}' found in the SDE")

        # Interpreted as an invented blueprint.
        for item in candidates:
            sources = self.invention.sources_of(item.type_id)
            if not sources:
                continue
            key = (item.type_id, C.MANUFACTURING)
            products = self.industry.products.get(key)
            if products:
                return self._require_type(products[0][0]), item.type_id, sources

        # Interpreted as a product whose blueprint is invented.
        for item in candidates:
            for blueprint_id, activity_id in self.industry.sources_of(item.type_id):
                if activity_id != C.MANUFACTURING:
                    continue
                sources = self.invention.sources_of(blueprint_id)
                if sources:
                    return item, blueprint_id, sources

        raise InventionError(f"'{name}' cannot be obtained through invention or reverse engineering")

    def _require_type(self, type_id: int) -> InvType:
        item = self.inventory.types.get(type_id)
        if item is None:
            raise InventionError(f"Type {type_id} referenced by industry data is missing")
        return item

    # --- planning ----------------------------------------------------------

    def plan(self, name: str, skill_level: int) -> InventionPlan:
        product, blueprint_id, sources = self._resolve_target(name)

        tech_level = self.inventory.tech_level_of(product)
        if tech_level not in ("Tech II", "Tech III"):
            relic_based = any(
                relic_quality(self.inventory.type_name(s)) is not None
                or a == C.REVERSE_ENGINEERING
                for s, a in sources
            )
            tech_level = "Tech III" if relic_based else "Tech II"
        is_t3 = tech_level == "Tech III"

        if is_t3:
            used = sorted(sources, key=lambda k: self._relic_sort_key(k[0]))
        else:
            used = sources[:1]

        datacore_qty: Dict[int, int] = {}
        skill_levels: Dict[int, int] = {}
        for key in used:
            for material_id, qty in self.invention.materials.get(key, {}).items():
                datacore_qty[material_id] = max(datacore_qty.get(material_id, 0), qty)
            skill_levels.update(self.invention.skills.get(key, {}))

        datacores = sorted((self.inventory.type_name(m) for m in datacore_qty), key=_name_key)
        required_per_run = max(datacore_qty.values()) if datacore_qty else 0
        skills = sorted((self.inventory.type_name(s) for s in skill_levels), key=_name_key)

        science_levels: List[int] = []
        encryption_levels: List[int] = []
        for skill_id in sorted(skill_levels, key=lambda s: _name_key(self.inventory.type_name(s))):
            skill = self.inventory.types.get(skill_id)
            if skill is None:
                continue
            if skill.name.endswith(ENCRYPTION_SUFFIX):
                encryption_levels.append(skill_level)
            elif self.inventory.group_name_of(skill) == SCIENCE_GROUP_NAME:
                science_levels.append(skill_level)

        seconds = self.invention.times.get(used[0], 0)

        rows: List[ProbabilityRow] = []
        for source_id, activity_id in used:
            triple = (source_id, activity_id, blueprint_id)
            source_name = self.inventory.type_name(source_id)
            base_chance = self.invention.probabilities.get(triple, 0.0)
            base_runs = self.invention.quantities.get(triple, 0)
            if is_t3:
                quality = relic_quality(source_name)
                if quality is not None:
                    _, base_chance, base_runs = RELIC_QUALITIES[quality]
            for decryptor, multiplier, runs, me, te in DECRYPTORS:
                rows.append(ProbabilityRow(
                    invented_from=source_name if is_t3 else None,
                    decryptor=decryptor,
                    probability=success_chance(base_chance, science_levels, encryption_levels, multiplier),
                    runs=base_runs + runs,
                    me=BASE_ME + me,
                    te=BASE_TE + te,
                ))

        return InventionPlan(
            product=product,
            tech_level=tech_level,
            base_blueprint=None if is_t3 else self._require_type(used[0][0]),
            datacores=datacores,
            required_per_run=required_per_run,
            skills=skills,
            time_minutes=math.ceil(seconds / 60),
            rows=rows,
        )

    def _relic_sort_key(self, source_id: int):
        name = self.inventory.type_name(source_id)
        quality = relic_quality(name)
        rank = quality if quality is not None else len(RELIC_QUALITIES)
        return (rank, name.lower(), name, source_id)


def _name_key(name: str):
    return (name.lower(), name)


# --- rendering -------------------------------------------------------------

def render_invention(info: ItemInfo, plan: InventionPlan) -> str:
    market = " > ".join(info.market_group_path) if info.market_group_path else "None"
    lines: List[str] = [
        f"ITEM: {info.name} ({info.type_id})",
        f"Group: {info.category_name} > {info.group_name}",
        f"Market Group: {market}",
        f"Tech Level: {plan.tech_level}",
        "",
        "Invention:",
    ]
    if plan.base_blueprint is not None:
        lines.append(f"Base: {plan.base_blueprint.name} ({plan.base_blueprint.type_id})")
    lines += [
        f"Datacores: {', '.join(plan.datacores)}",
        f"Required Per Run: {plan.required_per_run}",
        f"Skills: {', '.join(plan.skills)}",
        f"Time: {plan.time_minutes}",
        "Probabilities:",
    ]
    is_t3 = plan.tech_level == "Tech III"
    if is_t3:
        lines += [
            "| Invented From                | Decryptor                       | Probability | Runs | ME | TE |",
            "|------------------------------|---------------------------------|-------------|------|----|----|",
        ]
    else:
        lines += [
            "| Decryptor                       | Probability | Runs | ME | TE |",
            "|---------------------------------|-------------|------|----|----|",
        ]
    for row in plan.rows:
        cells = f"| {row.decryptor:<32}| {row.probability * 100:.2f}".ljust(48)
        cells += f"| {row.runs:<5}| {row.me:<3}| {row.te:<3}|"
        if is_t3:
            cells = f"| {row.invented_from:<29}" + cells
        lines.append(cells)
    return "\n".join(lines)
