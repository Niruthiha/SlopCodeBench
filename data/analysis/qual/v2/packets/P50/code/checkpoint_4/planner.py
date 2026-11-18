"""Build plans: which jobs to run for a build request and what to buy.

Secret: how a request is turned into manufacturing jobs (splitting runs
across limited-run invented blueprints), how many invention attempts are
expected, which inputs are consumed per job or attempt, and how time and
material efficiency bonuses combine.
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


@dataclass(frozen=True)
class BuildPlan:
    jobs: tuple  # of Job
    purchases: tuple  # of Purchase


def _check(value, low, high, label):
    if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
        raise ValueError("%s must be an integer in [%d,%d], got %r" % (label, low, high, value))
    return value


class Planner:
    def __init__(self, sde_dir, te_bonus=0, invention_skill=5):
        self._te_bonus = _check(te_bonus, 0, 30, "te_bonus")
        self._skill = _check(invention_skill, 1, 5, "invention_skill")
        self._items = catalog.Catalog(sde_dir)
        self._industry = blueprints.Industry(sde_dir, self._items)
        self._invention = invention.Invention(sde_dir, self._items)
        self._volumes = volumes.VolumeResolver(sde_dir, self._items)

    def is_item(self, name):
        return bool(self._items.ids_named(name))

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

    def plan(self, request):
        _check(request.runs, 1, 10 ** 9, "runs per job")
        _check(request.jobs, 1, 10 ** 9, "number of jobs")
        type_id, recipe = self._recipe(request.name)
        buy = {}

        if request.invented:
            outcome = self._outcome(request, type_id)
            me, te, max_runs = outcome.me, outcome.te, outcome.runs
            full, rest = divmod(request.runs, max_runs)
            groups = [(max_runs, full * request.jobs)] if full else []
            copies = full * request.jobs
            if rest:
                groups.append((rest, request.jobs))
                copies += math.ceil(Fraction(request.jobs, max_runs // rest))
            chance = outcome.probability / 100
            if chance <= 0:
                raise LookupError("Invention of %r cannot succeed" % request.name)
            attempts = math.ceil(round(copies / chance, 9))
            for material, quantity in outcome.materials:
                buy[material] = buy.get(material, 0) + quantity * attempts
            if outcome.decryptor != "None":
                decryptors = self._items.ids_named(outcome.decryptor)
                if decryptors:
                    buy[decryptors[0]] = buy.get(decryptors[0], 0) + attempts
            if outcome.invented_from is not None:
                buy[outcome.source_id] = buy.get(outcome.source_id, 0) + attempts
        else:
            me = _check(request.me, 0, 10, "material efficiency")
            te = _check(request.te, 0, 20, "time efficiency")
            groups = [(request.runs, request.jobs)]

        if not blueprints.material_efficiency_applies(recipe.activity):
            me = 0
        for runs, count in groups:
            for material, quantity in recipe.materials:
                needed = blueprints.material_amount(quantity, me, runs) * count
                buy[material] = buy.get(material, 0) + needed

        job_name = self._items.name(recipe.blueprint_id)
        jobs = tuple(
            Job(job_name, runs, self._days(recipe.seconds, runs, te), count)
            for runs, count in groups
        )
        return BuildPlan(jobs=jobs, purchases=self._purchases(buy))

    def _purchases(self, buy):
        totals = {}
        for type_id, quantity in buy.items():
            name = self._items.name(type_id) if self._items.is_valid(type_id) else str(type_id)
            if self._items.is_valid(type_id):
                volume, _ = self._volumes.volume(type_id)
                unit = Decimal(repr(float(volume)))
            else:
                unit = Decimal(0)
            old_quantity, old_volume = totals.get(name, (0, Decimal(0)))
            totals[name] = (old_quantity + quantity, old_volume + unit * quantity)
        return tuple(Purchase(name, q, v) for name, (q, v) in totals.items())
