"""Build plans: which jobs to run for a build request and what to buy.

Secret: how a request is turned into manufacturing jobs (splitting runs
across limited-run invented blueprints), how many invention attempts are
expected, which inputs are consumed per job or attempt, and how time and
material efficiency bonuses combine; with build-all, how the whole
buildable tree below the product is resolved into component jobs, which
efficiencies components use, and how long jobs are split; how stock on
hand is drawn on before building or buying, and how stock targets are
met by building (inventing without a decryptor) or buying.
"""

import math
from dataclasses import dataclass
from decimal import Decimal
from fractions import Fraction

import blueprints
import catalog
import invention
import volumes

_SECONDS_PER_DAY = 86400
_MAX_SPLIT_DAYS = 30
_SHIP_CATEGORY = "Ship"
_CAPITAL_MARKET_GROUP = "Capital Ships"
_CAPITAL_GROUPS = frozenset((
    "Titan", "Supercarrier", "Dreadnought", "Lancer Dreadnought", "Carrier",
    "Force Auxiliary", "Freighter", "Jump Freighter", "Capital Industrial Ship",
))


@dataclass(frozen=True)
class Job:
    name: str  # blueprint name
    runs: int
    days: Fraction  # duration of one job
    count: int


@dataclass(frozen=True)
class Purchase:
    name: str
    quantity: int
    volume: Decimal  # m3 for the whole quantity
    start_amount: int = 0
    end_amount: int = 0  # built but left over at the end


@dataclass(frozen=True)
class BuildPlan:
    jobs: tuple  # of Job
    purchases: tuple  # of Purchase


def _check(value, low, high, label):
    if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
        raise ValueError("%s must be an integer in [%d,%d], got %r" % (label, low, high, value))
    return value


def _check_days(value, label):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not value > 0:
        raise ValueError("%s must be a positive number, got %r" % (label, value))
    return min(Fraction(repr(float(value))), Fraction(_MAX_SPLIT_DAYS))


def split_runs(runs, max_runs):
    """[(runs, count)] for one job of `runs` split so no job exceeds max_runs."""
    max_runs = max(1, max_runs)
    if runs <= max_runs:
        return [(runs, 1)]
    t = math.ceil(Fraction(runs, max_runs))
    base, extra = divmod(runs, t)
    if base + 1 == max_runs and 2 * extra > t and runs // (t + 1) + 1 < max_runs:
        t += 1
        base, extra = divmod(runs, t)
    return [(r, c) for r, c in ((base + 1, extra), (base, t - extra)) if c and r]


