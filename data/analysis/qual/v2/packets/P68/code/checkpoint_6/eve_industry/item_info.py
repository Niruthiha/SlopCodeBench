"""Builds the descriptive header information for an item."""

from .inventory import Inventory
from .models import InvType, ItemInfo


def format_volume(volume: float, is_ship: bool) -> str:
    """Ships (packaged) use two decimals; other items keep their natural precision."""
    if is_ship:
        return f"{volume:.2f}"
    text = repr(float(volume))
    if "e" in text or "E" in text:
        text = format(volume, "f").rstrip("0")
        if text.endswith("."):
            text += "0"
    return text


def describe(inventory: Inventory, item: InvType) -> ItemInfo:
    is_ship = inventory.is_ship(item)
    return ItemInfo(
        type_id=item.type_id,
        name=item.name,
        category_name=inventory.category_name_of(item),
        group_name=inventory.group_name_of(item),
        market_group_path=inventory.market_group_path(item),
        tech_level=inventory.tech_level_of(item),
        volume_text=format_volume(inventory.packaged_volume(item), is_ship),
    )
