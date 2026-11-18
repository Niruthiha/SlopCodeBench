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
    def __init__(self, name, line):
        self.name = name
        self.line = line


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
    def __init__(self, amount, unit, seconds, line):
        self.amount = amount
        self.unit = unit
        self.seconds = seconds
        self.line = line


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


class Program:
    """A parsed pipeline: ordered row operations plus the grouping/aggregation spec."""

    def __init__(self, row_ops, group_by, window, aggregate):
        self.row_ops = row_ops
        self.group_by = group_by
        self.window = window
        self.aggregate = aggregate

    @property
    def group_columns(self):
        return self.group_by.columns if self.group_by else []
