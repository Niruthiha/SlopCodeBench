#!/usr/bin/env python3
"""MTL: run a small pipeline DSL (schemas, params, calcs, filter/apply/group_by/window/aggregate) over a CSV of sales events."""

import argparse
import csv
import io
import json
import math
import re
import sys
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP, localcontext

try:
    from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
except ImportError:  # pragma: no cover
    ZoneInfo = None
    ZoneInfoNotFoundError = Exception

EXIT_CODES = {"bad_dsl": 1, "type_error": 2, "bad_io": 3, "runtime_error": 4}


class MTLError(Exception):
    def __init__(self, kind, message):
        super().__init__(message)
        self.kind = kind
        self.message = message


def dsl_error(msg):
    return MTLError("bad_dsl", msg)


def type_error(msg):
    return MTLError("type_error", msg)


def io_error(msg):
    return MTLError("bad_io", msg)


def runtime_error(msg):
    return MTLError("runtime_error", msg)


# --------------------------------------------------------------------------- types

INT, FLOAT, STR, BOOL, TS = "int", "float", "string", "bool", "timestamp"
NUMERIC = (INT, FLOAT)
TYPES = (STR, INT, FLOAT, BOOL, TS)

REQUIRED_COLUMNS = {
    "timestamp": TS,
    "location": STR,
    "item": STR,
    "price": FLOAT,
    "quantity": FLOAT,
    "unit": STR,
    "category": STR,
}

WINDOW_KEYS = ("window_start", "window_end")
RESERVED_WORDS = ("true", "false", "in")

EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)
ONE_US = timedelta(microseconds=1)

# --------------------------------------------------------------------------- tokenizer

TOKEN_RE = re.compile(
    r"""
    (?P<nl>\n)
  | (?P<ws>[ \t\r\f\v]+)
  | (?P<comment>\#[^\n]*)
  | (?P<num>(?:\d+\.\d*|\.\d+|\d+)(?:[eE][+-]?\d+)?)
  | (?P<str>'[^'\n]*'|"[^"\n]*")
  | (?P<ident>[A-Za-z_][A-Za-z0-9_]*)
  | (?P<op><=|>=|==|!=|<|>|!|&|\||\+|-|\*|/|%|\(|\)|\[|\]|,|\{|\}|:|=|@)
    """,
    re.VERBOSE,
)


class Token:
    __slots__ = ("kind", "value", "pos", "end")

    def __init__(self, kind, value, pos, end):
        self.kind = kind
        self.value = value
        self.pos = pos
        self.end = end

    def __repr__(self):
        return f"{self.kind}:{self.value!r}"


def tokenize(text):
    tokens = []
    pos = 0
    while pos < len(text):
        m = TOKEN_RE.match(text, pos)
        if not m:
            ch = text[pos]
            if ch in "'\"":
                raise dsl_error(f"unterminated string literal at column {pos + 1}")
            raise dsl_error(f"unexpected character {ch!r} at column {pos + 1}")
        kind = m.lastgroup
        value = m.group()
        if kind == "str":
            if "\\" in value:
                raise dsl_error("escape sequences are not allowed in string literals")
            value = value[1:-1]
        if kind not in ("ws", "comment"):
            tokens.append(Token(kind, value, m.start(), m.end()))
        pos = m.end()
    tokens.append(Token("eof", None, len(text), len(text)))
    return tokens


# --------------------------------------------------------------------------- AST

class Lit:
    def __init__(self, value, typ):
        self.value = value
        self.typ = typ


class Col:
    def __init__(self, name):
        self.name = name


class Call:
    def __init__(self, name, args):
        self.name = name
        self.args = args


class Cast:
    def __init__(self, expr, typ):
        self.expr = expr
        self.typ = typ


class Unary:
    def __init__(self, op, operand):
        self.op = op
        self.operand = operand


class Binary:
    def __init__(self, op, left, right):
        self.op = op
        self.left = left
        self.right = right


FUNCTION_ARITY = {
    "len": (1, 1),
    "day": (1, 1),
    "month": (1, 1),
    "year": (1, 1),
    "round": (1, 2),
    "param": (1, 1),
    "lag": (1, 2),
    "lead": (1, 2),
    "coalesce": (2, None),
    "starts_with": (2, 2),
    "ends_with": (2, 2),
    "contains": (2, 2),
}
STRING_OPS = ("starts_with", "ends_with", "contains")
AGG_FUNCTIONS = ("average", "median", "sum", "count", "std", "var", "min", "max")
COMPARISON_OPS = ("<", "<=", ">", ">=", "==", "!=")
STATEMENT_KEYWORDS = ("filter", "apply", "group_by", "window", "aggregate")


def children(node):
    if isinstance(node, Unary):
        return [node.operand]
    if isinstance(node, Binary):
        return [node.left, node.right]
    if isinstance(node, Call):
        return [] if node.name == "param" else node.args
    if isinstance(node, Cast):
        return [node.expr]
    return []


def walk(node):
    stack = [node]
    while stack:
        n = stack.pop()
        yield n
        stack.extend(reversed(children(n)))


def col_refs(node):
    refs = []
    for n in walk(node):
        if isinstance(n, Col) and n.name not in refs:
            refs.append(n.name)
    return refs


