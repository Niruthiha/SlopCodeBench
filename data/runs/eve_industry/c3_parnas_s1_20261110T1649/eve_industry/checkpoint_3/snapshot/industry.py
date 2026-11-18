"""EVE Online industry planner CLI.

Usage:
  python industry.py recipe <Product or Blueprint name> --sde <SDE directory>
      [-me <0-10>] [-te <0-20, even>] [-waste]
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


def _build_report(name, sde_dir, me=0, te=0, show_waste=False):
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
    if not blueprints.material_efficiency_applies(recipe.activity):
        me = 0
    materials = []
    for mid, qty in recipe.materials:
        needed = blueprints.material_amount(qty, me)
        waste = blueprints.material_amount(qty, 0) - needed
        name_text = items.name(mid) if items.is_valid(mid) else str(mid)
        materials.append((name_text, needed, industry.is_buildable(mid), waste))
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
            seconds=blueprints.job_seconds(recipe.seconds, te),
            materials=tuple(materials),
            show_waste=show_waste,
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


def _efficiency(low, high, step, label):
    def parse(text):
        try:
            value = int(text)
        except ValueError:
            raise argparse.ArgumentTypeError("%s must be an integer" % label)
        if not low <= value <= high or value % step:
            kind = "an even integer" if step == 2 else "an integer"
            raise argparse.ArgumentTypeError(
                "%s must be %s in [%d,%d], got %r" % (label, kind, low, high, text)
            )
        return value
    return parse


def main(argv=None):
    parser = argparse.ArgumentParser(description="EVE Online industry planner")
    commands = parser.add_subparsers(dest="command", required=True)
    recipe = commands.add_parser("recipe", help="show the recipe for a product or blueprint")
    recipe.add_argument("name", nargs="+", help="exact product or blueprint typeName")
    recipe.add_argument("--sde", required=True, help="SDE directory")
    recipe.add_argument("--material-efficiency", "-me", dest="me", default=0, metavar="ME",
                        type=_efficiency(0, 10, 1, "material efficiency"),
                        help="material efficiency, integer in [0,10] (default 0)")
    recipe.add_argument("--time-efficiency", "-te", dest="te", default=0, metavar="TE",
                        type=_efficiency(0, 20, 2, "time efficiency"),
                        help="time efficiency, even integer in [0,20] (default 0)")
    recipe.add_argument("--display-waste", "-waste", dest="waste", action="store_true",
                        help="show materials wasted because ME is below 10")
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
            text = _build_report(" ".join(args.name), args.sde, args.me, args.te, args.waste)
    except (LookupError, OSError) as exc:
        print("error: %s" % exc, file=sys.stderr)
        return 1
    print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
