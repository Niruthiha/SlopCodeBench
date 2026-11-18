"""Item, group, category, market group and meta (tech level) data."""

from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Optional

from . import constants as C
from .models import Group, InvType, MarketGroup
from .sde_loader import iter_csv, load_yaml, parse_float, parse_int


class Inventory:
    """Indexes the inv* tables and ship volumes from the SDE."""

    def __init__(self, sde_dir: Path):
        self.types: Dict[int, InvType] = {}
        self.types_by_name: Dict[str, List[InvType]] = defaultdict(list)
        self.groups: Dict[int, Group] = {}
        self.categories: Dict[int, str] = {}
        self.market_groups: Dict[int, MarketGroup] = {}
        self.meta_group_of_type: Dict[int, int] = {}
        self.meta_group_names: Dict[int, str] = {}
        self.ship_volumes: Dict[str, float] = {}
        self._load(sde_dir)

    def _load(self, sde_dir: Path) -> None:
        for row in iter_csv(sde_dir, C.INV_TYPES):
            item = InvType(
                type_id=int(row["typeID"]),
                group_id=parse_int(row["groupID"]),
                name=row["typeName"],
                volume=parse_float(row["volume"]),
                published=parse_int(row["published"]) == 1,
                market_group_id=parse_int(row["marketGroupID"]),
            )
            self.types[item.type_id] = item
            if item.published:
                self.types_by_name[item.name].append(item)

        for row in iter_csv(sde_dir, C.INV_GROUPS):
            group = Group(
                group_id=int(row["groupID"]),
                category_id=parse_int(row["categoryID"]),
                name=row["groupName"],
            )
            self.groups[group.group_id] = group

        for row in iter_csv(sde_dir, C.INV_CATEGORIES):
            self.categories[int(row["categoryID"])] = row["categoryName"]

        for row in iter_csv(sde_dir, C.INV_MARKET_GROUPS):
            mg = MarketGroup(
                market_group_id=int(row["marketGroupID"]),
                parent_id=parse_int(row["parentGroupID"]),
                name=row["marketGroupName"],
            )
            self.market_groups[mg.market_group_id] = mg

        for row in iter_csv(sde_dir, C.INV_META_TYPES):
            meta_id = parse_int(row["metaGroupID"])
            if meta_id is not None:
                self.meta_group_of_type[int(row["typeID"])] = meta_id

        for row in iter_csv(sde_dir, C.INV_META_GROUPS):
            self.meta_group_names[int(row["metaGroupID"])] = row["metaGroupName"]

        raw_volumes = load_yaml(sde_dir, C.SHIP_VOLUMES)
        self.ship_volumes = {str(k): float(v) for k, v in raw_volumes.items()}

    # --- lookups -----------------------------------------------------------

    def published_by_name(self, name: str) -> List[InvType]:
        """All published types whose name matches exactly (case-sensitive)."""
        return sorted(self.types_by_name.get(name, []), key=lambda t: t.type_id)

    def type_name(self, type_id: int) -> str:
        item = self.types.get(type_id)
        return item.name if item else str(type_id)

    def group_of(self, item: InvType) -> Optional[Group]:
        return self.groups.get(item.group_id)

    def category_name_of(self, item: InvType) -> str:
        group = self.group_of(item)
        if group is None:
            return "Unknown"
        return self.categories.get(group.category_id, "Unknown")

    def group_name_of(self, item: InvType) -> str:
        group = self.group_of(item)
        return group.name if group else "Unknown"

    def market_group_path(self, item: InvType) -> Optional[List[str]]:
        """Market group names from root to leaf, or None if not on the market."""
        if item.market_group_id is None:
            return None
        path: List[str] = []
        seen = set()
        current = self.market_groups.get(item.market_group_id)
        while current is not None and current.market_group_id not in seen:
            seen.add(current.market_group_id)
            path.append(current.name)
            if current.parent_id is None:
                break
            current = self.market_groups.get(current.parent_id)
        if not path:
            return None
        path.reverse()
        return path

    def tech_level_of(self, item: InvType) -> str:
        meta_id = self.meta_group_of_type.get(item.type_id)
        meta_name = self.meta_group_names.get(meta_id, "") if meta_id else ""
        for level in C.TECH_LEVELS:
            if meta_name == level or meta_name.endswith(" " + level):
                return level
        return C.DEFAULT_TECH_LEVEL

    def is_ship(self, item: InvType) -> bool:
        return self.category_name_of(item) == C.SHIP_CATEGORY_NAME

    def packaged_volume(self, item: InvType) -> float:
        """Packaged volume: ship_volumes.yaml for ships, invTypes otherwise."""
        if self.is_ship(item):
            group_name = self.group_name_of(item)
            if group_name in self.ship_volumes:
                return self.ship_volumes[group_name]
        return item.volume