class Parser:
    def __init__(self, text=None, tokens=None):
        self.tokens = tokens if tokens is not None else tokenize(text)
        self.i = 0

    # -- helpers
    def peek(self, offset=0):
        return self.tokens[min(self.i + offset, len(self.tokens) - 1)]

    def next(self):
        tok = self.tokens[self.i]
        if tok.kind != "eof":
            self.i += 1
        return tok

    def at(self, kind, value=None):
        tok = self.peek()
        return tok.kind == kind and (value is None or tok.value == value)

    def at_op(self, *values):
        tok = self.peek()
        return tok.kind == "op" and tok.value in values

    def expect_op(self, value):
        tok = self.next()
        if tok.kind != "op" or tok.value != value:
            raise dsl_error(f"expected '{value}' but found {describe(tok)}")
        return tok

    def expect_ident(self, what="identifier"):
        tok = self.next()
        if tok.kind != "ident":
            raise dsl_error(f"expected {what} but found {describe(tok)}")
        return tok.value

    def expect_name(self, what="column name"):
        """A column name written either bare or as a quoted string."""
        tok = self.next()
        if tok.kind not in ("ident", "str") or tok.value == "":
            raise dsl_error(f"expected {what} but found {describe(tok)}")
        return tok.value

    def expect_eof(self):
        tok = self.peek()
        if tok.kind != "eof":
            raise dsl_error(f"unexpected {describe(tok)} at end of statement")

    # -- expressions
    def parse_expr(self):
        return self.parse_or()

    def parse_or(self):
        node = self.parse_and()
        while self.at_op("|"):
            self.next()
            node = Binary("|", node, self.parse_and())
        return node

    def parse_and(self):
        node = self.parse_not()
        while self.at_op("&"):
            self.next()
            node = Binary("&", node, self.parse_not())
        return node

    def parse_not(self):
        if self.at_op("!"):
            self.next()
            return Unary("!", self.parse_not())
        return self.parse_comparison()

    def at_comparison(self):
        tok = self.peek()
        if tok.kind == "op":
            return tok.value in COMPARISON_OPS
        return tok.kind == "ident" and (tok.value == "in" or tok.value in STRING_OPS)

    def parse_comparison(self):
        node = self.parse_additive()
        if not self.at_comparison():
            return node
        op = self.next().value
        node = Binary(op, node, self.parse_additive())
        if self.at_comparison():
            raise dsl_error("comparison operators cannot be chained; use parentheses")
        return node

    def parse_additive(self):
        node = self.parse_multiplicative()
        while self.at_op("+", "-"):
            op = self.next().value
            node = Binary(op, node, self.parse_multiplicative())
        return node

    def parse_multiplicative(self):
        node = self.parse_unary()
        while self.at_op("*", "/", "%"):
            op = self.next().value
            node = Binary(op, node, self.parse_unary())
        return node

    def parse_unary(self):
        if self.at_op("-", "+"):
            op = self.next().value
            operand = self.parse_unary()
            if isinstance(operand, Lit) and operand.typ in NUMERIC:
                return Lit(-operand.value if op == "-" else operand.value, operand.typ)
            return operand if op == "+" else Unary("-", operand)
        return self.parse_primary()

    def parse_primary(self):
        tok = self.next()
        if tok.kind == "num":
            if re.fullmatch(r"\d+", tok.value):
                return Lit(int(tok.value), INT)
            value = float(tok.value)
            if not math.isfinite(value):
                raise dsl_error(f"numeric literal {tok.value} is out of range")
            return Lit(value, FLOAT)
        if tok.kind == "str":
            return Lit(tok.value, STR)
        if tok.kind == "ident":
            if tok.value == "true":
                return Lit(True, BOOL)
            if tok.value == "false":
                return Lit(False, BOOL)
            if tok.value == "in":
                raise dsl_error("unexpected keyword 'in'")
            if self.at_op("("):
                if tok.value == "cast":
                    return self.parse_cast()
                return self.parse_call(tok.value)
            return Col(tok.value)
        if tok.kind == "op" and tok.value == "(":
            node = self.parse_expr()
            self.expect_op(")")
            return node
        raise dsl_error(f"unexpected {describe(tok)} in expression")

    def parse_cast(self):
        self.expect_op("(")
        expr = self.parse_expr()
        if not self.at("ident", "as"):
            raise dsl_error(f"expected 'as <type>' in cast(...), found {describe(self.peek())}")
        self.next()
        typ = parse_type(self)
        self.expect_op(")")
        return Cast(expr, typ)

    def parse_call(self, name):
        if name not in FUNCTION_ARITY:
            raise dsl_error(f"unknown function '{name}'")
        self.expect_op("(")
        args = []
        if not self.at_op(")"):
            args.append(self.parse_expr())
            while self.at_op(","):
                self.next()
                args.append(self.parse_expr())
        self.expect_op(")")
        lo, hi = FUNCTION_ARITY[name]
        if len(args) < lo or (hi is not None and len(args) > hi):
            expected = str(lo) if lo == hi else (f"at least {lo}" if hi is None else f"{lo} to {hi}")
            raise dsl_error(f"function '{name}' expects {expected} argument(s), got {len(args)}")
        if name == "param" and not (isinstance(args[0], Lit) and args[0].typ == STR):
            raise dsl_error("param() expects a quoted parameter name")
        return Call(name, args)

    # -- block-level helpers (operate on the whole-file token stream)
    def skip_nl(self):
        while self.at("nl"):
            self.next()

    def peek_past_nl(self):
        j = self.i
        while self.tokens[j].kind == "nl":
            j += 1
        return self.tokens[j]

    def collect_statement(self):
        """Gather the tokens of one logical statement inside a block.

        A newline ends the statement unless brackets are open, the line ends with an
        operator/comma, or the next line starts with an operator. A '}' at depth 0 ends
        the statement without being consumed."""
        out = []
        depth = 0
        while True:
            tok = self.peek()
            if tok.kind == "eof":
                break
            if tok.kind == "op" and tok.value == "}" and depth <= 0:
                break
            if tok.kind == "nl":
                self.next()
                if depth > 0 or not out or self.continues(out):
                    continue
                break
            if tok.kind == "op" and tok.value in "([":
                depth += 1
            elif tok.kind == "op" and tok.value in ")]":
                depth -= 1
            out.append(self.next())
        end = out[-1].end if out else self.peek().pos
        out.append(Token("eof", None, end, end))
        return out

    def continues(self, out):
        last = out[-1]
        if last.kind == "op" and last.value not in (")", "]", "}", "{"):
            return True
        if last.kind == "ident" and last.value in ("as", "in", "starts_with", "ends_with", "extends", "using"):
            return True
        if len(out) == 1 and last.kind == "ident" and last.value == "aggregate":
            return True
        nxt = self.peek_past_nl()
        if nxt.kind == "op" and nxt.value not in ("{", "}"):
            return True
        return nxt.kind == "ident" and nxt.value in ("as", "in", "starts_with", "ends_with")


def describe(tok):
    if tok.kind == "eof":
        return "end of statement"
    if tok.kind == "nl":
        return "end of line"
    if tok.kind == "str":
        return f"string '{tok.value}'"
    return f"'{tok.value}'"


def parse_type(p):
    tok = p.next()
    if tok.kind != "ident":
        raise dsl_error(f"expected a type but found {describe(tok)}")
    if tok.value not in TYPES:
        raise dsl_error(f"unknown type '{tok.value}'; expected one of {', '.join(TYPES)}")
    return tok.value


# --------------------------------------------------------------------------- statements

class Program:
    def __init__(self):
        self.steps = []  # ("filter", expr) | ("apply", expr, name) | ("calc", CalcDecl)
        self.group_by = None  # list of column names
        self.window = None  # width in microseconds
        self.window_text = None
        self.window_param = None  # name of a param holding the duration
        self.aggregates = None  # list of (fn, column-or-None, alias)
        # block-format additions
        self.block = False
        self.name = None
        self.schema_name = None
        self.schema_fields = None  # resolved schema: name -> SchemaField
        self.schema_calc_order = []  # schema calc field names in evaluation order
        self.params = {}  # name -> ParamDecl
        self.post_calcs = []  # CalcDecl with stage post_agg
        self.order = None  # execution order of row-level steps
        self.deferred_errors = []  # type errors found while resolving schemas


class CalcDecl:
    def __init__(self, name, expr, typ, stage):
        self.name = name
        self.expr = expr
        self.typ = typ
        self.stage = stage


class ParamDecl:
    def __init__(self, name, typ, default):
        self.name = name
        self.typ = typ
        self.default = default  # Lit or None


class FieldDecl:
    def __init__(self, name, typ, expr, line):
        self.name = name
        self.typ = typ
        self.expr = expr
        self.line = line


class SchemaDecl:
    def __init__(self, name, base):
        self.name = name
        self.base = base
        self.fields = []


class SchemaField:
    def __init__(self, typ, expr):
        self.typ = typ
        self.expr = expr


def split_statements(text):
    """Strip comments and join physical lines into logical statements."""
    statements = []
    buf = []
    depth = 0
    start_line = None
    for lineno, raw in enumerate(text.splitlines(), 1):
        out = []
        quote = None
        for ch in raw:
            if quote:
                if ch == quote:
                    quote = None
            elif ch in "'\"":
                quote = ch
            elif ch == "#":
                break
            elif ch in "([":
                depth += 1
            elif ch in ")]":
                depth -= 1
            out.append(ch)
        line = "".join(out).strip()
        if not line and not buf:
            continue
        if not buf:
            start_line = lineno
        if line:
            buf.append(line)
        joined = " ".join(buf)
        if depth > 0 or joined.endswith(",") or joined == "aggregate":
            continue
        statements.append((start_line, joined))
        buf = []
        depth = 0
    if buf:
        statements.append((start_line, " ".join(buf)))
    return statements


DURATION_UNITS = {"m": 60, "h": 3600, "d": 86400}
DURATION_RE = re.compile(r"\s*(\d+)\s*([mhd])\s*")


def is_block_format(text):
    for tok in tokenize(text):
        if tok.kind == "nl":
            continue
        return tok.kind == "ident" and tok.value in ("schema", "pipeline")
    return False


