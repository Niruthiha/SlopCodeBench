"""Industry recipes: which blueprint builds what, from what, and how fast.

Secret: how the industry activity tables link blueprints, products,
materials and times; which activities count as "building" an item; and
which blueprint is chosen when several (possibly unpublished) ones exist.
"""

import math
from dataclasses import dataclass
from fractions import Fraction

import sde_source

# Build activities in order of preference.
_BUILD_ACTIVITIES = ("Manufacturing", "Reactions")


@dataclass(frozen=True)
class Recipe:
    product_id: int
    activity: str
    output_quantity: int
    seconds: int
    materials: tuple  # of (material_type_id, quantity_per_run)
    blueprint_id: int = None


def material_amount(quantity, me, runs=1):
    """Units needed: ceil(max(runs, quantity * (1 - ME/100) * runs)), computed exactly.

    Every run consumes at least one unit of each material.
    """
    return math.ceil(max(runs, Fraction(quantity) * (100 - me) / 100 * runs))


def job_seconds(seconds, te):
    """Job duration in seconds after applying time efficiency."""
    return math.ceil(Fraction(seconds) * (100 - te) / 100)


def material_efficiency_applies(activity):
    """Only manufacturing jobs benefit from material efficiency."""
    return activity == "Manufacturing"


class Industry:
    def __init__(self, sde_dir, catalog):
        self._catalog = catalog
        names = dict(sde_source.activities(sde_dir))
        self._activity_rank = {}
        self._activity_name = {}
        for rank, wanted in enumerate(_BUILD_ACTIVITIES):
            for activity_id, name in names.items():
                if name == wanted:
                    self._activity_rank[activity_id] = rank
                    self._activity_name[activity_id] = name

        # (blueprint, activity) -> (product, quantity); product -> [(blueprint, activity)]
        self._outputs = {}
        self._makers = {}
        for bp, act, product, qty in sde_source.activity_products(sde_dir):
            if act not in self._activity_rank:
                continue
            if not (catalog.is_valid(bp) and catalog.is_valid(product)):
                continue
            key = (bp, act)
            if key in self._outputs:
                continue
            self._outputs[key] = (product, qty)
            self._makers.setdefault(product, []).append(key)

        self._times = {}
        for bp, act, seconds in sde_source.activity_times(sde_dir):
            if (bp, act) in self._outputs:
                self._times[(bp, act)] = seconds

        self._materials = {}
        for bp, act, material, qty in sde_source.activity_materials(sde_dir):
            if (bp, act) in self._outputs:
                self._materials.setdefault((bp, act), []).append((material, qty))

    def _rank(self, key):
        return (self._activity_rank[key[1]], key[0])

    def _job_for_blueprint(self, type_id):
        keys = [key for key in self._outputs if key[0] == type_id]
        return min(keys, key=self._rank) if keys else None

    def _job_for_product(self, type_id):
        keys = self._makers.get(type_id)
        return min(keys, key=self._rank) if keys else None

    def recipe_for(self, type_id):
        """Recipe for a blueprint, or for the product it builds; None if neither."""
        key = self._job_for_blueprint(type_id) or self._job_for_product(type_id)
        if key is None:
            return None
        product, quantity = self._outputs[key]
        return Recipe(
            product_id=product,
            activity=self._activity_name[key[1]],
            output_quantity=quantity,
            seconds=self._times.get(key, 0),
            materials=tuple(self._materials.get(key, ())),
            blueprint_id=key[0],
        )

    def is_buildable(self, type_id):
        return type_id in self._makers
