"""``appctl db``: basic database operations (simulated)."""

from ._listing import confirm

DATABASE = "appctl"
TABLES = ["app_comments", "app_options", "app_posts", "app_sites", "app_users"]


def create(ctx, args, assoc):
    ctx.output.success("Database created.")


def drop(ctx, args, assoc):
    if not confirm(ctx, assoc, f"Are you sure you want to drop the '{DATABASE}' database?"):
        return
    ctx.output.success(f"Database '{DATABASE}' dropped.")


def reset(ctx, args, assoc):
    if not confirm(ctx, assoc, f"Are you sure you want to reset the '{DATABASE}' database?"):
        return
    ctx.output.success(f"Database '{DATABASE}' reset.")


def export(ctx, args, assoc):
    tables = assoc.get("tables")
    scope = f" (tables: {tables})" if tables and tables is not True else ""
    if assoc.get("porcelain"):
        ctx.output.line(args[0])
        return
    ctx.output.success(f"Exported to '{args[0]}'{scope}.")


def import_(ctx, args, assoc):
    ctx.output.success(f"Imported from '{args[0]}'.")


def query(ctx, args, assoc):
    sql = args[0] if args else ""
    ctx.output.success(f"Executed query: {sql}" if sql else "Opened an interactive query session.")


def tables(ctx, args, assoc):
    wanted = [t for t in TABLES if not args or t in args]
    if assoc["format"] == "csv":
        ctx.output.line(",".join(wanted))
    else:
        for name in wanted:
            ctx.output.line(name)


def check(ctx, args, assoc):
    ctx.output.success("Database checked.")


def register(registry):
    registry.add("db", description="Performs basic database operations.")
    registry.add("db check", check, description="Checks the current status of the database.")
    registry.add("db create", create, description="Creates a new database.")
    registry.add(
        "db drop", drop, synopsis="[--yes]", description="Deletes the existing database.",
        options={"yes": "Answer yes to the confirmation message."},
    )
    registry.add(
        "db export", export,
        synopsis="[<file>] [--tables=<tables>] [--porcelain]",
        description="Exports the database to a file.",
        defaults={"file": f"{DATABASE}.sql"},
        options={"file": "The name of the SQL file to export.",
                 "tables": "The comma separated list of specific tables to export.",
                 "porcelain": "Output filename for the exported database."},
    )
    registry.add(
        "db import", import_,
        synopsis="[<file>]",
        description="Imports a database from a file.",
        defaults={"file": f"{DATABASE}.sql"},
        options={"file": "The name of the SQL file to import."},
    )
    registry.add(
        "db query", query,
        synopsis="[<sql>]",
        description="Executes a SQL query against the database.",
        alias="sql",
        options={"sql": "A SQL query."},
    )
    registry.add(
        "db reset", reset, synopsis="[--yes]",
        description="Removes all tables from the database.",
        options={"yes": "Answer yes to the confirmation message."},
    )
    registry.add(
        "db tables", tables,
        synopsis="[<table>...] [--format=<format>]",
        description="Lists the database tables.",
        defaults={"format": "list"},
        options={"table": "List tables based on wildcard search.",
                 "format": "Render output in a particular format (list, csv)."},
    )
