"""Shared behaviour for plugin and theme management commands."""

from ..errors import AppctlError
from ._listing import render_list

LIST_FIELDS = ["name", "status", "update", "version"]


class ExtensionCatalog:
    """A simulated collection of installed plugins or themes."""

    def __init__(self, noun, items):
        self.noun = noun
        self.items = items

    def find(self, name):
        return next((i for i in self.items if i["name"] == name), None)

    def targets(self, args, assoc):
        """Resolve the named items, or every item with ``--all``."""
        if assoc.get("all"):
            return [i["name"] for i in self.items]
        if not args:
            raise AppctlError(f"Please specify one or more {self.noun}s, or use --all.")
        return list(args)

    def each_installed(self, ctx, names):
        for name in names:
            if self.find(name) is None:
                ctx.output.warning(f"The '{name}' {self.noun} could not be found.")
            else:
                yield name

    # -- handlers -------------------------------------------------------

    def list(self, ctx, args, assoc):
        render_list(ctx, self.items, assoc, LIST_FIELDS, LIST_FIELDS + ["title"], id_field="name")

    def status(self, ctx, args, assoc):
        if args:
            item = self.find(args[0])
            if item is None:
                raise AppctlError(f"The '{args[0]}' {self.noun} could not be found.")
            ctx.output.line(f"{self.noun.capitalize()} {item['name']} details:")
            ctx.output.line(f"    Name: {item['title']}")
            ctx.output.line(f"    Status: {item['status'].capitalize()}")
            ctx.output.line(f"    Version: {item['version']}")
            return
        ctx.output.line(f"{len(self.items)} installed {self.noun}s:")
        for item in self.items:
            marker = "A" if item["status"] == "active" else "I"
            ctx.output.line(f"  {marker} {item['name']} {item['version']}")

    def install(self, ctx, args, assoc):
        for name in args:
            if self.find(name) and not assoc.get("force"):
                ctx.output.warning(f"{name}: {self.noun.capitalize()} already installed.")
                continue
            ctx.output.log(f"Installing {name} ({assoc['version']})...")
            if assoc.get("activate"):
                ctx.output.log(f"Activating '{name}'...")
        ctx.output.success(f"Installed {len(args)} of {len(args)} {self.noun}s.")

    def delete(self, ctx, args, assoc):
        names = self.targets(args, assoc)
        deleted = list(self.each_installed(ctx, names))
        for name in deleted:
            ctx.output.log(f"Deleted '{name}' {self.noun}.")
        self.summary(ctx, "Deleted", len(deleted), len(names))

    def update(self, ctx, args, assoc):
        names = self.targets(args, assoc)
        found = list(self.each_installed(ctx, names))
        if assoc.get("dry-run"):
            ctx.output.log(f"Available {self.noun} updates: {', '.join(found) or 'none'}")
            return
        self.summary(ctx, "Updated", len(found), len(names))

    def summary(self, ctx, verb, done, total):
        if done == total:
            ctx.output.success(f"{verb} {done} of {total} {self.noun}s.")
        else:
            raise AppctlError(f"Only {verb.lower()} {done} of {total} {self.noun}s.")
