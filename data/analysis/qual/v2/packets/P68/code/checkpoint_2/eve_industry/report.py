"""Renders the canonical recipe report block."""

from typing import List

from .models import ItemInfo, Recipe


def render(info: ItemInfo, recipe: Recipe) -> str:
    market = " > ".join(info.market_group_path) if info.market_group_path else "None"
    lines: List[str] = [
        f"ITEM: {info.name} ({info.type_id})",
        f"Group: {info.category_name} > {info.group_name}",
        f"Market Group: {market}",
        f"Tech Level: {info.tech_level}",
        f"Volume: {info.volume_text}",
        "",
        "Recipe:",
        f"Activity: {recipe.activity_name}",
        f"Output Quantity: {recipe.output_quantity}",
        f"Run Time: {recipe.run_time_minutes}",
        "| Item | Quantity | Buildable |",
        "|:-:|:---:|---:|",
    ]
    for material in recipe.materials:
        buildable = "Yes" if material.buildable else "No"
        lines.append(f"| {material.name} | {material.quantity} | {buildable} |")
    return "\n".join(lines)
