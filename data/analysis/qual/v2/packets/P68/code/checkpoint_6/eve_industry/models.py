"""Plain data structures used throughout the tool."""

from dataclasses import dataclass, field
from typing import List, Optional


@dataclass(frozen=True)
class InvType:
    type_id: int
    group_id: int
    name: str
    volume: float
    published: bool
    market_group_id: Optional[int]


@dataclass(frozen=True)
class Group:
    group_id: int
    category_id: int
    name: str


@dataclass(frozen=True)
class MarketGroup:
    market_group_id: int
    parent_id: Optional[int]
    name: str


@dataclass(frozen=True)
class Material:
    type_id: int
    name: str
    quantity: int
    buildable: bool
    waste: int = 0


@dataclass
class Recipe:
    blueprint: InvType
    product: InvType
    activity_name: str
    output_quantity: int
    run_time_minutes: int
    materials: List[Material] = field(default_factory=list)


@dataclass(frozen=True)
class ItemInfo:
    type_id: int
    name: str
    category_name: str
    group_name: str
    market_group_path: Optional[List[str]]
    tech_level: str
    volume_text: str
