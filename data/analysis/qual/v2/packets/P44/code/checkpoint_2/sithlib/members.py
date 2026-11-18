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
    unique,
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
        self._attribute_cache = {}

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
        """The (first) value of attribute `name` of `value`, or None."""
        values = self.member_values(value, name)
        return values[0] if values else None

    def member_values(self, value, name):
        """Every value attribute `name` of `value` may have."""
        inferrer = self.inferrer
        importer = inferrer.importer
        if isinstance(value, LocalModule):
            root = value.context.root
            if inferrer.binds(root, name):
                return inferrer.scope_values(root, name)
            submodule = importer.local_submodule(value, name)
            return [submodule] if submodule is not None else []
        if isinstance(value, LocalClass):
            for cls in self.mro(value):
                if name in cls.scope.bindings:
                    values = []
                    for member in inferrer.scope_values(cls.scope, name):
                        values += self._bind_member(member, cls, value, None)
                    return unique(values)
            return self._runtime_base_member(value, name)
        if isinstance(value, LocalInstance):
            for cls in self.mro(value.cls):
                attributes = self.instance_attribute_bindings(cls).get(name, [])
                if not attributes and name not in cls.scope.bindings:
                    continue
                values = []
                for binding in attributes:
                    values += self.instance_attribute_values(binding, value)
                if name in cls.scope.bindings:
                    for member in inferrer.scope_values(cls.scope, name):
                        values += self._bind_member(member, cls, value.cls, value)
                return unique(values)
            return self._runtime_base_member(value.cls, name)
        entry = self.all(value).get(name)
        if entry is not None:
            member = entry.value()
            return [member] if member is not None else []
        if isinstance(value, RuntimeModule):
            submodule = importer.runtime_submodule(value, name)
            return [submodule] if submodule is not None else []
        return []

    def member_definitions(self, value, name):
        """Where attribute `name` of `value` is defined: bindings, or values for runtime objects."""
        inferrer = self.inferrer
        if isinstance(value, LocalModule):
            root = value.context.root
            if inferrer.binds(root, name):
                return [fact.binding for fact in inferrer.scope_facts(root, name)]
            return self.member_values(value, name)
        if isinstance(value, (LocalClass, LocalInstance)):
            cls_value = value if isinstance(value, LocalClass) else value.cls
            for cls in self.mro(cls_value):
                found = []
                if isinstance(value, LocalInstance):
                    found += self.instance_attribute_bindings(cls).get(name, [])
                if name in cls.scope.bindings:
                    found += [_property_getter(cls.scope, fact.binding)
                              for fact in inferrer.scope_facts(cls.scope, name)]
                if found:
                    return found
        return self.member_values(value, name)

    def instance_attribute_values(self, binding, instance):
        """Values of a `self.attr = ...` binding for a particular instance."""
        method = binding.scope
        if not instance.init_args or method.node.name != "__init__":
            return self.inferrer.binding_values(binding)
        return self.inferrer.in_frame(method, instance.init_args, instance,
                                      lambda: self.inferrer.binding_values(binding))

    def _bind_member(self, member, owner, cls, instance):
        """The value of a class-body member accessed on a class (`instance` None) or instance."""
        if not isinstance(member, LocalFunction) or member.bound is not None:
            return [member]
        node = member.node
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) or member.scope.parent is not owner.scope:
            return [member]
        decorators = {_decorator_name(d) for d in node.decorator_list}
        if "staticmethod" in decorators:
            return [member]
        if "classmethod" in decorators:
            return [LocalFunction(member.scope, cls)]
        if instance is None:
            return [member]
        if decorators & {"setter", "deleter"}:
            binding = owner.scope.module.binding_of(node)
            getter = _property_getter(owner.scope, binding) if binding is not None else None
            if getter is not None and getter is not binding:
                scope = owner.scope.module.scope_of(getter.node)
                if scope is not None:
                    member, decorators = LocalFunction(scope), {"property"}
        if decorators & {"property", "cached_property"}:
            return self.inferrer.return_values(LocalFunction(member.scope, instance))
        return [LocalFunction(member.scope, instance)]

    def find_method(self, cls, name):
        """The (unbound) local function `name` defined in the MRO of `cls`, or None."""
        for current in self.mro(cls):
            for binding in reversed(current.scope.bindings.get(name, [])):
                if binding.kind == "def":
                    scope = current.scope.module.scope_of(binding.node)
                    if scope is not None:
                        return LocalFunction(scope)
            if name in current.scope.bindings:
                return None
        return None

    def runtime_bases(self, cls):
        """The runtime (installed or builtin) classes among the direct bases of `cls`."""
        bases = []
        for base in cls.node.bases:
            bases += [v for v in self.inferrer.infer_values(base, cls.scope.parent)
                      if isinstance(v, RuntimeClass)]
        return bases

    def _runtime_base_member(self, cls, name):
        for current in self.mro(cls):
            for base in self.runtime_bases(current):
                if base.obj is not object and hasattr(base.obj, name):
                    member = wrap_runtime(getattr(base.obj, name))
                    return [member] if member is not None else []
        return []

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
                for value in self.inferrer.infer_values(base, current.scope.parent):
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
            for name, bindings in self.instance_attribute_bindings(current).items():
                members[name] = BindingEntry(bindings[0], self.inferrer)
        return members

    def instance_attribute_bindings(self, cls):
        """{name: bindings} for `self.<name> = ...` assignments in the methods of `cls`.

        Assignments in `__init__` come first.
        """
        key = id(cls.scope)
        if key in self._attribute_cache:
            return self._attribute_cache[key]
        entries = {}
        methods = []
        for bindings in cls.scope.bindings.values():
            methods += [b.node for b in bindings if b.kind == "def"]
        methods.sort(key=lambda node: (node.name != "__init__", node.lineno))
        for method in methods:
            decorators = {_decorator_name(d) for d in method.decorator_list}
            method_scope = cls.scope.module.scope_of(method)
            positional = method.args.posonlyargs + method.args.args
            if method_scope is None or not positional or decorators & {"staticmethod", "classmethod"}:
                continue
            self._collect_attributes(method, method_scope, positional[0].arg, cls, entries)
        self._attribute_cache[key] = entries
        return entries

    def _collect_attributes(self, method, method_scope, self_name, cls, entries):
        for node in walk_local(method.body):
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    for attribute, target_node, value in _self_attributes(target, node.value, self_name):
                        binding = Binding(attribute, target_node.lineno, "assign", node, method_scope,
                                          value, {"owner": cls.scope}, target_node)
                        entries.setdefault(attribute, []).append(binding)
            elif isinstance(node, (ast.AnnAssign, ast.AugAssign)):
                for attribute, target_node, _ in _self_attributes(node.target, None, self_name):
                    if isinstance(node, ast.AugAssign) and attribute in entries:
                        continue
                    kind = "assign" if isinstance(node, ast.AnnAssign) else "augassign"
                    value = node.value if isinstance(node, ast.AnnAssign) else None
                    extra = {"owner": cls.scope}
                    if isinstance(node, ast.AnnAssign):
                        extra["annotation"] = node.annotation
                    binding = Binding(attribute, target_node.lineno, kind, node, method_scope, value,
                                      extra, target_node)
                    entries.setdefault(attribute, []).append(binding)


def _property_getter(class_scope, binding):
    """For the `@<name>.setter`/`.deleter` def `binding`, the `@property` getter; else `binding`."""
    if binding.kind != "def":
        return binding
    if not {_decorator_name(d) for d in binding.node.decorator_list} & {"setter", "deleter"}:
        return binding
    for candidate in class_scope.bindings.get(binding.name, []):
        if candidate.kind == "def" and "property" in {
                _decorator_name(d) for d in candidate.node.decorator_list}:
            return candidate
    return binding


def _decorator_name(node):
    if isinstance(node, ast.Call):
        node = node.func
    if isinstance(node, ast.Attribute):
        return node.attr
    if isinstance(node, ast.Name):
        return node.id
    return None


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
