"""Recursive-descent parser turning DSL source into a Program."""
from . import dtypes
from .ast_nodes import (AggItem, Aggregate, Apply, Binary, Call, ColumnRef, Filter,
                        GroupBy, InExpr, Literal, Program, Unary, Window)
from .errors import DSLSyntaxError
from .functions import ARITY
from .lexer import DURATION, DURATION_UNITS, EOF, IDENT, NUMBER, STRING, Token
from .lexer import split_statements, tokenize

AGG_FUNCTIONS = ("average", "median", "sum", "count", "std", "var", "min", "max")
COMPARISON_OPS = ("<", "<=", ">", ">=", "==", "!=")
RESERVED = ("true", "false", "in")


def parse_program(source):
    statements = []
    for stmt_tokens in split_statements(tokenize(source)):
        statements.append(_StatementParser(stmt_tokens).parse_statement())

    row_ops, group_by, window, aggregate = [], None, None, None
    for stmt in statements:
        if isinstance(stmt, (Filter, Apply)):
            row_ops.append(stmt)
        elif isinstance(stmt, GroupBy):
            if group_by is not None:
                raise DSLSyntaxError(f"line {stmt.line}: group_by may appear at most once")
            group_by = stmt
        elif isinstance(stmt, Window):
            if window is not None:
                raise DSLSyntaxError(f"line {stmt.line}: window may appear at most once")
            window = stmt
        elif isinstance(stmt, Aggregate):
            if aggregate is not None:
                raise DSLSyntaxError(f"line {stmt.line}: aggregate must appear exactly once")
            aggregate = stmt
    if aggregate is None:
        raise DSLSyntaxError("missing required aggregate statement")

    _check_output_names(group_by, aggregate, window)
    return Program(row_ops, group_by, window, aggregate)


def _check_output_names(group_by, aggregate, window):
    reserved = {"window_start", "window_end"} if window else set()
    taken = set()
    if group_by:
        for col in group_by.columns:
            if col in reserved:
                raise DSLSyntaxError(f"line {group_by.line}: group_by column '{col}' "
                                     "clashes with a window output field")
            taken.add(col)
    for item in aggregate.items:
        if item.alias in taken or item.alias in reserved:
            raise DSLSyntaxError(f"line {item.line}: output name '{item.alias}' is not unique")
        taken.add(item.alias)