def parse_program(text, cli_params=None):
    cli_params = cli_params or {}
    try:
        block = is_block_format(text)
    except MTLError:
        block = False
    if block:
        return parse_block_program(text, cli_params)
    program = Program()
    for lineno, stmt in split_statements(text):
        try:
            parse_statement(program, Parser(stmt))
        except MTLError as e:
            if e.kind == "bad_dsl":
                raise dsl_error(f"line {lineno}: {e.message}")
            raise
    if program.aggregates is None:
        raise dsl_error("exactly one 'aggregate' statement is required")
    validate_output_keys(program)
    for step in program.steps:
        check_expr_structure(step[1], {}, post=False)
    if program.window_param is not None:
        raise dsl_error(f"unknown parameter '{program.window_param}'")
    program.order = list(program.steps)
    return program


def parse_statement(program, p):
    head = p.next()
    if head.kind != "ident" or head.value not in STATEMENT_KEYWORDS:
        raise dsl_error(f"unknown statement starting with {describe(head)}")
    kw = head.value
    if kw == "filter":
        p.expect_op("(")
        expr = p.parse_expr()
        p.expect_op(")")
        p.expect_eof()
        program.steps.append(("filter", expr))
    elif kw == "apply":
        p.expect_op("(")
        expr = p.parse_expr()
        p.expect_op(",")
        name = p.expect_name("new column name")
        if name in RESERVED_WORDS:
            raise dsl_error(f"'{name}' is a reserved word and cannot be a column name")
        p.expect_op(")")
        p.expect_eof()
        program.steps.append(("apply", expr, name))
    elif kw == "group_by":
        if program.group_by is not None:
            raise dsl_error("at most one 'group_by' statement is allowed")
        p.expect_op("(")
        cols = []
        if p.at_op("["):
            p.next()
            cols.append(p.expect_name())
            while p.at_op(","):
                p.next()
                cols.append(p.expect_name())
            p.expect_op("]")
        else:
            cols.append(p.expect_name())
        p.expect_op(")")
        p.expect_eof()
        if len(set(cols)) != len(cols):
            raise dsl_error("duplicate column in group_by")
        program.group_by = cols
    elif kw == "window":
        if program.window is not None or program.window_param is not None:
            raise dsl_error("at most one 'window' statement is allowed")
        p.expect_op("(")
        if p.at("ident", "param") and p.peek(1).kind == "op" and p.peek(1).value == "(":
            p.next()
            call = p.parse_call("param")
            p.expect_op(")")
            p.expect_eof()
            program.window_param = call.args[0].value
            return
        num = p.next()
        unit = p.next()
        if (
            num.kind != "num"
            or not re.fullmatch(r"\d+", num.value)
            or unit.kind != "ident"
            or unit.value not in DURATION_UNITS
            or unit.pos != num.end
        ):
            raise dsl_error("invalid duration literal; expected e.g. 10m, 1h, 7d")
        p.expect_op(")")
        p.expect_eof()
        amount = int(num.value)
        if amount <= 0:
            raise dsl_error("window duration must be positive")
        program.window = amount * DURATION_UNITS[unit.value] * 1_000_000
        program.window_text = num.value + unit.value
    elif kw == "aggregate":
        if program.aggregates is not None:
            raise dsl_error("exactly one 'aggregate' statement is required")
        aggs = [parse_agg_entry(p)]
        while p.at_op(","):
            p.next()
            aggs.append(parse_agg_entry(p))
        p.expect_eof()
        aliases = [a[2] for a in aggs]
        dup = sorted({a for a in aliases if aliases.count(a) > 1})
        if dup:
            raise dsl_error(f"duplicate aggregate alias '{dup[0]}'")
        program.aggregates = aggs


def parse_agg_entry(p):
    fn = p.expect_ident("aggregate function")
    if fn not in AGG_FUNCTIONS:
        raise dsl_error(f"unknown aggregate function '{fn}'")
    p.expect_op("(")
    if p.at_op("*"):
        p.next()
        col = None
    else:
        col = p.expect_name("column name or '*'")
    p.expect_op(")")
    if not p.at("ident", "as"):
        raise dsl_error(f"expected 'as <alias>' after {fn}(...), found {describe(p.peek())}")
    p.next()
    alias = p.expect_ident("alias")
    return (fn, col, alias)


def validate_output_keys(program):
    reserved = set(program.group_by or [])
    if program.window is not None or program.window_param is not None:
        for key in WINDOW_KEYS:
            if key in reserved:
                raise dsl_error(f"group_by column '{key}' collides with window output field")
            reserved.add(key)
    for _, _, alias in program.aggregates:
        if alias in reserved:
            raise dsl_error(f"aggregate alias '{alias}' collides with another output field")
        reserved.add(alias)
    for calc in program.post_calcs:
        if calc.name in reserved or calc.name in WINDOW_KEYS:
            raise dsl_error(f"calc '{calc.name}' collides with another output field")
        reserved.add(calc.name)


# --------------------------------------------------------------------------- block format (schemas + pipeline)

def parse_block_program(text, cli_params):
    tokens = tokenize(text)

    def line_of(tok):
        return text.count("\n", 0, tok.pos) + 1

    def with_line(tok, fn, *args):
        try:
            return fn(*args)
        except MTLError as e:
            if e.kind == "bad_dsl" and not e.message.startswith("line "):
                raise dsl_error(f"line {line_of(tok)}: {e.message}")
            raise

    r = Parser(tokens=tokens)
    schemas = {}
    program = None
    while True:
        r.skip_nl()
        tok = r.peek()
        if tok.kind == "eof":
            break
        if tok.kind == "ident" and tok.value == "schema":
            decl = with_line(tok, parse_schema_block, r, line_of)
            if decl.name in schemas:
                raise dsl_error(f"line {line_of(tok)}: schema '{decl.name}' is defined more than once")
            schemas[decl.name] = decl
        elif tok.kind == "ident" and tok.value == "pipeline":
            if program is not None:
                raise dsl_error(f"line {line_of(tok)}: exactly one pipeline block is allowed")
            program = with_line(tok, parse_pipeline_block, r, with_line)
        else:
            raise dsl_error(f"line {line_of(tok)}: expected 'schema' or 'pipeline' block, found {describe(tok)}")
    if program is None:
        raise dsl_error("exactly one pipeline block is required")
    finalize_block_program(program, schemas, cli_params)
    return program


def parse_block_header_open(r):
    r.skip_nl()
    if not r.at_op("{"):
        raise dsl_error(f"expected '{{' but found {describe(r.peek())}")
    r.next()


def parse_schema_block(r, line_of):
    r.next()  # 'schema'
    name = r.expect_ident("schema name")
    base = None
    r.skip_nl()
    if r.at("ident", "extends"):
        r.next()
        r.skip_nl()
        base = r.expect_ident("base schema name")
        if r.at_op(","):
            raise dsl_error("multiple inheritance is not allowed")
    decl = SchemaDecl(name, base)
    parse_block_header_open(r)
    while True:
        r.skip_nl()
        if r.at_op("}"):
            r.next()
            return decl
        if r.at("eof"):
            raise dsl_error(f"schema '{name}' is missing a closing '}}'")
        toks = r.collect_statement()
        line = line_of(toks[0])
        try:
            decl.fields.append(parse_field(Parser(tokens=toks), line))
        except MTLError as e:
            if e.kind == "bad_dsl":
                raise dsl_error(f"line {line}: {e.message}")
            raise


def parse_field(p, line):
    name = p.expect_ident("field name")
    if name in RESERVED_WORDS:
        raise dsl_error(f"'{name}' is a reserved word and cannot be a field name")
    p.expect_op(":")
    typ = parse_type(p)
    expr = None
    if p.at_op("="):
        p.next()
        expr = p.parse_expr()
    if p.at_op("@"):
        stage = parse_stage(p)
        if stage != "pre":
            raise dsl_error("schema calculated fields are always @stage(pre)")
        if expr is None:
            raise dsl_error("@stage(...) is only allowed on calculated fields")
    p.expect_eof()
    return FieldDecl(name, typ, expr, line)


