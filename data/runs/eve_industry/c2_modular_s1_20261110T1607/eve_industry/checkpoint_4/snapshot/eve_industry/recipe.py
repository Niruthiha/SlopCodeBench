"""Resolves a product or blueprint name into a concrete recipe."""

import math
from typing import Optional

from . import constants as C
from .industry_data import ActivityKey, IndustryData
from .inventory import Inventory
from .models import InvType, Material, Recipe


MAX_MATERIAL_EFFICIENCY = 10
MAX_TIME_EFFICIENCY = 20


class RecipeError(Exception):
    """Raised when no recipe can be resolved for the requested name."""


def material_amount(per_run: int, me: int, runs: int = 1) -> int:
    """ceil(max(1, per_run * (1 - ME/100) * runs)), computed exactly in integers."""
    scaled = per_run * (100 - me) * runs
    return max(1, -(-scaled // 100))


def job_seconds(base_seconds: int, te: int) -> int:
    """Job duration in seconds after applying a Time Efficiency percentage."""
    return -(-base_seconds * (100 - te) // 100)


class RecipeResolver:
    def __init__(self, inventory: Inventory, industry: IndustryData):
        self.inventory = inventory
        self.industry = industry

    def resolve(self, name: str, me: int = 0, te: int = 0) -> Recipe:
        candidates = self.inventory.published_by_name(name)
        if not candidates:
            raise RecipeError(f"No published item named '{name}' found in the SDE")

        # Prefer interpreting the name as a blueprint, then as a product.
        for item in candidates:
            key = self.industry.blueprint_activity(item.type_id)
            if key is not None:
                return self._build(key, me=me, te=te)
        for item in candidates:
            sources = self.industry.sources_of(item.type_id)
            if sources:
                return self._build(sources[0], product_id=item.type_id, me=me, te=te)

        raise RecipeError(f"'{name}' has no manufacturing or reaction recipe")

    def _build(
        self, key: ActivityKey, product_id: Optional[int] = None, me: int = 0, te: int = 0
    ) -> Recipe:
        blueprint_id, activity_id = key
        products = self.industry.products[key]
        if product_id is None:
            product_id, quantity = products[0]
        else:
            quantity = next(q for p, q in products if p == product_id)

        product = self._require_type(product_id)
        blueprint = self._require_type(blueprint_id)
        seconds = self.industry.times.get(key, 0)

        # Material and time efficiency only apply to manufacturing jobs.
        if activity_id != C.MANUFACTURING:
            me = te = 0
        seconds = job_seconds(seconds, te)

        best_me = MAX_MATERIAL_EFFICIENCY if activity_id == C.MANUFACTURING else 0
        materials = []
        for material_id, qty in self.industry.materials.get(key, {}).items():
            needed = material_amount(qty, me)
            materials.append(
                Material(
                    type_id=material_id,
                    name=self.inventory.type_name(material_id),
                    quantity=needed,
                    buildable=self.industry.is_buildable(material_id),
                    waste=needed - material_amount(qty, best_me),
                )
            )
        materials.sort(key=lambda m: (m.name.lower(), m.name, m.type_id))

        return Recipe(
            blueprint=blueprint,
            product=product,
            activity_name=self.industry.activity_name(activity_id),
            output_quantity=quantity,
            run_time_minutes=math.ceil(seconds / 60),
            materials=materials,
        )

    def _require_type(self, type_id: int) -> InvType:
        item = self.inventory.types.get(type_id)
        if item is None:
            raise RecipeError(f"Type {type_id} referenced by industry data is missing")
        return item