class _StatementParser:
    """Parses the tokens of one logical statement."""

    def __init__(self, tokens):
        self.tokens = tokens + [Token(EOF, None, tokens[-1].line, 0)]
        self.pos = 0

    # -- token helpers -------------------------------------------------
    @property
    def tok(self):
        return self.tokens[self.pos]

    def advance(self):
        tok = self.tokens[self.pos]
        if tok.kind != EOF:
            self.pos += 1
        return tok

    def error(self, message, tok=None):
        tok = tok or self.tok
        raise DSLSyntaxError(f"line {tok.line}:{tok.col}: {message}")

    def expect_op(self, op):
        if not self.tok.is_op(op):
            self.error(f"expected '{op}' but found {self.tok.describe()}")
        return self.advance()

    def expect_ident(self, what):
        tok = self.tok
        if tok.kind != IDENT or tok.value in RESERVED:
            self.error(f"expected {what} but found {tok.describe()}")
        return self.advance().value

    def expect_end(self):
        if self.tok.kind != EOF:
            self.error(f"unexpected {self.tok.describe()}")

    # -- statements ----------------------------------------------------
    def parse_statement(self):
        head = self.tok
        if head.kind != IDENT:
            self.error(f"expected a statement but found {head.describe()}")
        handler = {
            "filter": self.parse_filter,
            "apply": self.parse_apply,
            "group_by": self.parse_group_by,
            "window": self.parse_window,
            "aggregate": self.parse_aggregate,
        }.get(head.value)
        if handler is None:
            self.error(f"unknown statement '{head.value}'")
        self.advance()
        stmt = handler(head.line)
        self.expect_end()
        return stmt

    def parse_filter(self, line):
        self.expect_op("(")
        expr = self.parse_expr()
        self.expect_op(")")
        return Filter(expr, line)

    def parse_apply(self, line):
        self.expect_op("(")
        expr = self.parse_expr()
        self.expect_op(",")
        name = self.expect_ident("a new column name")
        self.expect_op(")")
        return Apply(expr, name, line)

    def parse_group_by(self, line):
        self.expect_op("(")
        if self.tok.is_op("["):
            self.advance()
            columns = [self.expect_ident("a column name")]
            while self.tok.is_op(","):
                self.advance()
                columns.append(self.expect_ident("a column name"))
            self.expect_op("]")
        else:
            columns = [self.expect_ident("a column name")]
        self.expect_op(")")
        if len(set(columns)) != len(columns):
            raise DSLSyntaxError(f"line {line}: duplicate column in group_by")
        return GroupBy(columns, line)

    def parse_window(self, line):
        self.expect_op("(")
        tok = self.tok
        if tok.kind != DURATION:
            self.error(f"expected a duration literal like 10m, 1h or 7d but found {tok.describe()}")
        self.advance()
        amount, unit = tok.value
        if amount <= 0:
            self.error("window duration must be positive", tok)
        self.expect_op(")")
        return Window(amount, unit, amount * DURATION_UNITS[unit], line)

    def parse_aggregate(self, line):
        items = [self.parse_agg_item()]
        while self.tok.is_op(","):
            self.advance()
            items.append(self.parse_agg_item())
        return Aggregate(items, line)

    def parse_agg_item(self):
        tok = self.tok
        if tok.kind != IDENT:
            self.error(f"expected an aggregate function but found {tok.describe()}")
        if tok.value not in AGG_FUNCTIONS:
            self.error(f"unknown aggregate function '{tok.value}'")
        self.advance()
        self.expect_op("(")
        if self.tok.is_op("*"):
            self.advance()
            column = None
        else:
            column = self.expect_ident("a column name or '*'")
        self.expect_op(")")
        if not self.tok.is_ident("as"):
            self.error(f"expected 'as <alias>' but found {self.tok.describe()}")
        self.advance()
        alias = self.expect_ident("an alias")
        return AggItem(tok.value, column, alias, tok.line)

    # -- expressions ---------------------------------------------------
    def parse_expr(self):
        return self.parse_or()

    def parse_or(self):
        left = self.parse_and()
        while self.tok.is_op("|"):
            op = self.advance()
            left = Binary("|", left, self.parse_and(), op.line)
        return left

    def parse_and(self):
        left = self.parse_not()
        while self.tok.is_op("&"):
            op = self.advance()
            left = Binary("&", left, self.parse_not(), op.line)
        return left

    def parse_not(self):
        if self.tok.is_op("!"):
            op = self.advance()
            return Unary("!", self.parse_not(), op.line)
        return self.parse_comparison()

    def parse_comparison(self):
        left = self.parse_additive()
        tok = self.tok
        if tok.kind == "OP" and tok.value in COMPARISON_OPS:
            self.advance()
            node = Binary(tok.value, left, self.parse_additive(), tok.line)
        elif tok.is_ident("in"):
            self.advance()
            node = InExpr(left, self.parse_additive(), tok.line)
        else:
            return left
        nxt = self.tok
        if (nxt.kind == "OP" and nxt.value in COMPARISON_OPS) or nxt.is_ident("in"):
            self.error("comparisons cannot be chained; use parentheses and '&'")
        return node

    def parse_additive(self):
        left = self.parse_multiplicative()
        while self.tok.is_op("+", "-"):
            op = self.advance()
            left = Binary(op.value, left, self.parse_multiplicative(), op.line)
        return left

    def parse_multiplicative(self):
        left = self.parse_unary()
        while self.tok.is_op("*", "/", "%"):
            op = self.advance()
            left = Binary(op.value, left, self.parse_unary(), op.line)
        return left

    def parse_unary(self):
        if self.tok.is_op("-", "+"):
            op = self.advance()
            operand = self.parse_unary()
            if isinstance(operand, Literal) and dtypes.is_numeric(operand.type):
                value = -operand.value if op.value == "-" else operand.value
                return Literal(value, operand.type)
            return Unary(op.value, operand, op.line)
        return self.parse_primary()

    def parse_primary(self):
        tok = self.tok
        if tok.kind == NUMBER:
            self.advance()
            return Literal(tok.value, dtypes.FLOAT if isinstance(tok.value, float) else dtypes.INT)
        if tok.kind == STRING:
            self.advance()
            return Literal(tok.value, dtypes.STRING)
        if tok.is_op("("):
            self.advance()
            expr = self.parse_expr()
            self.expect_op(")")
            return expr
        if tok.kind == IDENT:
            if tok.value in ("true", "false"):
                self.advance()
                return Literal(tok.value == "true", dtypes.BOOL)
            if tok.value == "in":
                self.error("unexpected 'in'")
            self.advance()
            if self.tok.is_op("("):
                return self.parse_call(tok)
            return ColumnRef(tok.value, tok.line)
        self.error(f"expected an expression but found {tok.describe()}")

    def parse_call(self, name_tok):
        name = name_tok.value
        if name not in ARITY:
            self.error(f"unknown function '{name}'", name_tok)
        self.expect_op("(")
        args = []
        if not self.tok.is_op(")"):
            args.append(self.parse_expr())
            while self.tok.is_op(","):
                self.advance()
                args.append(self.parse_expr())
        self.expect_op(")")
        lo, hi = ARITY[name]
        if not lo <= len(args) <= hi:
            expected = str(lo) if lo == hi else f"{lo} to {hi}"
            self.error(f"{name}() takes {expected} argument(s), got {len(args)}", name_tok)
        return Call(name, args, name_tok.line)
