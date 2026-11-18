"""Command-line interface."""

import argparse
import sys
from pathlib import Path
from typing import List, Optional

from .industry_data import IndustryData
from .invention import InventionData, InventionError, InventionPlanner, render_invention
from .inventory import Inventory
from .item_info import describe
from .plan import BuildPlanner, PlanError, load_config, write_plan
from .recipe import MAX_MATERIAL_EFFICIENCY, MAX_TIME_EFFICIENCY, RecipeError, RecipeResolver
from .report import render
from .sde_loader import SDEFileError


def _material_efficiency(value: str) -> int:
    try:
        me = int(value)
    except ValueError:
        raise argparse.ArgumentTypeError(f"invalid integer: {value!r}")
    if not 0 <= me <= MAX_MATERIAL_EFFICIENCY:
        raise argparse.ArgumentTypeError(
            f"must be an integer in [0,{MAX_MATERIAL_EFFICIENCY}], got {me}"
        )
    return me


def _time_efficiency(value: str) -> int:
    try:
        te = int(value)
    except ValueError:
        raise argparse.ArgumentTypeError(f"invalid integer: {value!r}")
    if not 0 <= te <= MAX_TIME_EFFICIENCY or te % 2:
        raise argparse.ArgumentTypeError(
            f"must be an even integer in [0,{MAX_TIME_EFFICIENCY}], got {te}"
        )
    return te


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="industry.py",
        description="Plan EVE Online industry builds from the Static Data Export.",
    )
    sub = parser.add_subparsers(dest="command", required=True)
    recipe = sub.add_parser("recipe", help="Show the recipe for a product or blueprint")
    recipe.add_argument("name", nargs="+", help="Exact typeName of a product or blueprint")
    recipe.add_argument("--sde", required=True, help="Path to the SDE directory")
    recipe.add_argument("--material-efficiency", "-me", dest="me", type=_material_efficiency,
                        default=0, metavar="ME",
                        help="Blueprint material efficiency, integer in [0,10] (default 0)")
    recipe.add_argument("--time-efficiency", "-te", dest="te", type=_time_efficiency,
                        default=0, metavar="TE",
                        help="Blueprint time efficiency, even integer in [0,20] (default 0)")
    recipe.add_argument("--display-waste", "-waste", dest="waste", action="store_true",
                        help="Show material wasted compared to ME 10")
    invention = sub.add_parser("invention", help="Plan invention / reverse engineering for a product")
    invention.add_argument("name", nargs="+", help="Exact typeName of a Tech II/III product or blueprint")
    invention.add_argument("--sde", required=True, help="Path to the SDE directory")
    invention.add_argument("--skill", type=int, default=5, choices=range(1, 6), metavar="{1-5}",
                           help="Level used for all relevant skills (default 5)")
    plan = sub.add_parser("plan", help="Create a build plan (jobs.csv, materials.csv) for an item")
    plan.add_argument("name", nargs="+", help="Build string, e.g. 'Barrage L 10 None x10'")
    plan.add_argument("--config", required=True, help="YAML build config file")
    plan.add_argument("--sde", required=True, help="Path to the SDE directory")
    plan.add_argument("--output", required=True, help="Directory to write the CSV files to")
    return parser


def run_recipe(name: str, sde_dir: Path, me: int = 0, te: int = 0, waste: bool = False) -> str:
    inventory = Inventory(sde_dir)
    published = {t.type_id for t in inventory.types.values() if t.published}
    industry = IndustryData(sde_dir, published)
    recipe = RecipeResolver(inventory, industry).resolve(name, me=me, te=te)
    return render(describe(inventory, recipe.product), recipe, show_waste=waste)


def run_invention(name: str, sde_dir: Path, skill: int) -> str:
    inventory = Inventory(sde_dir)
    published = {t.type_id for t in inventory.types.values() if t.published}
    industry = IndustryData(sde_dir, published)
    invention = InventionData(sde_dir, published)
    plan = InventionPlanner(inventory, industry, invention).plan(name, skill)
    return render_invention(describe(inventory, plan.product), plan)


def run_plan(build: str, config_path: Path, sde_dir: Path, output_dir: Path) -> None:
    config = load_config(config_path)
    inventory = Inventory(sde_dir)
    published = {t.type_id for t in inventory.types.values() if t.published}
    industry = IndustryData(sde_dir, published)
    invention = InventionData(sde_dir, published)
    planner = BuildPlanner(inventory, industry, invention)
    plan = planner.plan(planner.parse(build), config)
    write_plan(plan, inventory, output_dir)


def main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    name = " ".join(args.name)
    sde_dir = Path(args.sde)
    if not sde_dir.is_dir():
        print(f"Error: SDE directory not found: {sde_dir}", file=sys.stderr)
        return 2
    try:
        if args.command == "recipe":
            print(run_recipe(name, sde_dir, args.me, args.te, args.waste))
        elif args.command == "invention":
            print(run_invention(name, sde_dir, args.skill))
        elif args.command == "plan":
            run_plan(name, Path(args.config), sde_dir, Path(args.output))
        else:
            return 2
    except (RecipeError, InventionError, PlanError, SDEFileError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    return 0
