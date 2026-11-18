"""Command-line interface."""

import argparse
import sys
from pathlib import Path
from typing import List, Optional

from .industry_data import IndustryData
from .invention import InventionData, InventionError, InventionPlanner, render_invention
from .inventory import Inventory
from .item_info import describe
from .recipe import RecipeError, RecipeResolver
from .report import render
from .sde_loader import SDEFileError


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="industry.py",
        description="Plan EVE Online industry builds from the Static Data Export.",
    )
    sub = parser.add_subparsers(dest="command", required=True)
    recipe = sub.add_parser("recipe", help="Show the recipe for a product or blueprint")
    recipe.add_argument("name", nargs="+", help="Exact typeName of a product or blueprint")
    recipe.add_argument("--sde", required=True, help="Path to the SDE directory")
    invention = sub.add_parser("invention", help="Plan invention / reverse engineering for a product")
    invention.add_argument("name", nargs="+", help="Exact typeName of a Tech II/III product or blueprint")
    invention.add_argument("--sde", required=True, help="Path to the SDE directory")
    invention.add_argument("--skill", type=int, default=5, choices=range(1, 6), metavar="{1-5}",
                           help="Level used for all relevant skills (default 5)")
    return parser


def run_recipe(name: str, sde_dir: Path) -> str:
    inventory = Inventory(sde_dir)
    published = {t.type_id for t in inventory.types.values() if t.published}
    industry = IndustryData(sde_dir, published)
    recipe = RecipeResolver(inventory, industry).resolve(name)
    return render(describe(inventory, recipe.product), recipe)


def run_invention(name: str, sde_dir: Path, skill: int) -> str:
    inventory = Inventory(sde_dir)
    published = {t.type_id for t in inventory.types.values() if t.published}
    industry = IndustryData(sde_dir, published)
    invention = InventionData(sde_dir, published)
    plan = InventionPlanner(inventory, industry, invention).plan(name, skill)
    return render_invention(describe(inventory, plan.product), plan)


def main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    name = " ".join(args.name)
    sde_dir = Path(args.sde)
    if not sde_dir.is_dir():
        print(f"Error: SDE directory not found: {sde_dir}", file=sys.stderr)
        return 2
    try:
        if args.command == "recipe":
            print(run_recipe(name, sde_dir))
        elif args.command == "invention":
            print(run_invention(name, sde_dir, args.skill))
        else:
            return 2
    except (RecipeError, InventionError, SDEFileError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    return 0
