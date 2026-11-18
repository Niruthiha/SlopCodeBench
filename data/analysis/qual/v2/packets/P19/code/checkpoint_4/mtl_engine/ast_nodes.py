"""AST node definitions for MTL expressions and statements.

Expression nodes carry a `type` attribute that the type checker fills in.
"""


class Expr:
    type = None


class Literal(Expr):
    def __init__(self, value, value_type):
        self.value = value
        self.type = value_type


class ColumnRef(Expr):
    """A column reference; `qualifier` is the relation alias of `A.col` (None when bare)."""

    def __init__(self, name, line, qualifier=None):
        self.name = name
        self.line = line
        self.qualifier = qualifier


class Unary(Expr):
    def __init__(self, op, operand, line):
        self.op = op
        self.operand = operand
        self.line = line


class Binary(Expr):
    def __init__(self, op, left, right, line):
        self.op = op
        self.left = left
        self.right = right
        self.line = line


class InExpr(Expr):
    """`needle in haystack`: substring test."""

    def __init__(self, needle, haystack, line):
        self.needle = needle
        self.haystack = haystack
        self.line = line


class Call(Expr):
    def __init__(self, name, args, line):
        self.name = name
        self.args = args
        self.line = line


class Cast(Expr):
    """`cast(expr as type)`: explicit conversion."""

    def __init__(self, operand, target, line):
        self.operand = operand
        self.target = target
        self.line = line


class Filter:
    def __init__(self, predicate, line):
        self.predicate = predicate
        self.line = line


class Apply:
    def __init__(self, expr, column, line):
        self.expr = expr
        self.column = column
        self.line = line


class GroupBy:
    def __init__(self, columns, line):
        self.columns = columns
        self.line = line


class Window:
    """A tumbling window; `param` names a parameter supplying the duration instead."""

    def __init__(self, amount, unit, seconds, line, param=None):
        self.amount = amount
        self.unit = unit
        self.seconds = seconds
        self.line = line
        self.param = param


class AggItem:
    def __init__(self, func, column, alias, line):
        self.func = func
        self.column = column  # None means '*'
        self.alias = alias
        self.line = line


class Aggregate:
    def __init__(self, items, line):
        self.items = items
        self.line = line


PRE = "pre"
POST_AGG = "post_agg"


class Calc:
    """`calc name = expr : type @stage(stage)`."""

    def __init__(self, name, expr, declared_type, stage, line):
        self.name = name
        self.expr = expr
        self.declared_type = declared_type
        self.stage = stage
        self.line = line


class FieldDecl:
    """A schema field: physical when `expr` is None, otherwise calculated (pre-stage)."""

    def __init__(self, name, field_type, expr, line):
        self.name = name
        self.type = field_type
        self.expr = expr
        self.line = line


class SchemaDecl:
    def __init__(self, name, base, fields, line):
        self.name = name
        self.base = base
        self.fields = fields
        self.line = line


class ParamDecl:
    """A pipeline parameter; `type` and `default` (a Literal) are both optional."""

    def __init__(self, name, param_type, default, line):
        self.name = name
        self.type = param_type
        self.default = default
        self.line = line


class SourceBinding:
    """`name as alias` inside a `sources { ... }` block."""

    def __init__(self, name, alias, line):
        self.name = name
        self.alias = alias
        self.line = line


class SourcesDecl:
    def __init__(self, bindings, line):
        self.bindings = bindings
        self.line = line


class WithBlock:
    """`with Alias { ... }`: pre-stage calcs and filters scoped to one relation."""

    def __init__(self, alias, calcs, filters, line):
        self.alias = alias
        self.calcs = calcs
        self.filters = filters
        self.line = line


class Projection:
    def __init__(self, expr, name, line):
        self.expr = expr
        self.name = name
        self.line = line


JOIN_TYPES = ("inner", "left", "right", "full")


class Join:
    """`join L with R on (...) [within D] type T project { ... } [as Alias]`."""

    def __init__(self, left, right, on, within, join_type, projections, alias, line):
        self.left = left
        self.right = right
        self.on = on
        self.within = within  # seconds, or None
        self.join_type = join_type
        self.projections = projections
        self.alias = alias
        self.line = line


class Program:
    """A parsed pipeline: ordered row operations plus the grouping/aggregation spec.

    A program read from a bare statement file has no schema (its typing
    environment is the CSV header); one read from a `pipeline` block names
    the schema it uses and may declare parameters.
    """

    def __init__(self, row_ops, group_by, window, aggregate, calcs=(),
                 params=(), schema_name=None, schemas=None, name=None,
                 sources=None, with_blocks=(), joins=()):
        self.row_ops = row_ops
        self.group_by = group_by
        self.window = window
        self.aggregate = aggregate
        self.calcs = list(calcs)
        self.params = list(params)
        self.schema_name = schema_name
        self.schemas = schemas or {}
        self.name = name
        self.sources = sources  # SourcesDecl or None
        self.with_blocks = list(with_blocks)
        self.joins = list(joins)

    @property
    def pre_calcs(self):
        return [c for c in self.calcs if c.stage == PRE]

    @property
    def post_calcs(self):
        return [c for c in self.calcs if c.stage == POST_AGG]

    @property
    def group_columns(self):
        return self.group_by.columns if self.group_by else []
