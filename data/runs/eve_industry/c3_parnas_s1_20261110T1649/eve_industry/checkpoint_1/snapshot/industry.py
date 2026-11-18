"""EVE Online industry planner CLI.

Usage: python industry.py recipe <Product or Blueprint name> --sde <SDE directory>

This module only parses arguments and wires the other modules together.
"""

import argparse
import sys

import blueprints
import catalog
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


def main(argv=None):
    parser = argparse.ArgumentParser(description="EVE Online industry planner")
    commands = parser.add_subparsers(dest="command", required=True)
    recipe = commands.add_parser("recipe", help="show the recipe for a product or blueprint")
    recipe.add_argument("name", nargs="+", help="exact product or blueprint typeName")
    recipe.add_argument("--sde", required=True, help="SDE directory")
    args = parser.parse_args(argv)

    try:
        text = _build_report(" ".join(args.name), args.sde)
    except (LookupError, OSError) as exc:
        print("error: %s" % exc, file=sys.stderr)
        return 1
    print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