class Planner:
    def __init__(self, sde_dir, te_bonus=0, invention_skill=5, split_days=3.0,
                 component_me=10, component_te=20):
        self._te_bonus = _check(te_bonus, 0, 30, "te_bonus")
        self._skill = _check(invention_skill, 1, 5, "invention_skill")
        self._split_days = _check_days(split_days, "split_days")
        self._component_me = _check(component_me, 0, 10, "component_bpo_defaults me")
        self._component_te = _check(component_te, 0, 20, "component_bpo_defaults te")
        self._items = catalog.Catalog(sde_dir)
        self._industry = blueprints.Industry(sde_dir, self._items)
        self._invention = invention.Invention(sde_dir, self._items)
        self._volumes = volumes.VolumeResolver(sde_dir, self._items)
        self._names_by_lower = None

    def is_item(self, name):
        return bool(self._items.ids_named(name))

    def canonical_name(self, name):
        """The published item name matching `name` (exactly, else ignoring case)."""
        if self._items.ids_named(name):
            return name
        if self._names_by_lower is None:
            self._names_by_lower = {}
            for known in self._items.names():
                self._names_by_lower.setdefault(known.lower(), known)
        return self._names_by_lower.get(name.lower())

    def is_relic(self, name):
        return any(
            invention.is_relic_name(self._items.name(t)) for t in self._items.ids_named(name)
        )

    def _recipe(self, name):
        candidates = self._items.ids_named(name)
        if not candidates:
            raise LookupError("No published item named %r" % name)
        for type_id in candidates:
            recipe = self._industry.recipe_for(type_id)
            if recipe is not None:
                return type_id, recipe
        raise LookupError("%r cannot be manufactured or reacted" % name)

    def _outcome(self, request, type_id):
        plan = self._invention.plan(type_id, self._skill)
        if plan is None:
            raise LookupError("%r cannot be invented or reverse engineered" % request.name)
        if plan.from_relics and request.relic is None:
            raise LookupError("%r is reverse engineered; a relic is required" % request.name)
        if not plan.from_relics and request.relic is not None:
            raise LookupError("%r is invented, not reverse engineered" % request.name)
        for outcome in plan.outcomes:
            if outcome.decryptor != request.decryptor:
                continue
            if plan.from_relics and outcome.invented_from.lower() != request.relic.lower():
                continue
            return outcome
        raise LookupError("No invention outcome for %r with %r" % (request.name, request.relic))

    def _days(self, seconds, runs, te):
        total = Fraction(seconds * runs) * (100 - te) / 100 * (100 - self._te_bonus) / 100
        return total / _SECONDS_PER_DAY

    def _max_runs(self, seconds, te):
        """Most runs one job can have while finishing in under the split limit."""
        per_run = self._days(seconds, 1, te)
        if per_run <= 0:
            return None
        return math.ceil(self._split_days / per_run) - 1

    def _split(self, groups, seconds, te):
        max_runs = self._max_runs(seconds, te)
        if max_runs is None:
            return list(groups)
        return [
            (runs, count * times)
            for job_runs, count in groups
            for runs, times in split_runs(job_runs, max_runs)
        ]

    def _is_capital(self, type_id):
        if self._items.category_name(type_id) != _SHIP_CATEGORY:
            return False
        if self._items.tech_level(type_id) != "Tech I":
            return False
        return (_CAPITAL_MARKET_GROUP in self._items.market_path(type_id)
                or self._items.group_name(type_id) in _CAPITAL_GROUPS)

    def _component_efficiency(self, type_id, recipe):
        if not blueprints.material_efficiency_applies(recipe.activity):
            return 0, 0
        if self._is_capital(type_id):
            return 0, 0
        return self._component_me, self._component_te

    def _build_order(self, product_id, materials, roots=(), recursive=True):
        """(buildable items below a product and below each root, every item
        before its inputs; (consumer, material) edges closing a cycle, whose
        material is bought).  The roots themselves are included."""
        order = []
        cut = set()
        state = {product_id: "active"}

        def visit(consumer, materials):
            for material, _ in materials:
                if not self._industry.is_buildable(material):
                    continue
                if state.get(material) == "active":
                    cut.add((consumer, material))
                    continue
                if state.get(material) == "done":
                    continue
                state[material] = "active"
                visit(material, self._industry.recipe_for(material).materials)
                state[material] = "done"
                order.append(material)

        if recursive:
            visit(product_id, materials)
        del state[product_id]
        for root in roots:
            if state.get(root) == "done" or not self._industry.is_buildable(root):
                continue
            state[root] = "active"
            if recursive:
                visit(root, self._industry.recipe_for(root).materials)
            state[root] = "done"
            order.append(root)
        return list(reversed(order)), cut

    def _consume(self, recipe, me, groups, buy, demand, consumed, cut=()):
        for runs, count in groups:
            for material, quantity in recipe.materials:
                needed = blueprints.material_amount(quantity, me, runs) * count
                built = (demand is not None and self._industry.is_buildable(material)
                         and (recipe.product_id, material) not in cut)
                target = demand if built else buy
                target[material] = target.get(material, 0) + needed
                consumed[material] = consumed.get(material, 0) + needed

    def _job_rows(self, recipe, groups, te):
        name = self._items.name(recipe.blueprint_id)
        return [Job(name, runs, self._days(recipe.seconds, runs, te), count)
                for runs, count in groups]

    def _invent(self, name, outcome, runs, jobs, buy, consumed):
        """Job groups for `jobs` jobs of `runs` runs built from invented copies;
        the expected invention inputs are added to `buy`."""
        max_runs = outcome.runs
        full, rest = divmod(runs, max_runs)
        groups = [(max_runs, full * jobs)] if full else []
        copies = full * jobs
        if rest:
            groups.append((rest, jobs))
            copies += math.ceil(Fraction(jobs, max_runs // rest))
        chance = outcome.probability / 100
        if chance <= 0:
            raise LookupError("Invention of %r cannot succeed" % name)
        attempts = math.ceil(round(copies / chance, 9))
        inputs = list(outcome.materials)
        if outcome.decryptor != "None":
            decryptors = self._items.ids_named(outcome.decryptor)
            if decryptors:
                inputs.append((decryptors[0], 1))
        if outcome.invented_from is not None:
            inputs.append((outcome.source_id, 1))
        for material, quantity in inputs:
            buy[material] = buy.get(material, 0) + quantity * attempts
            consumed[material] = consumed.get(material, 0) + quantity * attempts
        return groups

    def _target_outcome(self, type_id):
        """Invention outcome without a decryptor for an inventable item; None otherwise."""
        plan = self._invention.plan(type_id, self._skill)
        if plan is None:
            return None
        return next((o for o in plan.outcomes if o.decryptor == "None"), None)

    def resolve_amounts(self, amounts):
        """{type_id: quantity} for {item name: quantity}, preferring buildable types."""
        resolved = {}
        for name, quantity in amounts.items():
            candidates = self._items.ids_named(name)
            if not candidates:
                raise LookupError("No published item named %r" % name)
            type_id = next(
                (t for t in candidates if self._industry.is_buildable(t)), candidates[0]
            )
            resolved[type_id] = resolved.get(type_id, 0) + quantity
        return resolved

    def plan(self, request, build_all=False, stocks=None, targets=None):
        """Jobs and purchases for a request.

        stocks: {item name: quantity} on hand and usable; targets: {item
        name: quantity} that must be left over once everything is built.
        """
        _check(request.runs, 1, 10 ** 9, "runs per job")
        _check(request.jobs, 1, 10 ** 9, "number of jobs")
        type_id, recipe = self._recipe(request.name)
        pool = {}
        for name, quantity in (stocks or {}).items():
            pool[name] = pool.get(name, 0) + _check(quantity, 0, 10 ** 15, "stock of " + name)
        start = dict(pool)
        targets = self.resolve_amounts(targets or {})
        for target_id, quantity in targets.items():
            _check(quantity, 0, 10 ** 15, "target of " + self._items.name(target_id))
        buy = {}
        consumed = {}

        if request.invented:
            outcome = self._outcome(request, type_id)
            me, te = outcome.me, outcome.te
            groups = self._invent(request.name, outcome, request.runs, request.jobs, buy, consumed)
        else:
            me = _check(request.me, 0, 10, "material efficiency")
            te = _check(request.te, 0, 20, "time efficiency")
            groups = [(request.runs, request.jobs)]

        if not blueprints.material_efficiency_applies(recipe.activity):
            me = 0
        if build_all:
            groups = self._split(groups, recipe.seconds, te)
        order, cut = self._build_order(recipe.product_id, recipe.materials,
                                       sorted(targets), recursive=build_all)
        demand = {} if build_all else None
        self._consume(recipe, me, groups, buy, demand, consumed, cut)
        jobs = self._job_rows(recipe, groups, te)
        built = {}
        for item in order:
            component = self._industry.recipe_for(item)
            needed = (demand.pop(item, 0) if demand is not None else 0) + targets.get(item, 0)
            needed -= _take(pool, self._items.name(item), needed)
            output = component.output_quantity or 1
            runs = math.ceil(Fraction(needed, output))
            if runs <= 0:
                continue
            built[item] = built.get(item, 0) + runs * output
            outcome = self._target_outcome(item) if item in targets else None
            if outcome is not None:
                c_me, c_te = outcome.me, outcome.te
                c_groups = self._invent(self._items.name(item), outcome, runs, 1, buy, consumed)
            else:
                c_me, c_te = self._component_efficiency(item, component)
                c_groups = [(runs, 1)]
            if not blueprints.material_efficiency_applies(component.activity):
                c_me = 0
            if build_all:
                c_groups = self._split(c_groups, component.seconds, c_te)
            self._consume(component, c_me, c_groups, buy, demand, consumed, cut)
            jobs.extend(self._job_rows(component, c_groups, c_te))
        processed = set(order)
        for item, quantity in targets.items():
            if item not in processed:
                buy[item] = buy.get(item, 0) + quantity
        bought = {}
        for item, quantity in buy.items():
            name = self._items.name(item) if self._items.is_valid(item) else str(item)
            bought[item] = quantity - _take(pool, name, quantity)
        return BuildPlan(jobs=tuple(jobs),
                         purchases=self._purchases(bought, start, built, consumed))

    def _purchases(self, bought, start, built, consumed):
        rows = {}  # name -> [to_buy, volume, start, end]

        def row(name):
            return rows.setdefault(name, [0, Decimal(0), start.get(name, 0), start.get(name, 0)])

        for type_id, quantity in bought.items():
            if self._items.is_valid(type_id):
                volume, _ = self._volumes.volume(type_id)
                unit = Decimal(repr(float(volume)))
                name = self._items.name(type_id)
            else:
                unit = Decimal(0)
                name = str(type_id)
            entry = row(name)
            entry[0] += quantity
            entry[1] += unit * quantity
            entry[3] += quantity
        for type_id, quantity in built.items():
            row(self._items.name(type_id))[3] += quantity
        for type_id, quantity in consumed.items():
            name = self._items.name(type_id) if self._items.is_valid(type_id) else str(type_id)
            row(name)[3] -= quantity
        return tuple(
            Purchase(name, q, v, start_amount=s, end_amount=e)
            for name, (q, v, s, e) in rows.items()
            if q > 0 or s != e
        )


def _take(pool, name, wanted):
    """Remove up to `wanted` of `name` from the pool; return how many were taken."""
    taken = min(pool.get(name, 0), max(wanted, 0))
    if taken:
        pool[name] -= taken
    return taken