def parse_stage(p):
    p.expect_op("@")
    kw = p.expect_ident("'stage'")
    if kw != "stage":
        raise dsl_error(f"unknown annotation '@{kw}'")
    p.expect_op("(")
    stage = p.expect_ident("stage name")
    if stage not in ("pre", "post_agg"):
        raise dsl_error(f"unknown stage '{stage}'; expected pre or post_agg")
    p.expect_op(")")
    return stage


def parse_pipeline_block(r, with_line):
    r.next()  # 'pipeline'
    program = Program()
    program.block = True
    program.name = r.expect_ident("pipeline name")
    r.skip_nl()
    if not r.at("ident", "using"):
        raise dsl_error(f"expected 'using <SchemaName>' but found {describe(r.peek())}")
    r.next()
    r.skip_nl()
    program.schema_name = r.expect_ident("schema name")
    parse_block_header_open(r)
    params_seen = False
    while True:
        r.skip_nl()
        tok = r.peek()
        if r.at_op("}"):
            r.next()
            break
        if tok.kind == "eof":
            raise dsl_error(f"pipeline '{program.name}' is missing a closing '}}'")
        nxt = r.peek(1)
        if tok.kind == "ident" and tok.value == "params" and (nxt.kind == "nl" or (nxt.kind == "op" and nxt.value == "{")):
            if params_seen:
                raise dsl_error("at most one 'params' block is allowed")
            params_seen = True
            r.next()
            with_line(tok, parse_params_block, r, program, with_line)
            continue
        toks = r.collect_statement()
        with_line(toks[0], parse_pipeline_statement, program, Parser(tokens=toks))
    if program.aggregates is None:
        raise dsl_error("exactly one 'aggregate' statement is required")
    return program


def parse_params_block(r, program, with_line):
    parse_block_header_open(r)
    while True:
        r.skip_nl()
        if r.at_op("}"):
            r.next()
            return
        if r.at("eof"):
            raise dsl_error("params block is missing a closing '}'")
        toks = r.collect_statement()
        with_line(toks[0], parse_param_decls, Parser(tokens=toks), program)


def parse_param_decls(p, program):
    while True:
        name = p.expect_ident("parameter name")
        typ = None
        default = None
        if p.at_op(":"):
            p.next()
            typ = parse_type(p)
        if p.at_op("="):
            p.next()
            default = p.parse_unary()
            if not isinstance(default, Lit):
                raise dsl_error(f"default for parameter '{name}' must be a literal")
        if name in program.params:
            raise dsl_error(f"parameter '{name}' is declared more than once")
        program.params[name] = ParamDecl(name, typ, default)
        if p.at_op(","):
            p.next()
            if p.at("eof"):
                return
            continue
        p.expect_eof()
        return


def parse_pipeline_statement(program, p):
    if p.at("ident", "calc"):
        p.next()
        name = p.expect_ident("calc name")
        if name in RESERVED_WORDS:
            raise dsl_error(f"'{name}' is a reserved word and cannot be a field name")
        p.expect_op("=")
        expr = p.parse_expr()
        p.expect_op(":")
        typ = parse_type(p)
        if p.at_op("@"):
            stage = parse_stage(p)
        else:
            stage = "post_agg" if program.aggregates is not None else "pre"
        p.expect_eof()
        calc = CalcDecl(name, expr, typ, stage)
        if stage == "pre":
            program.steps.append(("calc", calc))
        else:
            program.post_calcs.append(calc)
        return
    parse_statement(program, p)


def resolve_schemas(decls, deferred):
    for name, decl in decls.items():
        seen = [name]
        cur = decl.base
        while cur is not None:
            if cur not in decls:
                raise dsl_error(f"schema '{seen[-1]}' extends unknown schema '{cur}'")
            if cur in seen:
                raise dsl_error(f"circular schema inheritance: {' -> '.join(seen + [cur])}")
            seen.append(cur)
            cur = decls[cur].base

    resolved = {}

    def build(name):
        if name in resolved:
            return resolved[name]
        decl = decls[name]
        fields = {}
        if decl.base is not None:
            fields = {k: SchemaField(v.typ, v.expr) for k, v in build(decl.base)[0].items()}
        declared = set()
        for fd in decl.fields:
            where = f"line {fd.line}: "
            if fd.name in declared:
                raise dsl_error(f"{where}field '{fd.name}' is declared more than once in schema '{name}'")
            declared.add(fd.name)
            expr = fd.expr
            if expr is not None:
                for ref in col_refs(expr):
                    if ref == fd.name:
                        raise dsl_error(f"{where}calculated field '{fd.name}' cannot reference itself")
                    if ref not in fields:
                        later = any(f.name == ref for f in decl.fields)
                        kind = "forward reference to" if later else "unknown field"
                        raise dsl_error(f"{where}calculated field '{fd.name}' has {kind} '{ref}'")
                for n in walk(expr):
                    if isinstance(n, Call) and n.name in ("lag", "lead"):
                        raise dsl_error(f"{where}{n.name}() is only allowed in @stage(post_agg) calcs")
            old = fields.get(fd.name)
            if old is not None:
                if not (old.typ == fd.typ or (old.typ == INT and fd.typ == FLOAT)):
                    deferred.append(type_error(
                        f"schema '{name}' illegally overrides field '{fd.name}' from {old.typ} to {fd.typ}"))
                if expr is None:
                    expr = old.expr
            fields[fd.name] = SchemaField(fd.typ, expr)
        order = []
        state = {}

        def visit(fname, path):
            if state.get(fname) == "done":
                return
            if state.get(fname) == "active":
                raise dsl_error(f"circular calculated fields in schema '{name}': {' -> '.join(path + [fname])}")
            state[fname] = "active"
            for ref in col_refs(fields[fname].expr):
                if ref in fields and fields[ref].expr is not None:
                    visit(ref, path + [fname])
            state[fname] = "done"
            order.append(fname)

        for fname, f in fields.items():
            if f.expr is not None:
                visit(fname, [])
        resolved[name] = (fields, order)
        return resolved[name]

    for name in decls:
        build(name)
    return resolved


def check_expr_structure(node, params, post):
    for n in walk(node):
        if not isinstance(n, Call):
            continue
        if n.name == "param":
            if n.args[0].value not in params:
                raise dsl_error(f"unknown parameter '{n.args[0].value}'")
        elif n.name in ("lag", "lead"):
            if not post:
                raise dsl_error(f"{n.name}() is only allowed in @stage(post_agg) calcs")
            if len(n.args) == 2:
                k = n.args[1]
                if isinstance(k, Lit):
                    if k.typ == INT and k.value <= 0:
                        raise dsl_error(f"{n.name}() offset must be a positive integer")
                elif not (isinstance(k, Call) and k.name == "param"):
                    raise dsl_error(f"{n.name}() offset must be a positive integer literal or an int param")


