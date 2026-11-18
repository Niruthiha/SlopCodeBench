"""Attribute resolution: the members exposed by each kind of value."""
import ast

from .entries import BindingEntry, ValueEntry
from .scopes import Binding, walk_local
from .values import (
    LocalClass,
    LocalFunction,
    LocalInstance,
    LocalModule,
    RuntimeClass,
    RuntimeFunction,
    RuntimeInstance,
    RuntimeModule,
    runtime_sample,
    wrap_runtime,
)


def _sample_function():
    """Stand-in used to list the attributes of locally defined functions."""


def runtime_entries(obj):
    """Entries for `dir(obj)`, each resolving the attribute lazily."""
    try:
        names = dir(obj)
    except Exception:
        return {}
    return {name: ValueEntry(lambda name=name: wrap_runtime(getattr(obj, name))) for name in names}


def is_public(name):
    return not name.startswith("_")


class MemberResolver:
    def __init__(self, inferrer):
        self.inferrer = inferrer

    def all(self, value):
        """Every attribute entry of `value`, keyed by name."""
        if isinstance(value, LocalModule):
            return self.inferrer.scope_entries(value.context.root)
        if isinstance(value, RuntimeModule):
            return runtime_entries(value.obj)
        if isinstance(value, LocalClass):
            return self.class_members(value)
        if isinstance(value, LocalInstance):
            return self.instance_members(value.cls)
        if isinstance(value, (RuntimeClass, RuntimeFunction)):
            return runtime_entries(value.obj)
        if isinstance(value, RuntimeInstance):
            return runtime_entries(runtime_sample(value.cls))
        if isinstance(value, LocalFunction):
            return runtime_entries(_sample_function)
        return {}

    def public(self, value):
        return {name: entry for name, entry in self.all(value).items() if is_public(name)}

    def member(self, value, name):
        """The value of attribute `name` of `value`, or None."""
        entry = self.all(value).get(name)
        if entry is not None:
            return entry.value()
        importer = self.inferrer.importer
        if isinstance(value, LocalModule):
            return importer.local_submodule(value, name)
        if isinstance(value, RuntimeModule):
            return importer.runtime_submodule(value, name)
        return None

    # -- classes -----------------------------------------------------------

    def mro(self, cls):
        """The class followed by its locally defined bases (depth first)."""
        order = []

        def visit(current):
            if any(current.scope is seen.scope for seen in order):
                return
            order.append(current)
            node = current.node
            for base in node.bases:
                value = self.inferrer.infer(base, current.scope.parent, node.lineno)
                if isinstance(value, LocalClass):
                    visit(value)

        visit(cls)
        return order

    def class_members(self, cls):
        members = {}
        for current in reversed(self.mro(cls)):
            members.update(self.inferrer.scope_entries(current.scope))
        return members

    def instance_members(self, cls):
        mro = self.mro(cls)
        members = {}
        for current in reversed(mro):
            members.update(self.inferrer.scope_entries(current.scope))
        for current in reversed(mro):
            members.update(self.init_attributes(current))
        return members

    def init_attributes(self, cls):
        """Entries for `self.<name> = ...` assignments in the class's `__init__`."""
        init = None
        for binding in cls.scope.bindings.get("__init__", []):
            if binding.kind == "def":
                init = binding.node
        if init is None:
            return {}
        init_scope = cls.scope.module.scope_of(init)
        positional = init.args.posonlyargs + init.args.args
        if init_scope is None or not positional:
            return {}
        self_name = positional[0].arg
        entries = {}
        for node in walk_local(init.body):
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    for attribute, target_node, value in _self_attributes(target, node.value, self_name):
                        binding = Binding(attribute, target_node.lineno, "assign", node, init_scope, value)
                        entries[attribute] = BindingEntry(binding, self.inferrer)
            elif isinstance(node, (ast.AnnAssign, ast.AugAssign)):
                for attribute, target_node, _ in _self_attributes(node.target, None, self_name):
                    if isinstance(node, ast.AugAssign) and attribute in entries:
                        continue
                    kind = "assign" if isinstance(node, ast.AnnAssign) else "augassign"
                    value = node.value if isinstance(node, ast.AnnAssign) else None
                    extra = {"annotation": node.annotation} if isinstance(node, ast.AnnAssign) else {}
                    binding = Binding(attribute, target_node.lineno, kind, node, init_scope, value, extra)
                    entries[attribute] = BindingEntry(binding, self.inferrer)
        return entries


def _self_attributes(target, value, self_name):
    """Yield (attribute name, target node, value) for `self.attr` targets."""
    if isinstance(target, ast.Attribute):
        if isinstance(target.value, ast.Name) and target.value.id == self_name:
            yield target.attr, target, value
    elif isinstance(target, (ast.Tuple, ast.List)):
        values = None
        if isinstance(value, (ast.Tuple, ast.List)) and len(value.elts) == len(target.elts):
            values = value.elts
        for index, element in enumerate(target.elts):
            yield from _self_attributes(element, values[index] if values else None, self_name)
    elif isinstance(target, ast.Starred):
        yield from _self_attributes(target.value, None, self_name)
