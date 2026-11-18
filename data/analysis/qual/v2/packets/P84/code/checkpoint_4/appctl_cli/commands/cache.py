"""``appctl cache``: object cache management (simulated)."""

from ..errors import AppctlError


def add(ctx, args, assoc):
    key, value, group, expiration = args
    ctx.output.success(
        f"Added object '{key}' in group '{group}' (expires in {expiration} seconds)."
    )


def delete(ctx, args, assoc):
    key, group = args
    ctx.output.success(f"Object '{key}' deleted from group '{group}'.")


def get(ctx, args, assoc):
    key, group = args
    raise AppctlError(f"Object with key '{key}' and group '{group}' not found.")


def flush(ctx, args, assoc):
    ctx.output.success("The cache was flushed.")


def cache_type(ctx, args, assoc):
    ctx.output.line("Default")


def register(registry):
    registry.add("cache", description="Adds, removes, fetches, and flushes the object cache.")
    registry.add(
        "cache add", add,
        synopsis="<key> <value> [<group>] [<expiration>]",
        description="Adds a value to the object cache.",
        defaults={"group": "default", "expiration": "0"},
        options={"key": "Cache key.", "value": "Value to add.", "group": "Method for grouping data.",
                 "expiration": "Define how long to keep the value, in seconds."},
    )
    registry.add(
        "cache delete", delete,
        synopsis="<key> [<group>]",
        description="Removes a value from the object cache.",
        defaults={"group": "default"},
    )
    registry.add("cache flush", flush, description="Flushes the object cache.")
    registry.add(
        "cache get", get,
        synopsis="<key> [<group>]",
        description="Gets a value from the object cache.",
        defaults={"group": "default"},
    )
    registry.add("cache type", cache_type, description="Attempts to determine which object cache is being used.")
