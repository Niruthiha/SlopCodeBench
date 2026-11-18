"""MTL parser.

Secret: the concrete syntax of the DSL -- tokens, comments, how statements
are delimited (including multi-line continuation), operator precedence, the
shapes of statements, and the structural rules (exactly one aggregate, at
most one group_by/window, unique aliases).
"""

import re

from . import program as P
from .errors import DslError

_TRANSFORM_ARITY = {"len": (1, 1), "day": (1, 1), "month": (1, 1), "year": (1, 1), "round": (1, 2)}
AGGREGATE_FUNCTIONS = ("average", "median", "sum", "count", "std", "var", "min", "max")
_RESERVED_OUTPUT = ("window_start", "window_end")

_TOKEN_RE = re.compile(r"""
    (?P<ws>\s+)
  | (?P<float>(\d+\.\d*|\.\d+)([eE][+-]?\d+)?|\d+[eE][+-]?\d+)
  | (?P<int>\d+)
  | (?P<string>'[^'\n]*')
  | (?P<ident>[A-Za-z_][A-Za-z0-9_]*)
  | (?P<op><=|>=|==|!=|[<>!&|()\[\],*+\-/%])
""", re.VERBOSE)


class _Token:
    __slots__ = ("kind", "text", "pos")

    def __init__(self, kind, text, pos):
        self.kind = kind
        self.text = text
        self.pos = pos

    def __repr__(self):
        return "%s %r" % (self.kind, self.text)


def _logical_lines(text):
    """Split source into statements, dropping comments and blank lines.

    A newline ends a statement unless it is inside brackets, the statement
    so far ends with a comma, or the next non-blank line starts with one.
    Yields (line_number, statement_text).
    """
    statements = []
    current = []
    start_line = None
    depth = 0
    line = 1
    i = 0
    n = len(text)

    def flush():
        stmt = "".join(current).strip()
        if stmt:
            statements.append((start_line, stmt))
        current.clear()

    while i < n:
        ch = text[i]
        if ch == "'":
            end = text.find("'", i + 1)
            nl = text.find("\n", i + 1)
            if end == -1 or (nl != -1 and nl < end):
                raise DslError("line %d: unterminated string literal" % line)
            if start_line is None:
                start_line = line
            current.append(text[i:end + 1])
            i = end + 1
            continue
        if ch == "#":
            nl = text.find("\n", i)
            i = n if nl == -1 else nl
            continue
        if ch == "\r":
            i += 1
            continue
        if ch == "\n":
            line += 1
            i += 1
            so_far = "".join(current).strip()
            if not so_far:
                continue
            if depth > 0 or so_far.endswith(","):
                current.append(" ")
                continue
            if _next_significant_char(text, i) == ",":
                current.append(" ")
                continue
            flush()
            start_line = None
            depth = 0
            continue
        if ch in "([":
            depth += 1
        elif ch in ")]":
            depth -= 1
        if start_line is None and not ch.isspace():
            start_line = line
        current.append(ch)
        i += 1
    flush()
    return statements


def _next_significant_char(text, i):
    n = len(text)
    while i < n:
        ch = text[i]
        if ch.isspace():
            i += 1
        elif ch == "#":
            nl = text.find("\n", i)
            if nl == -1:
                return None
            i = nl
        else:
            return ch
    return None


def _tokenize(stmt, line):
    tokens = []
    pos = 0
    while pos < len(stmt):
        m = _TOKEN_RE.match(stmt, pos)
        if not m:
            raise DslError("line %d: unexpected character %r" % (line, stmt[pos]))
        kind = m.lastgroup
        if kind != "ws":
            tokens.append(_Token(kind, m.group(), pos))
        pos = m.end()
    tokens.append(_Token("eof", "", pos))
    return tokens


