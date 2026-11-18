"""Blueprint activities, products and materials from the industry tables."""

from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

from . import constants as C
from .sde_loader import iter_csv, parse_int

ActivityKey = Tuple[int, int]  # (blueprintTypeID, activityID)


class IndustryData:
    """Indexes manufacturing and reaction data, restricted to published blueprints."""

    def __init__(self, sde_dir: Path, published_type_ids: Set[int]):
        self.activity_names: Dict[int, str] = {}
        self.times: Dict[ActivityKey, int] = {}
        # (blueprint, activity) -> list of (productTypeID, quantity)
        self.products: Dict[ActivityKey, List[Tuple[int, int]]] = defaultdict(list)
        # productTypeID -> list of (blueprint, activity)
        self.sources: Dict[int, List[ActivityKey]] = defaultdict(list)
        # (blueprint, activity) -> {materialTypeID: quantity}
        self.materials: Dict[ActivityKey, Dict[int, int]] = defaultdict(dict)
        self._load(sde_dir, published_type_ids)

    def _load(self, sde_dir: Path, published: Set[int]) -> None:
        wanted = set(C.PRODUCTION_ACTIVITIES)

        for row in iter_csv(sde_dir, C.RAM_ACTIVITIES):
            self.activity_names[int(row["activityID"])] = row["activityName"]

        for row in iter_csv(sde_dir, C.INDUSTRY_ACTIVITY):
            key = (int(row["typeID"]), int(row["activityID"]))
            if key[1] in wanted:
                self.times[key] = parse_int(row["time"]) or 0

        for row in iter_csv(sde_dir, C.INDUSTRY_PRODUCTS):
            key = (int(row["typeID"]), int(row["activityID"]))
            if key[1] not in wanted or key[0] not in published:
                continue
            product_id = int(row["productTypeID"])
            self.products[key].append((product_id, parse_int(row["quantity"]) or 0))
            self.sources[product_id].append(key)

        for row in iter_csv(sde_dir, C.INDUSTRY_MATERIALS):
            key = (int(row["typeID"]), int(row["activityID"]))
            if key[1] not in wanted:
                continue
            material_id = int(row["materialTypeID"])
            quantity = parse_int(row["quantity"]) or 0
            bucket = self.materials[key]
            bucket[material_id] = bucket.get(material_id, 0) + quantity

    def activity_name(self, activity_id: int) -> str:
        return self.activity_names.get(activity_id, str(activity_id))

    def blueprint_activity(self, blueprint_id: int) -> Optional[ActivityKey]:
        """The production activity a published blueprint performs, if any."""
        for activity_id in C.PRODUCTION_ACTIVITIES:
            key = (blueprint_id, activity_id)
            if self.products.get(key):
                return key
        return None

    def sources_of(self, product_id: int) -> List[ActivityKey]:
        """Published (blueprint, activity) pairs producing a type, sorted deterministically."""
        order = {a: i for i, a in enumerate(C.PRODUCTION_ACTIVITIES)}
        return sorted(self.sources.get(product_id, []), key=lambda k: (order[k[1]], k[0]))

    def is_buildable(self, type_id: int) -> bool:
        return bool(self.sources.get(type_id))
