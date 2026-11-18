"""Resolution of schema blocks: inheritance, type overrides and calculated-field order."""
import copy

from . import dtypes
from .ast_nodes import ColumnRef
from .errors import DSLSyntaxError, TypeCheckError
from .typecheck import walk


class ResolvedField:
    """A schema field after inheritance; `visible` are the names its expression may use."""

    def __init__(self, name, field_type, expr, line, visible):
        self.name = name
        self.type = field_type
        self.expr = expr
        self.line = line
        self.visible = visible

    @property
    def is_calculated(self):
        return self.expr is not None


class ResolvedSchema:
    def __init__(self, name, fields):
        self.name = name
        self.fields = fields  # name -> ResolvedField, in declaration order
        self.calc_order = _calc_order(name, fields)

    @property
    def types(self):
        return {name: f.type for name, f in self.fields.items()}

    @property
    def physical(self):
        return {name: f.type for name, f in self.fields.items() if not f.is_calculated}


def override_allowed(old, new):
    """Same type, or numeric widening int -> float."""
    return old == new or (old == dtypes.INT and new == dtypes.FLOAT)


def resolve_all(decls):
    """Resolve every schema declaration; returns name -> ResolvedSchema."""
    resolved = {}
    for name in decls:
        _resolve(name, decls, resolved, [])
    return resolved


def _resolve(name, decls, resolved, stack):
    if name in resolved:
        return resolved[name]
    if name in stack:
        chain = " -> ".join(stack[stack.index(name):] + [name])
        raise DSLSyntaxError(f"circular schema inheritance: {chain}")
    decl = decls[name]
    fields = {}
    if decl.base is not None:
        if decl.base not in decls:
            raise DSLSyntaxError(f"line {decl.line}: schema '{name}' extends unknown "
                                 f"schema '{decl.base}'")
        base = _resolve(decl.base, decls, resolved, stack + [name])
        for fname, f in base.fields.items():
            fields[fname] = ResolvedField(f.name, f.type, copy.deepcopy(f.expr), f.line, f.visible)

    visible = set(fields)
    for f in decl.fields:
        if f.expr is not None:
            _check_references(f, visible, name)
        inherited = fields.get(f.name)
        if inherited is not None and not override_allowed(inherited.type, f.type):
            raise TypeCheckError(f"line {f.line}: schema '{name}' cannot override field "
                                 f"'{f.name}' from {inherited.type} to {f.type}")
        fields[f.name] = ResolvedField(f.name, f.type, f.expr, f.line, frozenset(visible))
        visible.add(f.name)

    result = ResolvedSchema(name, fields)
    resolved[name] = result
    return result


def _check_references(field, visible, schema_name):
    for node in walk(field.expr):
        if isinstance(node, ColumnRef) and node.name not in visible:
            raise DSLSyntaxError(f"line {field.line}: calculated field '{field.name}' in schema "
                                 f"'{schema_name}' references unknown or later-declared field "
                                 f"'{node.name}'")


def _calc_order(schema_name, fields):
    """Calculated fields ordered so each comes after the calculated fields it uses."""
    order = []
    state = {}

    def visit(f):
        mark = state.get(f.name)
        if mark == "done":
            return
        if mark == "active":
            raise DSLSyntaxError(f"line {f.line}: calculated field '{f.name}' in schema "
                                 f"'{schema_name}' depends on itself")
        state[f.name] = "active"
        for node in walk(f.expr):
            if isinstance(node, ColumnRef):
                dep = fields.get(node.name)
                if dep is not None and dep.is_calculated:
                    visit(dep)
        state[f.name] = "done"
        order.append(f)

    for f in fields.values():
        if f.is_calculated:
            visit(f)
    return order