class _StatementParser:
    def __init__(self, stmt, line):
        self.line = line
        self.stmt = stmt
        self.tokens = _tokenize(stmt, line)
        self.i = 0

    # -- token helpers -------------------------------------------------
    def peek(self, offset=0):
        return self.tokens[min(self.i + offset, len(self.tokens) - 1)]

    def advance(self):
        tok = self.tokens[self.i]
        if tok.kind != "eof":
            self.i += 1
        return tok

    def fail(self, message, tok=None):
        tok = tok or self.peek()
        where = "end of statement" if tok.kind == "eof" else repr(tok.text)
        raise DslError("line %d: %s (at %s)" % (self.line, message, where))

    def is_op(self, text):
        tok = self.peek()
        return tok.kind == "op" and tok.text == text

    def expect_op(self, text):
        if not self.is_op(text):
            self.fail("expected %r" % text)
        return self.advance()

    def expect_ident(self, what):
        tok = self.peek()
        if tok.kind != "ident":
            self.fail("expected %s" % what)
        return self.advance().text

    def expect_end(self):
        if self.peek().kind != "eof":
            self.fail("unexpected trailing input")

    # -- statements ----------------------------------------------------
    def statement(self):
        keyword = self.peek()
        if keyword.kind != "ident":
            self.fail("expected a statement keyword")
        name = keyword.text
        if name == "filter":
            return self.filter_statement()
        if name == "apply":
            return self.apply_statement()
        if name == "group_by":
            return self.group_by_statement()
        if name == "window":
            return self.window_statement()
        if name == "aggregate":
            return self.aggregate_statement()
        self.fail("unknown statement %r" % name, keyword)

    def filter_statement(self):
        self.advance()
        self.expect_op("(")
        expr = self.expression()
        self.expect_op(")")
        self.expect_end()
        return P.Filter(expr)

    def apply_statement(self):
        self.advance()
        self.expect_op("(")
        expr = self.expression()
        self.expect_op(",")
        tok = self.peek()
        if tok.kind == "ident":
            column = self.advance().text
        elif tok.kind == "string" and len(tok.text) > 2:
            column = self.advance().text[1:-1]
        else:
            self.fail("expected a new column name")
        self.expect_op(")")
        self.expect_end()
        return P.Apply(expr, column)

    def group_by_statement(self):
        self.advance()
        self.expect_op("(")
        bracketed = self.is_op("[")
        if bracketed:
            self.advance()
        columns = [self.expect_ident("a column name")]
        while self.is_op(","):
            self.advance()
            columns.append(self.expect_ident("a column name"))
        if bracketed:
            self.expect_op("]")
        self.expect_op(")")
        self.expect_end()
        if len(set(columns)) != len(columns):
            raise DslError("line %d: duplicate column in group_by" % self.line)
        return P.GroupBy(tuple(columns))

    def window_statement(self):
        m = re.match(r"^window\s*\(\s*(\d+)([mhd])\s*\)$", self.stmt)
        if not m:
            raise DslError("line %d: invalid window statement, expected window(<n><m|h|d>)"
                           % self.line)
        amount = int(m.group(1))
        if amount <= 0:
            raise DslError("line %d: window duration must be positive" % self.line)
        return P.Window(amount, m.group(2))

    def aggregate_statement(self):
        self.advance()
        items = [self.aggregate_item()]
        while self.is_op(","):
            self.advance()
            items.append(self.aggregate_item())
        self.expect_end()
        aliases = [it.alias for it in items]
        if len(set(aliases)) != len(aliases):
            raise DslError("line %d: aggregate aliases must be unique" % self.line)
        return P.Aggregate(tuple(items))

    def aggregate_item(self):
        fn_tok = self.peek()
        fn = self.expect_ident("an aggregate function")
        if fn not in AGGREGATE_FUNCTIONS:
            self.fail("unknown aggregate function %r" % fn, fn_tok)
        self.expect_op("(")
        if self.is_op("*"):
            self.advance()
            column = None
        else:
            column = self.expect_ident("a column name or *")
        self.expect_op(")")
        tok = self.peek()
        if not (tok.kind == "ident" and tok.text == "as"):
            self.fail("expected 'as <alias>'")
        self.advance()
        alias = self.expect_ident("an alias")
        return P.AggregateItem(fn, column, alias)

    # -- expressions ---------------------------------------------------
    def expression(self):
        return self.or_expr()

    def or_expr(self):
        left = self.and_expr()
        while self.is_op("|"):
            self.advance()
            left = P.Binary("|", left, self.and_expr())
        return left

    def and_expr(self):
        left = self.not_expr()
        while self.is_op("&"):
            self.advance()
            left = P.Binary("&", left, self.not_expr())
        return left

    def not_expr(self):
        if self.is_op("!"):
            self.advance()
            return P.Unary("!", self.not_expr())
        return self.comparison()

    def comparison(self):
        left = self.additive()
        tok = self.peek()
        if tok.kind == "op" and tok.text in ("<", "<=", ">", ">=", "==", "!="):
            op = self.advance().text
            right = self.additive()
            self.reject_chain()
            return P.Binary(op, left, right)
        if tok.kind == "ident" and tok.text == "in":
            self.advance()
            right = self.additive()
            self.reject_chain()
            return P.Binary("in", left, right)
        return left

    def reject_chain(self):
        tok = self.peek()
        if (tok.kind == "op" and tok.text in ("<", "<=", ">", ">=", "==", "!=")) or \
                (tok.kind == "ident" and tok.text == "in"):
            self.fail("comparisons cannot be chained")

    def additive(self):
        left = self.term()
        while self.peek().kind == "op" and self.peek().text in ("+", "-"):
            op = self.advance().text
            left = P.Binary(op, left, self.term())
        return left

    def term(self):
        left = self.unary()
        while self.peek().kind == "op" and self.peek().text in ("*", "/", "%"):
            op = self.advance().text
            left = P.Binary(op, left, self.unary())
        return left

    def unary(self):
        if self.peek().kind == "op" and self.peek().text in ("-", "+"):
            op = self.advance().text
            return P.Unary(op, self.unary())
        return self.primary()

    def primary(self):
        tok = self.peek()
        if tok.kind == "int":
            self.advance()
            return P.Literal("int", int(tok.text))
        if tok.kind == "float":
            self.advance()
            return P.Literal("float", float(tok.text))
        if tok.kind == "string":
            self.advance()
            return P.Literal("string", tok.text[1:-1])
        if tok.kind == "ident":
            if tok.text in ("true", "false"):
                self.advance()
                return P.Literal("bool", tok.text == "true")
            if tok.text in ("in", "as"):
                self.fail("unexpected keyword")
            self.advance()
            if self.is_op("("):
                self.advance()
                args = []
                if not self.is_op(")"):
                    args.append(self.expression())
                    while self.is_op(","):
                        self.advance()
                        args.append(self.expression())
                self.expect_op(")")
                if tok.text not in _TRANSFORM_ARITY:
                    self.fail("unknown transform %r" % tok.text, tok)
                low, high = _TRANSFORM_ARITY[tok.text]
                if not low <= len(args) <= high:
                    self.fail("wrong number of arguments to %s()" % tok.text, tok)
                return P.Call(tok.text, tuple(args))
            return P.ColumnRef(tok.text)
        if self.is_op("("):
            self.advance()
            inner = self.expression()
            self.expect_op(")")
            return inner
        self.fail("expected an expression")


