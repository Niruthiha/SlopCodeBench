"""Resolves a product or blueprint name into a concrete recipe."""

import math
from typing import Optional

from .industry_data import ActivityKey, IndustryData
from .inventory import Inventory
from .models import InvType, Material, Recipe


class RecipeError(Exception):
    """Raised when no recipe can be resolved for the requested name."""


class RecipeResolver:
    def __init__(self, inventory: Inventory, industry: IndustryData):
        self.inventory = inventory
        self.industry = industry

    def resolve(self, name: str) -> Recipe:
        candidates = self.inventory.published_by_name(name)
        if not candidates:
            raise RecipeError(f"No published item named '{name}' found in the SDE")

        # Prefer interpreting the name as a blueprint, then as a product.
        for item in candidates:
            key = self.industry.blueprint_activity(item.type_id)
            if key is not None:
                return self._build(key)
        for item in candidates:
            sources = self.industry.sources_of(item.type_id)
            if sources:
                return self._build(sources[0], product_id=item.type_id)

        raise RecipeError(f"'{name}' has no manufacturing or reaction recipe")

    def _build(self, key: ActivityKey, product_id: Optional[int] = None) -> Recipe:
        blueprint_id, activity_id = key
        products = self.industry.products[key]
        if product_id is None:
            product_id, quantity = products[0]
        else:
            quantity = next(q for p, q in products if p == product_id)

        product = self._require_type(product_id)
        blueprint = self._require_type(blueprint_id)
        seconds = self.industry.times.get(key, 0)

        materials = [
            Material(
                type_id=material_id,
                name=self.inventory.type_name(material_id),
                quantity=qty,
                buildable=self.industry.is_buildable(material_id),
            )
            for material_id, qty in self.industry.materials.get(key, {}).items()
        ]
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
