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
MAX_SPLIT_DAYS = 30
DEFAULT_SPLIT_DAYS = 3.0
SECONDS_PER_DAY = 86400
CAPITAL_MARKET_GROUP = "Capital Ships"
CAPITAL_SHIP_GROUPS = frozenset({
    "Capital Industrial Ship", "Carrier", "Dreadnought", "Force Auxiliary", "Freighter",
    "Jump Freighter", "Lancer Dreadnought", "Supercarrier", "Titan",
})
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
    split_days: float = DEFAULT_SPLIT_DAYS
    component_me: int = MAX_MATERIAL_EFFICIENCY
    component_te: int = MAX_TIME_EFFICIENCY


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
    # typeID -> surplus left over after the build
    leftovers: Dict[int, int] = field(default_factory=dict)


def load_config(path: Path) -> PlanConfig:
    if not path.is_file():
        raise PlanError(f"Config file not found: {path}")
    raw = load_yaml(path.parent, path.name)
    if not isinstance(raw, dict):
        raise PlanError(f"Config file must be a mapping: {path}")
    te_bonus = _config_int(raw, "te_bonus", 0, 0, MAX_TE_BONUS)
    skill = _config_int(raw, "invention_skill", 5, 1, 5)
    split_days = _config_split_days(raw)
    defaults = raw.get("component_bpo_defaults")
    if defaults is None:
        defaults = {}
    if not isinstance(defaults, dict):
        raise PlanError("Config 'component_bpo_defaults' must be a mapping with 'me' and 'te'")
    me = _config_int(defaults, "me", MAX_MATERIAL_EFFICIENCY, 0, MAX_MATERIAL_EFFICIENCY)
    te = _config_int(defaults, "te", MAX_TIME_EFFICIENCY, 0, MAX_TIME_EFFICIENCY)
    return PlanConfig(te_bonus=te_bonus, invention_skill=skill, split_days=split_days,
                      component_me=me, component_te=te)