def finalize_block_program(program, schemas, cli_params):
    if program.schema_name not in schemas:
        raise dsl_error(f"pipeline uses unknown schema '{program.schema_name}'")
    resolved = resolve_schemas(schemas, program.deferred_errors)
    fields, order = resolved[program.schema_name]
    program.schema_fields = fields
    program.schema_calc_order = order
    params = program.params

    for decl in params.values():
        if decl.default is None and decl.name not in cli_params:
            raise dsl_error(f"parameter '{decl.name}' has no default and was not provided via --param")

    for f in fields.values():
        if f.expr is not None:
            check_expr_structure(f.expr, params, post=False)
    for step in program.steps:
        expr = step[1].expr if step[0] == "calc" else step[1]
        check_expr_structure(expr, params, post=False)
    for calc in program.post_calcs:
        check_expr_structure(calc.expr, params, post=True)
    if program.window_param is not None and program.window_param not in params:
        raise dsl_error(f"unknown parameter '{program.window_param}'")

    pre_calcs = [s[1] for s in program.steps if s[0] == "calc"]
    apply_names = {s[2] for s in program.steps if s[0] == "apply"}
    aliases = {a[2] for a in program.aggregates}
    seen = set()
    for calc in pre_calcs + program.post_calcs:
        if calc.name in seen:
            raise dsl_error(f"calc '{calc.name}' is declared more than once")
        seen.add(calc.name)
        if calc.stage == "pre" and (calc.name in fields or calc.name in apply_names):
            raise dsl_error(f"calc '{calc.name}' collides with an existing field")
    validate_output_keys(program)

    # Pre-stage calcs run before every other step, unless they depend on an apply(...) column,
    # in which case they run at their position in the pipeline body.
    available = set(fields)
    hoisted = set()
    for calc in pre_calcs:
        if all(ref in available for ref in col_refs(calc.expr)):
            hoisted.add(calc.name)
            available.add(calc.name)
    execution = [s for s in program.steps if s[0] == "calc" and s[1].name in hoisted]
    later_calcs = {c.name for c in pre_calcs} | {c.name for c in program.post_calcs}
    for step in program.steps:
        if step[0] == "calc":
            calc = step[1]
            if calc.name in hoisted:
                continue
            for ref in col_refs(calc.expr):
                if ref in available:
                    continue
                if ref in aliases:
                    raise dsl_error(f"pre-stage calc '{calc.name}' cannot reference aggregate alias '{ref}'")
                if ref in later_calcs:
                    raise dsl_error(f"calc '{calc.name}' references '{ref}' before it is defined")
                raise dsl_error(f"calc '{calc.name}' references unknown field '{ref}'")
            available.add(calc.name)
        elif step[0] == "apply":
            available.add(step[2])
        execution.append(step)
    program.order = execution

    post_names = [c.name for c in program.post_calcs]
    for idx, calc in enumerate(program.post_calcs):
        for ref in col_refs(calc.expr):
            if ref in post_names[idx:]:
                raise dsl_error(f"calc '{calc.name}' references '{ref}' before it is defined")


# --------------------------------------------------------------------------- CSV loading

NUMBER_RE = re.compile(r"[+-]?(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?|[+-]?(?:inf|infinity|nan)", re.IGNORECASE)
INT_RE = re.compile(r"[+-]?\d+")


def parse_number(s):
    s = s.strip()
    if not NUMBER_RE.fullmatch(s):
        raise ValueError(s)
    return float(s)


def make_ts_parser(tz, fmt):
    def parse(s):
        s = s.strip()
        if fmt:
            dt = datetime.strptime(s, fmt)
        else:
            t = s[:-1] + "+00:00" if s[-1:] in ("Z", "z") else s
            dt = datetime.fromisoformat(t)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=tz)
        return dt.astimezone(timezone.utc)

    return parse


def infer_type(values, parse_ts):
    present = [v.strip() for v in values if v.strip() != ""]
    if not present:
        return STR
    if all(INT_RE.fullmatch(v) for v in present):
        return INT
    if all(NUMBER_RE.fullmatch(v) for v in present):
        return FLOAT
    if all(v.lower() in ("true", "false") for v in present):
        return BOOL
    if all(":" in v for v in present):
        try:
            for v in present:
                parse_ts(v)
            return TS
        except (ValueError, OverflowError):
            pass
    return STR


def convert(value, typ, parse_ts):
    if typ == STR:
        return value
    v = value.strip()
    if v == "":
        return None
    if typ == FLOAT:
        return parse_number(v)
    if typ == INT:
        return int(v)
    if typ == BOOL:
        low = v.lower()
        if low not in ("true", "false"):
            raise ValueError(v)
        return low == "true"
    return parse_ts(v)


def load_csv(path, parse_ts, required=REQUIRED_COLUMNS, keep_extra=True):
    try:
        with open(path, "r", encoding="utf-8-sig", newline="") as f:
            data = f.read()
    except FileNotFoundError:
        raise io_error(f"CSV file not found: {path}")
    except IsADirectoryError:
        raise io_error(f"CSV path is a directory: {path}")
    except UnicodeDecodeError:
        raise io_error(f"CSV file is not valid UTF-8: {path}")
    except OSError as e:
        raise io_error(f"cannot read CSV file {path}: {e.strerror or e}")
    try:
        records = list(csv.reader(io.StringIO(data, newline="")))
    except csv.Error as e:
        raise io_error(f"malformed CSV: {e}")
    if not records:
        raise io_error("CSV file is empty; a header row is required")
    header = [h.strip() for h in records[0]]
    if len(set(header)) != len(header):
        raise io_error("CSV header contains duplicate column names")
    missing = [c for c in required if c not in header]
    if missing:
        raise io_error(f"CSV is missing required column(s): {', '.join(missing)}")
    body = []
    for lineno, rec in enumerate(records[1:], 2):
        if not rec or (len(rec) == 1 and rec[0].strip() == ""):
            continue
        if len(rec) != len(header):
            raise io_error(f"CSV row {lineno} has {len(rec)} fields, expected {len(header)}")
        body.append(rec)

    schema = {}
    columns = {}
    for idx, name in enumerate(header):
        if name not in required and not keep_extra:
            continue
        raw = [rec[idx] for rec in body]
        typ = required.get(name) or infer_type(raw, parse_ts)
        schema[name] = typ
        converted = []
        for value in raw:
            try:
                converted.append(convert(value, typ, parse_ts))
            except (ValueError, OverflowError):
                raise type_error(f"column '{name}' has invalid {typ} value {value!r}")
        columns[name] = converted
    rows = [{name: columns[name][i] for name in schema} for i in range(len(body))]
    return schema, rows


# --------------------------------------------------------------------------- compile (type check + evaluator)

class Context:
    def __init__(self, tz, parse_ts, params, strict):
        self.tz = tz
        self.parse_ts = parse_ts
        self.params = params  # name -> (type, value)
        self.strict = strict
        self.post = False  # compiling a @stage(post_agg) calc


class PostRow:
    """A view of one output row that lets lag()/lead() reach its neighbours."""

    __slots__ = ("rows", "index")

    def __init__(self, rows, index):
        self.rows = rows
        self.index = index

    def __getitem__(self, name):
        return self.rows[self.index][name]


def type_name(t):
    return "number" if t in NUMERIC else t


def check_finite(x):
    if isinstance(x, float) and not math.isfinite(x):
        raise runtime_error("expression produced a non-finite number")
    return x


def round_half_away(x, digits):
    if isinstance(x, int) and digits >= 0:
        return x
    if isinstance(x, float) and not math.isfinite(x):
        raise runtime_error("cannot round a non-finite number")
    if digits > 400:
        return x
    if digits < -400:
        return 0 if isinstance(x, int) else 0.0
    with localcontext() as ctx:
        ctx.prec = 1000
        try:
            d = Decimal(repr(x)).quantize(Decimal(1).scaleb(-digits), rounding=ROUND_HALF_UP)
        except InvalidOperation:
            raise runtime_error("round() failed")
    if isinstance(x, int):
        return int(d)
    result = float(d)
    if result == 0:
        result = 0.0
    return check_finite(result)


def arith(op, a, b):
    try:
        if op == "+":
            r = a + b
        elif op == "-":
            r = a - b
        elif op == "*":
            r = a * b
        elif op == "/":
            if b == 0:
                raise runtime_error("division by zero")
            r = a / b
        else:
            if b == 0:
                raise runtime_error("modulo by zero")
            r = a % b
    except OverflowError:
        raise runtime_error("numeric overflow")
    return check_finite(r)


