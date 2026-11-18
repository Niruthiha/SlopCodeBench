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
        """Every attribute entry of `value`, keyed by name (submodules included)."""
        if isinstance(value, (LocalModule, RuntimeModule)):
            entries = dict(self.namespace(value))
            for name in self.inferrer.importer.submodule_names(value):
                if name not in entries:
                    entries[name] = ValueEntry(lambda name=name: self.member(value, name))
            return entries
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

    def namespace(self, value):
        """The names a module binds itself (no submodules that it does not import).

        Names only declared by the module's stub are included.
        """
        if isinstance(value, LocalModule):
            root = value.context.root
            return self._with_stub_entries(self.inferrer.scope_entries(root), root)
        if isinstance(value, RuntimeModule):
            return runtime_entries(value.obj)
        return self.all(value)

    def public(self, value):
        return {name: entry for name, entry in self.all(value).items() if is_public(name)}

    def dunder_all(self, value):
        """The names listed in a module's `__all__`, or None when it has none."""
        if isinstance(value, LocalModule):
            return static_all(value.context.tree)
        if isinstance(value, RuntimeModule):
            names = getattr(value.obj, "__all__", None)
            if isinstance(names, (list, tuple)) and all(isinstance(n, str) for n in names):
                return list(names)
        return None

    def exported(self, value, submodules=False):
        """Names a module exports: its `__all__`, else every name not starting with `_`.

        Without `submodules`, only names the module binds itself count (as
        for `from module import *`).
        """
        names = self.dunder_all(value)
        entries = self.all(value) if submodules else self.namespace(value)
        if names is None:
            return {name: entry for name, entry in entries.items() if is_public(name)}
        return {name: entries.get(name) or ValueEntry(lambda name=name: self.member(value, name))
                for name in names}

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
            stub = inferrer.stubs.stub_scope(root)
            if stub is not None and inferrer.binds(stub, name):
                return unique(inferrer.from_stub(inferrer.scope_values(stub, name)))
            submodule = importer.local_submodule(value, name)
            return [submodule] if submodule is not None else []
        if isinstance(value, LocalClass):
            for cls in self.mro(value):
                if name in cls.scope.bindings:
                    values = []
                    for member in inferrer.scope_values(cls.scope, name):
                        values += self._bind_member(member, cls, value, None)
                    return unique(values)
            stubbed = self._stub_member(value, name, None)
            if stubbed is not None:
                return stubbed
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
            stubbed = self._stub_member(value.cls, name, value)
            if stubbed is not None:
                return stubbed
            return self._runtime_base_member(value.cls, name)
        entry = self.namespace(value).get(name)
        if entry is not None:
            member = entry.value()
            return [member] if member is not None else []
        if isinstance(value, RuntimeModule):
            submodule = importer.runtime_submodule(value, name)
            return [submodule] if submodule is not None else []
        return []

    def member_definitions(self, value, name):
        """Where attribute `name` of `value` is defined: bindings, or values for runtime objects.

        Source definitions win; stub definitions are used for names only a stub declares.
        """
        inferrer = self.inferrer
        if isinstance(value, LocalModule):
            root = value.context.root
            if inferrer.binds(root, name):
                return [fact.binding for fact in inferrer.scope_facts(root, name)]
            stub = inferrer.stubs.stub_scope(root)
            if stub is not None and inferrer.binds(stub, name):
                return [fact.binding for fact in inferrer.scope_facts(stub, name)]
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
            for cls in self.mro(cls_value):
                stub = inferrer.stubs.stub_scope(cls.scope)
                if stub is not None and name in stub.bindings:
                    return [fact.binding for fact in inferrer.scope_facts(stub, name)]
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

    def _stub_member(self, cls, name, instance):
        """Values of a member only declared by the stub of a class in the MRO of `cls` (or None)."""
        inferrer = self.inferrer
        for current in self.mro(cls):
            stub = inferrer.stubs.stub_scope(current.scope)
            if stub is None or name not in stub.bindings:
                continue
            owner = LocalClass(stub)
            values = []
            for member in inferrer.scope_values(stub, name):
                values += self._bind_member(member, owner, cls, instance)
            return unique(inferrer.from_stub(values))
        return None

    def _with_stub_entries(self, entries, scope):
        """`entries` plus the names declared only in the stub of `scope` (stub imports excluded)."""
        stub = self.inferrer.stubs.stub_scope(scope)
        if stub is None:
            return entries
        entries = dict(entries)
        for name, entry in self.inferrer.scope_entries(stub).items():
            binding = getattr(entry, "binding", None)
            if binding is None or binding.kind in ("import", "importfrom"):
                continue
            entries.setdefault(name, entry)
        return entries

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
            members.update(self._with_stub_entries(self.inferrer.scope_entries(current.scope),
                                                   current.scope))
        return members

    def instance_members(self, cls):
        mro = self.mro(cls)
        members = {}
        for current in reversed(mro):
            members.update(self._with_stub_entries(self.inferrer.scope_entries(current.scope),
                                                   current.scope))
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


def static_all(tree):
    """The strings a module's top-level code puts in `__all__`, or None if it never assigns it."""
    state = {"names": None}

    def strings(node):
        if isinstance(node, (ast.List, ast.Tuple, ast.Set)):
            return [e.value for e in node.elts
                    if isinstance(e, ast.Constant) and isinstance(e.value, str)]
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
            return strings(node.left) + strings(node.right)
        return []

    def visit(statements):
        for node in statements:
            if isinstance(node, (ast.Assign, ast.AnnAssign)):
                targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                if any(isinstance(t, ast.Name) and t.id == "__all__" for t in targets):
                    state["names"] = strings(node.value) if node.value is not None else []
            elif isinstance(node, ast.AugAssign):
                if isinstance(node.target, ast.Name) and node.target.id == "__all__":
                    state["names"] = (state["names"] or []) + strings(node.value)
            elif isinstance(node, ast.Expr) and isinstance(node.value, ast.Call):
                call = node.value
                func = call.func
                if (isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name)
                        and func.value.id == "__all__" and len(call.args) == 1
                        and state["names"] is not None):
                    argument = call.args[0]
                    if func.attr == "extend":
                        state["names"] = state["names"] + strings(argument)
                    elif func.attr in ("append", "remove") and isinstance(argument, ast.Constant) \
                            and isinstance(argument.value, str):
                        if func.attr == "append":
                            state["names"] = state["names"] + [argument.value]
                        elif argument.value in state["names"]:
                            state["names"] = [n for n in state["names"] if n != argument.value]
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                continue
            else:
                for field in ("body", "orelse", "finalbody"):
                    visit(getattr(node, field, None) or [])
                for handler in getattr(node, "handlers", None) or []:
                    visit(handler.body)

    visit(tree.body)
    names = state["names"]
    if names is None:
        return None
    return list(dict.fromkeys(names))


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
