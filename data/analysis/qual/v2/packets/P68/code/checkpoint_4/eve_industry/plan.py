"""Build plans: parses a build string and produces the jobs and materials to buy."""

import csv
import math
import re
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from . import constants as C
from .industry_data import ActivityKey, IndustryData
from .invention import DECRYPTORS, InventionData, InventionError, InventionPlanner
from .inventory import Inventory
from .models import InvType
from .recipe import MAX_MATERIAL_EFFICIENCY, MAX_TIME_EFFICIENCY
from .sde_loader import load_yaml

MAX_TE_BONUS = 30
SECONDS_PER_DAY = 86400
NO_DECRYPTOR = "None"
DECRYPTOR_SUFFIX = " Decryptor"

_JOBS_RE = re.compile(r"^[xX](\d+)$")
_INT_RE = re.compile(r"^\d+$")


class PlanError(Exception):
    """Raised when a build string or config cannot be turned into a build plan."""


@dataclass(frozen=True)
class PlanConfig:
    te_bonus: int = 0
    invention_skill: int = 5


@dataclass(frozen=True)
class BuildSpec:
    product: InvType
    blueprint_key: ActivityKey
    runs: int
    jobs: int
    me: int = 0
    te: int = 0
    decryptor: Optional[str] = None  # set for invention / reverse engineering
    relic: Optional[str] = None  # set for reverse engineering

    @property
    def invented(self) -> bool:
        return self.decryptor is not None


@dataclass(frozen=True)
class Job:
    name: str
    runs: int
    days: float
    count: int


@dataclass
class BuildPlan:
    jobs: List[Job] = field(default_factory=list)
    # typeID -> quantity to buy
    purchases: Dict[int, int] = field(default_factory=dict)


def load_config(path: Path) -> PlanConfig:
    if not path.is_file():
        raise PlanError(f"Config file not found: {path}")
    raw = load_yaml(path.parent, path.name)
    if not isinstance(raw, dict):
        raise PlanError(f"Config file must be a mapping: {path}")
    te_bonus = _config_int(raw, "te_bonus", 0, 0, MAX_TE_BONUS)
    skill = _config_int(raw, "invention_skill", 5, 1, 5)
    return PlanConfig(te_bonus=te_bonus, invention_skill=skill)


def _config_int(raw: dict, key: str, default: int, low: int, high: int) -> int:
    value = raw.get(key, default)
    if value is None:
        value = default
    if isinstance(value, bool) or not isinstance(value, (int, float)) or int(value) != value:
        raise PlanError(f"Config '{key}' must be an integer in [{low},{high}], got {value!r}")
    value = int(value)
    if not low <= value <= high:
        raise PlanError(f"Config '{key}' must be an integer in [{low},{high}], got {value}")
    return value


def _decryptor_name(text: str) -> Optional[str]:
    """Canonical decryptor name ('None' included) for user text, or None if unknown."""
    folded = text.lower()
    for name, *_ in DECRYPTORS:
        if folded == name.lower():
            return name
        if name.endswith(DECRYPTOR_SUFFIX) and folded == name[: -len(DECRYPTOR_SUFFIX)].lower():
            return name
    return None


def _positive(text: str, what: str) -> int:
    value = int(text)
    if value < 1:
        raise PlanError(f"{what} must be at least 1, got {value}")
    return value