def parse_program(text):
    """Parse DSL source into a program.Program; raises DslError."""
    steps = []
    group_by = window = aggregate = None
    for line, stmt in _logical_lines(text):
        node = _StatementParser(stmt, line).statement()
        if isinstance(node, (P.Filter, P.Apply)):
            steps.append(node)
        elif isinstance(node, P.GroupBy):
            if group_by is not None:
                raise DslError("line %d: group_by may appear at most once" % line)
            group_by = node
        elif isinstance(node, P.Window):
            if window is not None:
                raise DslError("line %d: window may appear at most once" % line)
            window = node
        else:
            if aggregate is not None:
                raise DslError("line %d: aggregate must appear exactly once" % line)
            aggregate = node
    if aggregate is None:
        raise DslError("program has no aggregate statement")
    _check_output_names(group_by, window, aggregate)
    return P.Program(steps, group_by, window, aggregate)


def _check_output_names(group_by, window, aggregate):
    taken = set(group_by.columns) if group_by else set()
    if window:
        clash = taken.intersection(_RESERVED_OUTPUT)
        if clash:
            raise DslError("group_by column %r collides with a window field" % sorted(clash)[0])
        taken.update(_RESERVED_OUTPUT)
    for item in aggregate.items:
        if item.alias in taken:
            raise DslError("aggregate alias %r collides with another output field" % item.alias)
