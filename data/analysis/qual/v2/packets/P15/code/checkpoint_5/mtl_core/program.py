"""Abstract syntax of an MTL program.

This is the shared vocabulary between the parser and the engine; it reveals
nothing about concrete syntax or about how programs are executed.
"""

from collections import namedtuple

# Expressions
Literal = namedtuple("Literal", "kind value")        # kind: int|float|string|bool
ColumnRef = namedtuple("ColumnRef", "name")
Unary = namedtuple("Unary", "op operand")            # op: ! - +
Binary = namedtuple("Binary", "op left right")       # op: | & == != < <= > >= in + - * / %
Call = namedtuple("Call", "name args")               # transform / function call
Param = namedtuple("Param", "name")                  # param("<name>")
Cast = namedtuple("Cast", "operand type")            # cast(<expr> as <type>)

# Statements
Filter = namedtuple("Filter", "predicate")
Apply = namedtuple("Apply", "expression column")
GroupBy = namedtuple("GroupBy", "columns")
Window = namedtuple("Window", "amount unit param")   # unit: m|h|d; param: name or None
Window.__new__.__defaults__ = (None,)
AggregateItem = namedtuple("AggregateItem", "function column alias")  # column None means *
Aggregate = namedtuple("Aggregate", "items")
Calc = namedtuple("Calc", "name expression type stage")               # stage: pre|post_agg

# Multi-source pipelines
SourceBinding = namedtuple("SourceBinding", "name alias")     # config source name, DSL alias
ScopedBlock = namedtuple("ScopedBlock", "alias steps line")   # with <alias> { Calc/Filter/Apply }
Duration = namedtuple("Duration", "amount unit param")        # unit: s|m|h|d; param name or None
ProjectItem = namedtuple("ProjectItem", "expression name")
Join = namedtuple("Join", "left right on within kind project alias line")
# left/right: alias of a source, of an earlier join, or "_" (the previous join's result)
# kind: inner|left|right|full; within: Duration or None; alias: name or None

# Declarations
FieldDef = namedtuple("FieldDef", "name type expression")   # expression None => physical
SchemaDef = namedtuple("SchemaDef", "name base fields")     # base: schema name or None
ParamDef = namedtuple("ParamDef", "name type default")      # type/default may be None

STAGE_PRE = "pre"
STAGE_POST = "post_agg"


class Program:
    """A validated pipeline: row steps in order plus the rollup clauses."""

    def __init__(self, steps, group_by, window, aggregate, calcs=(), params=(),
                 schemas=None, schema_name=None, name=None, sources=None, scoped=(),
                 joins=()):
        self.steps = tuple(steps)        # Filter / Apply, in execution order
        self.group_by = group_by         # GroupBy or None
        self.window = window             # Window or None
        self.aggregate = aggregate       # Aggregate
        self.calcs = tuple(calcs)        # Calc, in declaration order
        self.params = tuple(params)      # ParamDef, in declaration order
        self.schemas = dict(schemas or {})  # name -> SchemaDef
        self.schema_name = schema_name   # schema named by `using`, or None
        self.name = name                 # pipeline name, or None (bare program)
        self.sources = None if sources is None else tuple(sources)  # SourceBinding, or None
        self.scoped = tuple(scoped)      # ScopedBlock, in declaration order
        self.joins = tuple(joins)        # Join, in execution order

    @property
    def pre_calcs(self):
        return tuple(c for c in self.calcs if c.stage == STAGE_PRE)

    @property
    def post_calcs(self):
        return tuple(c for c in self.calcs if c.stage == STAGE_POST)


def walk(expr):
    """Yield `expr` and every expression nested inside it, parents first."""
    yield expr
    if isinstance(expr, Unary):
        yield from walk(expr.operand)
    elif isinstance(expr, Binary):
        yield from walk(expr.left)
        yield from walk(expr.right)
    elif isinstance(expr, Call):
        for arg in expr.args:
            yield from walk(arg)
    elif isinstance(expr, Cast):
        yield from walk(expr.operand)


def program_expressions(program):
    """Every top-level expression of a program (schemas, steps, calcs, scoped blocks, joins)."""
    for schema in program.schemas.values():
        for field in schema.fields:
            if field.expression is not None:
                yield field.expression
    for step in program.steps:
        yield step.predicate if isinstance(step, Filter) else step.expression
    for calc in program.calcs:
        yield calc.expression
    for block in program.scoped:
        for step in block.steps:
            if isinstance(step, Filter):
                yield step.predicate
            else:
                yield step.expression
    for join in program.joins:
        yield join.on
        for item in join.project:
            yield item.expression
