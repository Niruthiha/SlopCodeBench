"""EVE Online industry planner CLI.

Usage:
  python industry.py recipe <Product or Blueprint name> --sde <SDE directory>
  python industry.py invention <Product or Blueprint name> --sde <SDE directory> [--skill <1-5>]

This module only parses arguments and wires the other modules together.
"""

import argparse
import sys

import blueprints
import catalog
import invention
import invention_report
import report
import volumes


def _build_report(name, sde_dir):
    items = catalog.Catalog(sde_dir)
    industry = blueprints.Industry(sde_dir, items)
    volume_of = volumes.VolumeResolver(sde_dir, items)

    candidates = items.ids_named(name)
    if not candidates:
        raise LookupError("No published item named %r" % name)
    recipe = next(
        (r for r in (industry.recipe_for(t) for t in candidates) if r is not None), None
    )
    if recipe is None:
        raise LookupError("%r cannot be manufactured or reacted" % name)

    product = recipe.product_id
    volume, packaged = volume_of.volume(product)
    materials = tuple(
        (items.name(mid) if items.is_valid(mid) else str(mid), qty, industry.is_buildable(mid))
        for mid, qty in recipe.materials
    )
    return report.render(
        report.ReportInput(
            item_name=items.name(product),
            type_id=product,
            category=items.category_name(product),
            group=items.group_name(product),
            market_path=tuple(items.market_path(product)),
            tech_level=items.tech_level(product),
            volume=volume,
            volume_is_packaged=packaged,
            activity=recipe.activity,
            output_quantity=recipe.output_quantity,
            seconds=recipe.seconds,
            materials=materials,
        )
    )


def _build_invention_report(name, sde_dir, skill_level):
    items = catalog.Catalog(sde_dir)
    planner = invention.Invention(sde_dir, items)

    candidates = items.ids_named(name)
    if not candidates:
        raise LookupError("No published item named %r" % name)
    plan = next(
        (p for p in (planner.plan(t, skill_level) for t in candidates) if p is not None), None
    )
    if plan is None:
        raise LookupError("%r cannot be invented or reverse engineered" % name)

    product = plan.product_id
    tech_level = items.tech_level(product)
    if tech_level not in ("Tech II", "Tech III"):
        tech_level = "Tech III" if plan.from_relics else "Tech II"
    return invention_report.render(
        invention_report.InventionReportInput(
            item_name=items.name(product),
            type_id=product,
            category=items.category_name(product),
            group=items.group_name(product),
            market_path=tuple(items.market_path(product)),
            tech_level=tech_level,
            base_blueprint=plan.base_blueprint,
            datacores=plan.datacores,
            quantity_per_run=plan.quantity_per_run,
            skills=plan.skills,
            seconds=plan.seconds,
            with_source=plan.from_relics,
            rows=tuple(
                (o.invented_from, o.decryptor, o.probability, o.runs, o.me, o.te)
                for o in plan.outcomes
            ),
        )
    )


def main(argv=None):
    parser = argparse.ArgumentParser(description="EVE Online industry planner")
    commands = parser.add_subparsers(dest="command", required=True)
    recipe = commands.add_parser("recipe", help="show the recipe for a product or blueprint")
    recipe.add_argument("name", nargs="+", help="exact product or blueprint typeName")
    recipe.add_argument("--sde", required=True, help="SDE directory")
    invent = commands.add_parser("invention", help="plan invention for a Tech II/III product")
    invent.add_argument("name", nargs="+", help="exact product or blueprint typeName")
    invent.add_argument("--sde", required=True, help="SDE directory")
    invent.add_argument("--skill", type=int, default=5, choices=range(1, 6), metavar="{1-5}",
                        help="level of every relevant skill (default 5)")
    args = parser.parse_args(argv)

    try:
        if args.command == "invention":
            text = _build_invention_report(" ".join(args.name), args.sde, args.skill)
        else:
            text = _build_report(" ".join(args.name), args.sde)
    except (LookupError, OSError) as exc:
        print("error: %s" % exc, file=sys.stderr)
        return 1
    print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