COMPARE = {
    "<": lambda a, b: a < b,
    "<=": lambda a, b: a <= b,
    ">": lambda a, b: a > b,
    ">=": lambda a, b: a >= b,
    "==": lambda a, b: a == b,
    "!=": lambda a, b: a != b,
}

STRING_TESTS = {
    "starts_with": lambda s, x: s.startswith(x),
    "ends_with": lambda s, x: s.endswith(x),
    "contains": lambda s, x: x in s,
}


def is_constant_string(node, ctx):
    if isinstance(node, Lit):
        return node.typ == STR
    if isinstance(node, Call) and node.name == "param":
        return ctx.params.get(node.args[0].value, (None,))[0] == STR
    return False


def compile_expr(node, schema, ctx):
    """Type-check `node` against `schema`; return (type, evaluator(row))."""
    if isinstance(node, Lit):
        value = node.value
        return node.typ, lambda row: value

    if isinstance(node, Col):
        if node.name not in schema:
            raise type_error(f"unknown column '{node.name}'")
        name = node.name
        return schema[name], lambda row: row[name]

    if isinstance(node, Cast):
        return compile_cast(node, schema, ctx)

    if isinstance(node, Unary):
        t, f = compile_expr(node.operand, schema, ctx)
        if node.op == "!":
            if t != BOOL:
                raise type_error(f"'!' requires a boolean operand, got {type_name(t)}")
            return BOOL, lambda row: not f(row)
        if t not in NUMERIC:
            raise type_error(f"unary '-' requires a numeric operand, got {type_name(t)}")

        def neg(row):
            v = f(row)
            return None if v is None else -v

        return t, neg

    if isinstance(node, Call):
        return compile_call(node, schema, ctx)

    op = node.op
    if op == "in":
        if not is_constant_string(node.left, ctx):
            raise type_error("'in' requires a string literal on the left (<string_literal> in <string_col>)")
        if not isinstance(node.right, Col):
            raise type_error("'in' requires a string column on the right (<string_literal> in <string_col>)")
        lt, lf = compile_expr(node.left, schema, ctx)
        rt, rf = compile_expr(node.right, schema, ctx)
        if rt != STR:
            raise type_error(f"'in' requires a string column on the right, column '{node.right.name}' is {type_name(rt)}")

        def contains(row):
            v = rf(row)
            needle = lf(row)
            return v is not None and needle is not None and needle in v

        return BOOL, contains

    if op in STRING_OPS:
        return compile_string_test(op, node.left, node.right, schema, ctx)

    lt, lf = compile_expr(node.left, schema, ctx)
    rt, rf = compile_expr(node.right, schema, ctx)

    if op in ("&", "|"):
        if lt != BOOL or rt != BOOL:
            raise type_error(f"'{op}' requires boolean operands, got {type_name(lt)} and {type_name(rt)}")
        if op == "&":
            return BOOL, lambda row: bool(lf(row)) and bool(rf(row))
        return BOOL, lambda row: bool(lf(row)) or bool(rf(row))

    if op in COMPARISON_OPS:
        ok = (
            (lt in NUMERIC and rt in NUMERIC)
            or (lt == rt and lt in (STR, TS))
            or (lt == rt == BOOL and op in ("==", "!="))
        )
        if not ok:
            raise type_error(f"cannot compare {type_name(lt)} with {type_name(rt)} using '{op}'")
        cmp = COMPARE[op]

        def compare(row):
            a = lf(row)
            if a is None:
                return False
            b = rf(row)
            if b is None:
                return False
            return cmp(a, b)

        return BOOL, compare

    # arithmetic
    if lt not in NUMERIC or rt not in NUMERIC:
        raise type_error(f"'{op}' requires numeric operands, got {type_name(lt)} and {type_name(rt)}")
    result_type = FLOAT if op == "/" or FLOAT in (lt, rt) else INT

    def evaluate(row):
        a = lf(row)
        if a is None:
            return None
        b = rf(row)
        if b is None:
            return None
        return arith(op, a, b)

    return result_type, evaluate


def compile_string_test(op, left, right, schema, ctx):
    lt, lf = compile_expr(left, schema, ctx)
    rt, rf = compile_expr(right, schema, ctx)
    if lt != STR or rt != STR:
        raise type_error(f"{op} requires string operands, got {type_name(lt)} and {type_name(rt)}")
    test = STRING_TESTS[op]

    def evaluate(row):
        s = lf(row)
        if s is None:
            return False
        x = rf(row)
        if x is None:
            return False
        return test(s, x)

    return BOOL, evaluate


def is_missing(v):
    return v is None or (isinstance(v, float) and math.isnan(v))


def compile_call(node, schema, ctx):
    name = node.name
    if name == "param":
        pname = node.args[0].value
        if pname not in ctx.params:
            raise dsl_error(f"unknown parameter '{pname}'")
        t, value = ctx.params[pname]
        return t, lambda row: value
    if name in ("lag", "lead"):
        return compile_shift(node, schema, ctx)
    if name in STRING_OPS:
        return compile_string_test(name, node.args[0], node.args[1], schema, ctx)
    if name == "coalesce":
        compiled = [compile_expr(a, schema, ctx) for a in node.args]
        types = [t for t, _ in compiled]
        if all(t in NUMERIC for t in types):
            result_type = FLOAT if FLOAT in types else INT
        elif all(t == types[0] for t in types):
            result_type = types[0]
        else:
            raise type_error(f"coalesce() arguments must have matching types, got {', '.join(map(type_name, types))}")
        fns = [f for _, f in compiled]
        widen = result_type == FLOAT

        def first_valid(row):
            for f in fns:
                v = f(row)
                if not is_missing(v):
                    return float(v) if widen else v
            return None

        return result_type, first_valid

    compiled = [compile_expr(a, schema, ctx) for a in node.args]
    t, f = compiled[0]
    if name == "len":
        if t != STR:
            raise type_error(f"len() requires a string argument, got {type_name(t)}")

        def length(row):
            v = f(row)
            return None if v is None else len(v)

        return INT, length
    if name in ("day", "month", "year"):
        if t != TS:
            raise type_error(f"{name}() requires a timestamp argument, got {type_name(t)}")
        attr = name
        tz = ctx.tz

        def part(row):
            v = f(row)
            return None if v is None else getattr(v.astimezone(tz), attr)

        return INT, part
    # round
    if t not in NUMERIC:
        raise type_error(f"round() requires a numeric argument, got {type_name(t)}")
    if len(compiled) == 2:
        dt, df = compiled[1]
        if dt != INT:
            raise type_error(f"round() digits must be an integer, got {type_name(dt)}")
    else:
        df = lambda row: 0  # noqa: E731

    def rounder(row):
        v = f(row)
        if v is None:
            return None
        d = df(row)
        if d is None:
            return None
        return round_half_away(v, d)

    return t, rounder


def compile_shift(node, schema, ctx):
    name = node.name
    if not ctx.post:
        raise dsl_error(f"{name}() is only allowed in @stage(post_agg) calcs")
    et, ef = compile_expr(node.args[0], schema, ctx)
    if len(node.args) == 2:
        kt, kf = compile_expr(node.args[1], schema, ctx)
        if kt != INT:
            raise type_error(f"{name}() offset must be an int, got {type_name(kt)}")
    else:
        kf = lambda row: 1  # noqa: E731
    sign = -1 if name == "lag" else 1

    def shifted(row):
        k = kf(row)
        if k is None or k <= 0:
            raise runtime_error(f"{name}() offset must be a positive integer, got {k}")
        j = row.index + sign * k
        if 0 <= j < len(row.rows):
            return ef(PostRow(row.rows, j))
        return None

    return et, shifted


