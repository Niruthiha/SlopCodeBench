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
Call = namedtuple("Call", "name args")               # transform call

# Statements
Filter = namedtuple("Filter", "predicate")
Apply = namedtuple("Apply", "expression column")
GroupBy = namedtuple("GroupBy", "columns")
Window = namedtuple("Window", "amount unit")         # unit: m|h|d
AggregateItem = namedtuple("AggregateItem", "function column alias")  # column None means *
Aggregate = namedtuple("Aggregate", "items")


class Program:
    """A validated pipeline: row steps in order plus the rollup clauses."""

    def __init__(self, steps, group_by, window, aggregate):
        self.steps = tuple(steps)        # Filter / Apply, in execution order
        self.group_by = group_by         # GroupBy or None
        self.window = window             # Window or None
        self.aggregate = aggregate       # Aggregate