def _config_split_days(raw: dict) -> float:
    value = raw.get("split_days", DEFAULT_SPLIT_DAYS)
    if value is None:
        value = DEFAULT_SPLIT_DAYS
    if isinstance(value, bool) or not isinstance(value, (int, float)) or math.isnan(value):
        raise PlanError(f"Config 'split_days' must be a number in (0,{MAX_SPLIT_DAYS}], got {value!r}")
    if not 0 < value <= MAX_SPLIT_DAYS:
        raise PlanError(f"Config 'split_days' must be a number in (0,{MAX_SPLIT_DAYS}], got {value}")
    return float(value)


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

    def plan(self, spec: BuildSpec, config: PlanConfig, build_all: bool = False) -> BuildPlan:
        purchases: Dict[int, int] = defaultdict(int)
        me, te = spec.me, spec.te
        if spec.invented:
            me, te = self._plan_invention(spec, config, purchases)

        blueprint_id, activity_id = spec.blueprint_key
        if activity_id != C.MANUFACTURING:
            me = te = 0

        if not build_all:
            for material_id, qty in self.industry.materials.get(spec.blueprint_key, {}).items():
                purchases[material_id] += _job_material(qty, me, spec.runs) * spec.jobs
            job = self._job(spec.blueprint_key, spec.runs, te, spec.jobs, config)
            return BuildPlan(jobs=[job], purchases=dict(purchases))

        demand: Dict[int, int] = defaultdict(int)
        jobs: Dict[Tuple[str, int], Job] = {}

        def schedule(key: ActivityKey, runs: int, count: int, me: int, te: int) -> None:
            days_per_run = self._days_per_run(key, te, config)
            for job_runs, job_count in split_runs(runs, days_per_run, config.split_days):
                job = self._job(key, job_runs, te, job_count * count, config)
                previous = jobs.get((job.name, job.runs))
                if previous is not None:
                    job = Job(job.name, job.runs, job.days, previous.count + job.count)
                jobs[(job.name, job.runs)] = job
                for material_id, qty in self.industry.materials.get(key, {}).items():
                    amount = _job_material(qty, me, job_runs) * job_count * count
                    if self.industry.is_buildable(material_id):
                        demand[material_id] += amount
                    else:
                        purchases[material_id] += amount

        schedule(spec.blueprint_key, spec.runs, spec.jobs, me, te)

        leftovers: Dict[int, int] = {}
        for type_id in self._consumer_order(spec.blueprint_key):
            needed = demand.get(type_id, 0)
            if needed <= 0:
                continue
            key = self.industry.sources_of(type_id)[0]
            per_run = next(q for p, q in self.industry.products[key] if p == type_id)
            if per_run <= 0:
                raise PlanError(f"'{self.inventory.type_name(type_id)}' cannot be built")
            runs = -(-needed // per_run)
            surplus = runs * per_run - needed
            if surplus:
                leftovers[type_id] = surplus
            component_me, component_te = self._component_efficiency(type_id, key, config)
            schedule(key, runs, 1, component_me, component_te)

        return BuildPlan(jobs=list(jobs.values()), purchases=dict(purchases), leftovers=leftovers)

    def _job(self, key: ActivityKey, runs: int, te: int, count: int, config: PlanConfig) -> Job:
        seconds = self.industry.times.get(key, 0) * runs
        seconds *= (100 - te) * (100 - config.te_bonus) / 10000
        return Job(
            name=self.inventory.type_name(key[0]),
            runs=runs,
            days=round(seconds / SECONDS_PER_DAY, 2),
            count=count,
        )

    def _days_per_run(self, key: ActivityKey, te: int, config: PlanConfig) -> float:
        seconds = self.industry.times.get(key, 0) * ((100 - te) * (100 - config.te_bonus) / 10000)
        return seconds / SECONDS_PER_DAY

    def _component_efficiency(self, type_id: int, key: ActivityKey,
                              config: PlanConfig) -> Tuple[int, int]:
        if key[1] != C.MANUFACTURING:
            return 0, 0
        item = self.inventory.types.get(type_id)
        if item is not None and self._is_t1_capital(item):
            return 0, 0
        return config.component_me, config.component_te

    def _is_t1_capital(self, item: InvType) -> bool:
        if not self.inventory.is_ship(item) or self.inventory.tech_level_of(item) != "Tech I":
            return False
        if self.inventory.group_name_of(item) in CAPITAL_SHIP_GROUPS:
            return True
        return CAPITAL_MARKET_GROUP in (self.inventory.market_group_path(item) or [])

    def _consumer_order(self, root: ActivityKey) -> List[int]:
        """Buildable materials reachable from ``root``, each listed after all of its consumers."""
        order: List[int] = []
        state: Dict[int, int] = {}  # 1 = in progress, 2 = done

        def materials_of(key: ActivityKey) -> List[int]:
            return sorted(m for m in self.industry.materials.get(key, {})
                          if self.industry.is_buildable(m))

        stack: List[Tuple[int, List[int]]] = []
        for material_id in materials_of(root):
            if material_id in state:
                continue
            state[material_id] = 1
            stack.append((material_id, materials_of(self.industry.sources_of(material_id)[0])))
            while stack:
                type_id, pending = stack[-1]
                if pending:
                    child = pending.pop()
                    seen = state.get(child)
                    if seen == 1:
                        raise PlanError(
                            f"Circular recipe involving '{self.inventory.type_name(child)}'")
                    if seen is None:
                        state[child] = 1
                        stack.append((child, materials_of(self.industry.sources_of(child)[0])))
                    continue
                stack.pop()
                state[type_id] = 2
                order.append(type_id)
        order.reverse()
        return order

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


def _job_material(per_run: int, me: int, runs: int) -> int:
    """Material needed by a single job, rounded up at the job level."""
    return max(runs, -(-per_run * (100 - me) * runs // 100))


def split_runs(runs: int, days_per_run: float, split_days: float) -> List[Tuple[int, int]]:
    """Split ``runs`` into jobs within the day limit; returns (runs, count) pairs."""
    if runs <= 1 or days_per_run <= 0:
        return [(runs, 1)]
    max_runs = max(1, int(min(float(MAX_SPLIT_DAYS), split_days) // days_per_run))
    if runs <= max_runs:
        return [(runs, 1)]
    t = -(-runs // max_runs)
    base, extra = divmod(runs, t)
    if base + 1 == max_runs and extra > t / 2 and runs // (t + 1) + 1 < max_runs:
        t += 1
        base, extra = divmod(runs, t)
    return [(r, c) for r, c in ((base + 1, extra), (base, t - extra)) if c > 0 and r > 0]


# --- output ----------------------------------------------------------------

def write_plan(plan: BuildPlan, inventory: Inventory, output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)

    rows = []
    for type_id in set(plan.purchases) | set(plan.leftovers):
        quantity = plan.purchases.get(type_id, 0)
        item = inventory.types.get(type_id)
        name = inventory.type_name(type_id)
        volume = inventory.packaged_volume(item) if item else 0.0
        rows.append((name, quantity, round(quantity * volume, 2), 0, plan.leftovers.get(type_id, 0)))
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