def cast_value(v, src, dst, ctx):
    """Convert a non-null value; raises ValueError when the conversion is impossible."""
    if src == dst:
        return v
    if dst == STR:
        if src == BOOL:
            return "true" if v else "false"
        if src == TS:
            return format_ts(v)
        if src == FLOAT:
            check_finite(v)
            return repr(0.0 if v == 0 else v)
        return str(v)
    if src == STR:
        s = v.strip()
        if dst == INT:
            if not INT_RE.fullmatch(s):
                raise ValueError(v)
            return int(s)
        if dst == FLOAT:
            x = parse_number(s)
            if not math.isfinite(x):
                raise ValueError(v)
            return x
        if dst == BOOL:
            if s.lower() not in ("true", "false"):
                raise ValueError(v)
            return s.lower() == "true"
        return ctx.parse_ts(s)
    if dst == TS:
        return EPOCH + timedelta(seconds=v)
    if src == TS:
        seconds = (v - EPOCH) / timedelta(seconds=1)
        return math.floor(seconds) if dst == INT else seconds
    if dst == BOOL:
        return v != 0
    if dst == INT:
        if not math.isfinite(v):
            raise ValueError(v)
        return int(v)
    return float(v)


def compile_cast(node, schema, ctx):
    src, f = compile_expr(node.expr, schema, ctx)
    dst = node.typ
    if (src == BOOL and dst == TS) or (src == TS and dst == BOOL):
        raise type_error(f"cannot cast {type_name(src)} to {dst}")

    def evaluate(row):
        v = f(row)
        if v is None:
            return None
        try:
            return cast_value(v, src, dst, ctx)
        except (ValueError, OverflowError, TypeError):
            if ctx.strict:
                raise runtime_error(f"cannot cast {v!r} to {dst}")
            return None

    return dst, evaluate


def declared_conv(declared, inferred, what):
    """Check an expression's inferred type against its declared type; return a value converter."""
    if declared == inferred:
        return None
    if declared == FLOAT and inferred == INT:
        return lambda v: None if v is None else float(v)
    raise type_error(f"{what} is declared {declared} but its expression has type {inferred}")


# --------------------------------------------------------------------------- aggregation

def agg_sum(vals):
    try:
        total = 0
        for v in vals:
            total += v
    except OverflowError:
        raise runtime_error("numeric overflow in sum")
    return total


def agg_mean(vals):
    return agg_sum(vals) / len(vals)


def agg_var(vals):
    mean = agg_mean(vals)
    acc = 0.0
    for v in vals:
        d = v - mean
        acc += d * d
    return acc / len(vals)


def agg_median(vals):
    s = sorted(vals)
    n = len(s)
    mid = n // 2
    if n % 2:
        return s[mid]
    return (s[mid - 1] + s[mid]) / 2


AGG_IMPL = {
    "sum": agg_sum,
    "average": agg_mean,
    "median": agg_median,
    "var": agg_var,
    "std": lambda vals: math.sqrt(check_finite(agg_var(vals))),
    "min": min,
    "max": max,
}


def agg_type(fn, col_type):
    if fn == "count":
        return INT
    if fn in ("sum", "min", "max"):
        return col_type
    return FLOAT


def compute_aggregate(fn, col, rows):
    if col is None:
        return len(rows)
    vals = [r[col] for r in rows if r[col] is not None]
    if fn == "count":
        return len(vals)
    if any(isinstance(v, float) and math.isnan(v) for v in vals):
        raise runtime_error(f"{fn}({col}) produced a non-finite number")
    if not vals:
        return None
    try:
        result = AGG_IMPL[fn](vals)
    except OverflowError:
        raise runtime_error(f"numeric overflow in {fn}({col})")
    if isinstance(result, float) and not math.isfinite(result):
        raise runtime_error(f"{fn}({col}) produced a non-finite number")
    return result


# --------------------------------------------------------------------------- params

def parse_param_text(raw, typ, parse_ts):
    """Parse a --param value (or a string default) into `typ`; raises ValueError."""
    if typ == STR:
        return raw
    s = raw.strip()
    if typ == INT:
        if not INT_RE.fullmatch(s):
            raise ValueError(raw)
        return int(s)
    if typ == FLOAT:
        x = parse_number(s)
        if not math.isfinite(x):
            raise ValueError(raw)
        return x
    if typ == BOOL:
        if s.lower() not in ("true", "false"):
            raise ValueError(raw)
        return s.lower() == "true"
    return parse_ts(s)


def resolve_params(program, cli_params, parse_ts):
    values = {}
    for decl in program.params.values():
        typ = decl.typ
        if typ is None:
            typ = decl.default.typ if decl.default is not None else STR
        if decl.name in cli_params:
            raw = cli_params[decl.name]
            try:
                value = parse_param_text(raw, typ, parse_ts)
            except (ValueError, OverflowError):
                raise type_error(f"--param {decl.name}={raw!r} is not a valid {typ}")
        else:
            lit = decl.default
            if lit.typ == typ:
                value = lit.value
            elif typ == FLOAT and lit.typ == INT:
                value = float(lit.value)
            elif typ == TS and lit.typ == STR:
                try:
                    value = parse_ts(lit.value)
                except (ValueError, OverflowError):
                    raise type_error(f"default for parameter '{decl.name}' is not a valid timestamp")
            else:
                raise type_error(f"default for parameter '{decl.name}' must be {typ}, got {lit.typ}")
        values[decl.name] = (typ, value)
    return values


# --------------------------------------------------------------------------- planning & execution

class Plan:
    def __init__(self):
        self.prelude = []  # (name, evaluator, converter) for schema calcs
        self.steps = []  # ("filter", f, None, None) | ("set", f, name, converter)
        self.group_cols = []
        self.window = None
        self.aggregates = []
        self.post = []  # (name, evaluator, converter)


def compile_plan(program, schema, ctx):
    schema = dict(schema)
    plan = Plan()
    if program.block:
        for d in program.deferred_errors:
            raise d
        fields = program.schema_fields
        for name in program.schema_calc_order:
            f = fields[name]
            t, fn = compile_expr(f.expr, schema, ctx)
            plan.prelude.append((name, fn, declared_conv(f.typ, t, f"calculated field '{name}'")))

    for step in program.order:
        if step[0] == "calc":
            calc = step[1]
            t, f = compile_expr(calc.expr, schema, ctx)
            conv = declared_conv(calc.typ, t, f"calc '{calc.name}'")
            schema[calc.name] = calc.typ
            plan.steps.append(("set", f, calc.name, conv))
            continue
        t, f = compile_expr(step[1], schema, ctx)
        if step[0] == "filter":
            if t != BOOL:
                raise type_error(f"filter expression must be boolean, got {type_name(t)}")
            plan.steps.append(("filter", f, None, None))
        else:
            schema[step[2]] = t
            plan.steps.append(("set", f, step[2], None))

    group_cols = program.group_by or []
    for c in group_cols:
        if c not in schema:
            raise type_error(f"unknown group_by column '{c}'")
    plan.group_cols = group_cols

    window = program.window
    if program.window_param is not None:
        t, value = ctx.params[program.window_param]
        m = DURATION_RE.fullmatch(value) if t == STR else None
        if not m or int(m.group(1)) <= 0:
            raise type_error(f"parameter '{program.window_param}' is not a valid window duration (e.g. 10m, 1h, 7d)")
        window = int(m.group(1)) * DURATION_UNITS[m.group(2)] * 1_000_000
    if window is not None:
        if schema.get("timestamp") != TS:
            raise type_error("window requires 'timestamp' to be a timestamp column")
    plan.window = window

    out_schema = {}
    if window is not None:
        out_schema["window_start"] = TS
        out_schema["window_end"] = TS
    for c in group_cols:
        out_schema[c] = schema[c]
    for fn, col, alias in program.aggregates:
        if col is None:
            if fn != "count":
                raise type_error(f"{fn}(*) is not allowed; only count(*) accepts '*'")
            out_schema[alias] = INT
            continue
        if col not in schema:
            raise type_error(f"unknown column '{col}' in {fn}({col})")
        if schema[col] not in NUMERIC:
            raise type_error(f"{fn}({col}) requires a numeric column, '{col}' is {type_name(schema[col])}")
        out_schema[alias] = agg_type(fn, schema[col])
    plan.aggregates = sorted(program.aggregates, key=lambda a: a[2])

    ctx.post = True
    try:
        for calc in program.post_calcs:
            t, f = compile_expr(calc.expr, out_schema, ctx)
            conv = declared_conv(calc.typ, t, f"calc '{calc.name}'")
            out_schema[calc.name] = calc.typ
            plan.post.append((calc.name, f, conv))
    finally:
        ctx.post = False
    return plan


