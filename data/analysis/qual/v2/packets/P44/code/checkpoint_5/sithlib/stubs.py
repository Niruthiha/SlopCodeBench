"""Pairing `.pyi` stubs with the source modules they describe.

Inference keeps working on source scopes (so that `goto` and `infer` report
`.py` locations); the stub index finds the stub scope declaring the types of a
source module, class or function, and maps stub scopes back to their source.
"""
from .scopes import CLASS, FUNCTION, MODULE

_KINDS = {CLASS: "class", FUNCTION: "def"}


def decorator_names(node):
    names = set()
    for decorator in getattr(node, "decorator_list", []):
        target = getattr(decorator, "func", decorator)
        names.add(getattr(target, "attr", None) or getattr(target, "id", None))
    return names


def declared_overloads(bindings):
    """The `@overload` variants among `def` bindings of one name, else the last definition."""
    defs = [b for b in bindings if b.kind == "def"]
    overloads = [b for b in defs if "overload" in decorator_names(b.node)]
    return overloads or defs[-1:]


class StubIndex:
    def __init__(self, importer):
        self.importer = importer
        self._to_stub = {}
        self._to_source = {}

    def stub_scope(self, scope):
        """The stub scope declaring source module/class/function `scope`, or None."""
        key = id(scope)
        if key not in self._to_stub:
            self._to_stub[key] = None
            if not scope.module.is_stub:
                self._to_stub[key] = _counterpart(scope, self.importer.stub_for, self.stub_scope)
        return self._to_stub[key]

    def source_scope(self, scope):
        """The source scope a stub module/class/function `scope` describes, or None."""
        key = id(scope)
        if key not in self._to_source:
            self._to_source[key] = None
            if scope.module.is_stub:
                self._to_source[key] = _counterpart(scope, self.importer.source_for,
                                                    self.source_scope)
        return self._to_source[key]

    def bindings(self, scope, name):
        """Stub bindings of `name` in the stub counterpart of source `scope`."""
        stub = self.stub_scope(scope)
        return stub.bindings.get(name, []) if stub is not None else []

    def function_scopes(self, scope):
        """Stub function scopes declaring source function `scope` (several for overloads)."""
        if scope.kind != FUNCTION or scope.parent is None:
            return []
        stub_parent = self.stub_scope(scope.parent)
        if stub_parent is None:
            return []
        declared = declared_overloads(stub_parent.bindings.get(scope.node.name, []))
        scopes = [stub_parent.module.scope_of(b.node) for b in declared]
        return [s for s in scopes if s is not None]


def _counterpart(scope, module_lookup, parent_lookup):
    if scope.kind == MODULE:
        context = module_lookup(scope.module)
        return context.root if context is not None else None
    kind = _KINDS.get(scope.kind)
    if kind is None or scope.parent is None:
        return None
    parent = parent_lookup(scope.parent)
    if parent is None:
        return None
    candidates = [b for b in parent.bindings.get(scope.node.name, []) if b.kind == kind]
    if not candidates:
        return None
    return parent.module.scope_of(candidates[-1].node)