class BuildPlanner:
    def __init__(self, inventory: Inventory, industry: IndustryData, invention: InventionData):
        self.inventory = inventory
        self.industry = industry
        self.invention = invention

    # --- build string parsing ----------------------------------------------

    def parse(self, build: str) -> BuildSpec:
        tokens = build.split()
        if not tokens:
            raise PlanError("Empty build string")
        jobs = 1
        match = _JOBS_RE.match(tokens[-1])
        if match and len(tokens) > 1:
            jobs = _positive(match.group(1), "Number of jobs")
            tokens = tokens[:-1]

        # Longest item name first, so names containing numbers still resolve.
        for split in range(len(tokens), 0, -1):
            name = " ".join(tokens[:split])
            target = self._production_key(name)
            if target is None:
                continue
            spec = self._interpret(target, tokens[split:], jobs)
            if spec is not None:
                return spec

        for split in range(len(tokens), 0, -1):
            if self.inventory.published_by_name(" ".join(tokens[:split])):
                raise PlanError(f"Cannot interpret build string '{build}'")
        raise PlanError(f"No buildable published item found in build string '{build}'")

    def _production_key(self, name: str) -> Optional[Tuple[InvType, ActivityKey]]:
        candidates = self.inventory.published_by_name(name)
        for item in candidates:
            sources = self.industry.sources_of(item.type_id)
            if sources:
                return item, sources[0]
        # Be lenient and accept a blueprint name as well.
        for item in candidates:
            key = self.industry.blueprint_activity(item.type_id)
            if key is not None:
                product = self.inventory.types.get(self.industry.products[key][0][0])
                if product is not None:
                    return product, key
        return None

    def _interpret(self, target: Tuple[InvType, ActivityKey], rest: List[str],
                   jobs: int) -> Optional[BuildSpec]:
        product, key = target
        if not rest:
            return BuildSpec(product, key, runs=1, jobs=jobs)
        if not _INT_RE.match(rest[0]):
            return None
        runs = _positive(rest[0], "Runs per job")
        rest = rest[1:]
        if not rest:
            return BuildSpec(product, key, runs=runs, jobs=jobs)
        if len(rest) == 2 and all(_INT_RE.match(t) for t in rest):
            me, te = int(rest[0]), int(rest[1])
            if not 0 <= me <= MAX_MATERIAL_EFFICIENCY:
                raise PlanError(f"Material efficiency must be in [0,{MAX_MATERIAL_EFFICIENCY}], got {me}")
            if not 0 <= te <= MAX_TIME_EFFICIENCY:
                raise PlanError(f"Time efficiency must be in [0,{MAX_TIME_EFFICIENCY}], got {te}")
            return BuildSpec(product, key, runs=runs, jobs=jobs, me=me, te=te)
        for split in range(len(rest), 0, -1):
            decryptor = _decryptor_name(" ".join(rest[:split]))
            if decryptor is None:
                continue
            relic = " ".join(rest[split:]) or None
            return BuildSpec(product, key, runs=runs, jobs=jobs, decryptor=decryptor, relic=relic)
        return None

    # --- planning ----------------------------------------------------------

    def plan(self, spec: BuildSpec, config: PlanConfig) -> BuildPlan:
        purchases: Dict[int, int] = defaultdict(int)
        me, te = spec.me, spec.te
        if spec.invented:
            me, te = self._plan_invention(spec, config, purchases)

        blueprint_id, activity_id = spec.blueprint_key
        if activity_id != C.MANUFACTURING:
            me = te = 0

        for material_id, qty in self.industry.materials.get(spec.blueprint_key, {}).items():
            per_job = max(spec.runs, -(-qty * (100 - me) * spec.runs // 100))
            purchases[material_id] += per_job * spec.jobs

        seconds = self.industry.times.get(spec.blueprint_key, 0) * spec.runs
        seconds *= (100 - te) * (100 - config.te_bonus) / 10000
        job = Job(
            name=self.inventory.type_name(blueprint_id),
            runs=spec.runs,
            days=round(seconds / SECONDS_PER_DAY, 2),
            count=spec.jobs,
        )
        return BuildPlan(jobs=[job], purchases=dict(purchases))

    def _plan_invention(self, spec: BuildSpec, config: PlanConfig,
                        purchases: Dict[int, int]) -> Tuple[int, int]:
        """Add invention inputs to ``purchases``; return the invented blueprint's (ME, TE)."""
        planner = InventionPlanner(self.inventory, self.industry, self.invention)
        try:
            invention = planner.plan(spec.product.name, config.invention_skill)
        except InventionError as exc:
            raise PlanError(str(exc))
        is_t3 = invention.tech_level == "Tech III"
        if is_t3 and spec.relic is None:
            raise PlanError(f"'{spec.product.name}' is reverse engineered; a relic name is required")
        if not is_t3 and spec.relic is not None:
            raise PlanError(f"'{spec.product.name}' is invented; relics do not apply")

        row = next(
            (r for r in invention.rows
             if r.decryptor == spec.decryptor and (not is_t3 or r.invented_from == spec.relic)),
            None,
        )
        if row is None:
            raise PlanError(f"'{spec.relic}' cannot be used to reverse engineer '{spec.product.name}'")
        if row.probability <= 0 or row.runs <= 0:
            raise PlanError(f"'{spec.product.name}' cannot be invented with these inputs")

        blueprints = math.ceil(spec.runs * spec.jobs / row.runs)
        attempts = math.ceil(blueprints / row.probability - 1e-9)

        source = self._invention_source(spec, is_t3)
        for material_id, qty in self.invention.materials.get(source, {}).items():
            purchases[material_id] += qty * attempts
        if spec.decryptor != NO_DECRYPTOR:
            purchases[self._type_id(spec.decryptor)] += attempts
        if is_t3:
            purchases[source[0]] += attempts
        return row.me, row.te

    def _invention_source(self, spec: BuildSpec, is_t3: bool) -> ActivityKey:
        sources = self.invention.sources_of(spec.blueprint_key[0])
        if is_t3:
            for key in sources:
                if self.inventory.type_name(key[0]) == spec.relic:
                    return key
            raise PlanError(f"'{spec.relic}' cannot be used to reverse engineer '{spec.product.name}'")
        return sources[0]

    def _type_id(self, name: str) -> int:
        candidates = self.inventory.published_by_name(name)
        if not candidates:
            raise PlanError(f"No published item named '{name}' found in the SDE")
        return candidates[0].type_id


# --- output ----------------------------------------------------------------

def write_plan(plan: BuildPlan, inventory: Inventory, output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)

    rows = []
    for type_id, quantity in plan.purchases.items():
        item = inventory.types.get(type_id)
        name = inventory.type_name(type_id)
        volume = inventory.packaged_volume(item) if item else 0.0
        rows.append((name, quantity, round(quantity * volume, 2), 0, 0))
    rows.sort(key=lambda r: r[0])
    with open(output_dir / "materials.csv", "w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh, lineterminator="\n")
        writer.writerow(["name", "to_buy", "buy_volume", "start_amount", "end_amount"])
        writer.writerows(rows)

    jobs = sorted(plan.jobs, key=lambda j: (j.name, j.runs, j.count, j.days))
    with open(output_dir / "jobs.csv", "w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh, lineterminator="\n")
        writer.writerow(["name", "runs", "days", "count"])
        for job in jobs:
            writer.writerow([job.name, job.runs, job.days, job.count])