def format_ts(dt):
    dt = dt.astimezone(timezone.utc)
    s = dt.strftime("%Y-%m-%dT%H:%M:%S")
    if dt.microsecond:
        s += f".{dt.microsecond:06d}"
    return s + "Z"


def to_json_value(v):
    if isinstance(v, datetime):
        return format_ts(v)
    if isinstance(v, float):
        if not math.isfinite(v):
            raise runtime_error("result contains a non-finite number")
        return 0.0 if v == 0 else v
    return v


def sort_key(value):
    if value is None:
        return (0, 0)
    return (1, value)


def execute(plan, rows):
    for r in rows:
        for name, f, conv in plan.prelude:
            v = f(r)
            r[name] = conv(v) if conv else v

    for kind, f, name, conv in plan.steps:
        if kind == "filter":
            rows = [r for r in rows if f(r)]
        else:
            for r in rows:
                v = f(r)
                r[name] = conv(v) if conv else v

    group_cols = plan.group_cols
    width = plan.window
    windowed = width is not None
    out = []
    if not windowed and not group_cols:
        obj = {}
        for fn, col, alias in plan.aggregates:
            obj[alias] = compute_aggregate(fn, col, rows)
        out.append(obj)
    else:
        buckets = {}
        for r in rows:
            if windowed:
                ts = r["timestamp"]
                if ts is None:
                    continue
                us = (ts - EPOCH) // ONE_US
                start = (us // width) * width
            else:
                start = None
            key = (start, tuple(r[c] for c in group_cols))
            buckets.setdefault(key, []).append(r)

        def bucket_order(key):
            start, gvals = key
            return (start if start is not None else 0, tuple(sort_key(v) for v in gvals))

        for key in sorted(buckets, key=bucket_order):
            start, gvals = key
            members = buckets[key]
            obj = {}
            if windowed:
                obj["window_start"] = EPOCH + timedelta(microseconds=start)
                obj["window_end"] = EPOCH + timedelta(microseconds=start + width)
            for c, v in zip(group_cols, gvals):
                obj[c] = v
            for fn, col, alias in plan.aggregates:
                obj[alias] = compute_aggregate(fn, col, members)
            out.append(obj)

    for name, f, conv in plan.post:
        values = []
        for i in range(len(out)):
            v = f(PostRow(out, i))
            values.append(conv(v) if conv else v)
        for obj, v in zip(out, values):
            obj[name] = v

    keys = []
    if windowed:
        keys.extend(WINDOW_KEYS)
    keys.extend(group_cols)
    keys.extend(alias for _, _, alias in plan.aggregates)
    keys.extend(sorted(name for name, _, _ in plan.post))
    result = [{k: to_json_value(obj[k]) for k in keys} for obj in out]
    if not windowed and not group_cols:
        return result[0]
    return result


# --------------------------------------------------------------------------- CLI

class ArgParser(argparse.ArgumentParser):
    def error(self, message):
        raise io_error(f"invalid arguments: {message}")


def resolve_tz(name):
    if name in ("UTC", "Z", "Etc/UTC"):
        return timezone.utc
    if ZoneInfo is None:
        raise io_error(f"timezone support unavailable for '{name}'")
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError, OSError):
        raise io_error(f"unknown timezone '{name}'")


def read_dsl(path):
    if path == "-":
        try:
            return sys.stdin.read()
        except (OSError, UnicodeDecodeError) as e:
            raise io_error(f"cannot read DSL from STDIN: {e}")
    try:
        with open(path, "r", encoding="utf-8-sig") as f:
            return f.read()
    except FileNotFoundError:
        raise io_error(f"DSL file not found: {path}")
    except IsADirectoryError:
        raise io_error(f"DSL path is a directory: {path}")
    except UnicodeDecodeError:
        raise io_error(f"DSL file is not valid UTF-8: {path}")
    except OSError as e:
        raise io_error(f"cannot read DSL file {path}: {e.strerror or e}")


def parse_cli_params(groups):
    params = {}
    for group in groups or []:
        for item in group:
            key, sep, value = item.partition("=")
            key = key.strip()
            if not sep or not key:
                raise io_error(f"invalid arguments: --param expects key=value, got {item!r}")
            params[key] = value
    return params


def main(argv=None):
    parser = ArgParser(prog="mtl.py", description="Run an MTL pipeline over a CSV of sales events.")
    parser.add_argument("--csv", required=True)
    parser.add_argument("--dsl", required=True)
    parser.add_argument("--out", default=None)
    parser.add_argument("--tz", default="UTC")
    parser.add_argument("--timestamp-format", dest="timestamp_format", default=None)
    parser.add_argument("--strict", action="store_true")
    parser.add_argument("--param", action="append", nargs="+", default=[], metavar="KEY=VALUE")
    args = parser.parse_args(argv)

    tz = resolve_tz(args.tz)
    parse_ts = make_ts_parser(tz, args.timestamp_format)
    cli_params = parse_cli_params(args.param)
    program = parse_program(read_dsl(args.dsl), cli_params)
    ctx = Context(tz, parse_ts, {}, args.strict)
    if program.block:
        ctx.params = resolve_params(program, cli_params, parse_ts)
        env = {name: f.typ for name, f in program.schema_fields.items()}
        plan = compile_plan(program, env, ctx)
        physical = {name: f.typ for name, f in program.schema_fields.items() if f.expr is None}
        _, rows = load_csv(args.csv, parse_ts, required=physical, keep_extra=False)
    else:
        schema, rows = load_csv(args.csv, parse_ts)
        plan = compile_plan(program, schema, ctx)
    result = execute(plan, rows)
    try:
        text = json.dumps(result, indent=2, ensure_ascii=False, allow_nan=False) + "\n"
    except ValueError:
        raise runtime_error("result contains a non-finite number")

    if args.out and args.out != "-":
        try:
            with open(args.out, "w", encoding="utf-8") as f:
                f.write(text)
        except OSError as e:
            raise io_error(f"cannot write output file {args.out}: {e.strerror or e}")
    else:
        sys.stdout.write(text)
        sys.stdout.flush()
    return 0


def entry():
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass
    try:
        code = main()
    except MTLError as e:
        msg = " ".join(str(e.message).split())
        sys.stderr.write(f"ERROR:{e.kind}:{msg}\n")
        code = EXIT_CODES[e.kind]
    except RecursionError:
        sys.stderr.write("ERROR:bad_dsl:expression is nested too deeply\n")
        code = 1
    except Exception as e:  # unexpected failure during execution
        msg = " ".join(f"{type(e).__name__}: {e}".split())
        sys.stderr.write(f"ERROR:runtime_error:{msg}\n")
        code = 4
    sys.exit(code)


if __name__ == "__main__":
    entry()
