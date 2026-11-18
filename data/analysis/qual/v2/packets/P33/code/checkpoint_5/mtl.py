#!/usr/bin/env python3
"""MTL: run a small versioned pipeline DSL (schemas, params, calcs, filter/apply/group_by/window/aggregate, UDFs) over
sales events read from CSV, TSV (optionally gzipped) and Parquet files, either from --input paths or from multiple named
sources declared in an ingest config (YAML/JSON) and combined with joins. Runs can be resumed from file-level
checkpoints kept in a state directory and can emit structured run metadata."""

import argparse
import csv
import glob
import gzip
import hashlib
import io
import json
import math
import os
import re
import struct
import sys
import tempfile
import uuid
import zlib
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP, localcontext

try:
    from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
except ImportError:  # pragma: no cover
    ZoneInfo = None
    ZoneInfoNotFoundError = Exception

EXIT_CODES = {"bad_dsl": 1, "type_error": 2, "bad_io": 3, "runtime_error": 4, "config_error": 5, "artifact_error": 6}

MTL_RUNTIME_VERSION = "1.5.0"
SUPPORTED_MAJOR = 1
SUPPORTED_MINOR = 5


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


def config_error(msg):
    return MTLError("config_error", msg)


def artifact_error(msg):
    """Version / resume-state errors (exit 6)."""
    return MTLError("artifact_error", msg)


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
  | (?P<op><=|>=|==|!=|<|>|!|&|\||\+|-|\*|/|%|\(|\)|\[|\]|,|\{|\}|:|=|@|\.)
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
UDFS = {}  # name -> Udf, registered from --udf files before the DSL is parsed
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
            if self.at_op(".") and self.peek(1).kind == "ident":
                self.next()
                return Col(f"{tok.value}.{self.next().value}")
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
        if name not in FUNCTION_ARITY and name not in UDFS:
            raise dsl_error(f"unknown function '{name}'")
        self.expect_op("(")
        args = []
        if not self.at_op(")"):
            args.append(self.parse_expr())
            while self.at_op(","):
                self.next()
                args.append(self.parse_expr())
        self.expect_op(")")
        if name in UDFS:
            lo = hi = len(UDFS[name].args)
        else:
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

    def peek_after_nl(self, offset):
        """The first non-newline token at or after position i + offset."""
        j = min(self.i + offset, len(self.tokens) - 1)
        while self.tokens[j].kind == "nl":
            j += 1
        return self.tokens[j]

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
        # multi-source additions
        self.sources = None  # [(source_name, alias)] from a 'sources { ... }' block
        self.with_blocks = []  # [(alias, [("filter", expr) | ("calc", CalcDecl)])]
        self.with_errors = []  # type errors found in alias-scoped 'with' blocks
        self.joins = []  # [JoinDecl]
        self.resolved_schemas = {}  # schema name -> (fields, calc order)


class JoinDecl:
    def __init__(self, left, right):
        self.left = left
        self.right = right
        self.on = None
        self.on_keys = []  # equality conjuncts as written, e.g. "W.item==P.item" (for run metadata)
        self.within = None  # band width in microseconds
        self.within_text = None
        self.jtype = None
        self.project = None  # [(expr, name)]
        self.alias = None


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
    statements_seen = False
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
        if tok.kind == "ident" and tok.value == "sources" and r.peek_after_nl(1).kind == "op" and r.peek_after_nl(1).value == "{":
            if program.sources is not None:
                with_line(tok, fail, dsl_error("at most one 'sources' block is allowed"))
            if statements_seen:
                with_line(tok, fail, dsl_error("'sources { ... }' must appear before any other statements"))
            with_line(tok, parse_sources_block, r, program)
            continue
        statements_seen = True
        if tok.kind == "ident" and tok.value == "with" and nxt.kind == "ident":
            with_line(tok, parse_with_block, r, program, with_line)
            continue
        if tok.kind == "ident" and tok.value == "join":
            with_line(tok, parse_join, r, program)
            continue
        toks = r.collect_statement()
        with_line(toks[0], parse_pipeline_statement, program, Parser(tokens=toks))
    if program.aggregates is None:
        raise dsl_error("exactly one 'aggregate' statement is required")
    return program


def fail(err):
    raise err


def expect_line_end(r):
    tok = r.peek()
    if not (tok.kind in ("nl", "eof") or (tok.kind == "op" and tok.value == "}")):
        raise dsl_error(f"unexpected {describe(tok)}")


def parse_sources_block(r, program):
    r.next()  # 'sources'
    parse_block_header_open(r)
    entries = []
    while True:
        r.skip_nl()
        if r.at_op("}"):
            r.next()
            break
        if r.at("eof"):
            raise dsl_error("sources block is missing a closing '}'")
        name = r.expect_ident("source name")
        alias = name
        if r.at("ident", "as"):
            r.next()
            alias = r.expect_ident("source alias")
        if alias in RESERVED_WORDS or alias == "_":
            raise dsl_error(f"'{alias}' cannot be used as a source alias")
        if any(a == alias for _, a in entries):
            raise dsl_error(f"source alias '{alias}' is bound more than once")
        entries.append((name, alias))
        r.skip_nl()
        if r.at_op(","):
            r.next()
        elif not r.at_op("}") and not r.at("ident"):
            raise dsl_error(f"expected ',' or '}}' in sources block but found {describe(r.peek())}")
    expect_line_end(r)
    if not entries:
        raise dsl_error("sources block must bind at least one source")
    program.sources = entries


WITH_FORBIDDEN = ("group_by", "window", "aggregate", "apply", "join", "with", "sources", "params")


def parse_with_block(r, program, with_line):
    r.next()  # 'with'
    alias = r.expect_ident("source alias")
    parse_block_header_open(r)
    steps = []
    while True:
        r.skip_nl()
        if r.at_op("}"):
            r.next()
            break
        if r.at("eof"):
            raise dsl_error(f"'with {alias}' block is missing a closing '}}'")
        toks = r.collect_statement()
        with_line(toks[0], parse_with_statement, program, alias, steps, Parser(tokens=toks))
    expect_line_end(r)
    program.with_blocks.append((alias, steps))


def parse_with_statement(program, alias, steps, p):
    head = p.peek()
    if head.kind == "ident" and head.value == "calc":
        calc = parse_calc(p, "pre")
        if calc.stage != "pre":
            program.with_errors.append(type_error(
                f"calc '{calc.name}' in 'with {alias}' must be @stage(pre); post-aggregation calcs are not allowed in 'with' blocks"))
            return
        steps.append(("calc", calc))
        return
    if head.kind == "ident" and head.value == "filter":
        p.next()
        p.expect_op("(")
        expr = p.parse_expr()
        p.expect_op(")")
        p.expect_eof()
        steps.append(("filter", expr))
        return
    if head.kind == "ident" and head.value in WITH_FORBIDDEN:
        raise dsl_error(f"'{head.value}' is not allowed inside 'with {alias}'; only pre-stage calcs and filters are")
    raise dsl_error(f"unknown statement starting with {describe(head)} in 'with {alias}'")


JOIN_TYPES = ("inner", "left", "right", "full")
JOIN_CLAUSES = ("on", "within", "type", "project")
WITHIN_UNITS = {"s": 1, "sec": 1, "m": 60, "min": 60, "h": 3600, "hr": 3600, "d": 86400}


def parse_join_operand(r):
    r.skip_nl()
    if r.at_op("("):
        r.next()
        name = r.expect_ident("relation alias")
        r.expect_op(")")
        return name
    return r.expect_ident("relation alias")


def parse_join(r, program):
    r.next()  # 'join'
    decl = JoinDecl(parse_join_operand(r), None)
    r.skip_nl()
    if not r.at("ident", "with"):
        raise dsl_error(f"expected 'with' in join but found {describe(r.peek())}")
    r.next()
    decl.right = parse_join_operand(r)
    while True:
        r.skip_nl()
        tok = r.peek()
        if tok.kind == "ident" and tok.value == "on":
            if decl.on is not None:
                raise dsl_error("join has more than one 'on' clause")
            r.next()
            decl.on = parse_join_on(r)
            decl.on_keys = [f"{c.left.name}=={c.right.name}" for c in conjuncts(decl.on)
                            if isinstance(c, Binary) and c.op == "==" and isinstance(c.left, Col) and isinstance(c.right, Col)]
        elif (tok.kind == "ident" and tok.value == "within") or (tok.kind == "op" and tok.value == "["):
            if decl.within is not None:
                raise dsl_error("join has more than one 'within' clause")
            bracketed = tok.kind == "op"
            r.next()
            if bracketed:
                r.skip_nl()
                if not r.at("ident", "within"):
                    raise dsl_error(f"expected 'within' but found {describe(r.peek())}")
                r.next()
            decl.within, decl.within_text = parse_within_duration(r)
            if bracketed:
                r.skip_nl()
                r.expect_op("]")
        elif tok.kind == "ident" and tok.value == "type":
            if decl.jtype is not None:
                raise dsl_error("join has more than one 'type' clause")
            r.next()
            jt = r.expect_ident("join type")
            if jt not in JOIN_TYPES:
                raise dsl_error(f"unknown join type '{jt}'; expected one of {', '.join(JOIN_TYPES)}")
            if jt != "inner" and r.at("ident", "outer"):
                r.next()
            decl.jtype = jt
        elif tok.kind == "ident" and tok.value == "project":
            r.next()
            decl.project = parse_project(r)
            if r.peek_after_nl(0).kind == "ident" and r.peek_after_nl(0).value == "as":
                r.skip_nl()
                r.next()
                decl.alias = r.expect_ident("join alias")
                if decl.alias in RESERVED_WORDS or decl.alias == "_":
                    raise dsl_error(f"'{decl.alias}' cannot be used as a join alias")
            expect_line_end(r)
            break
        else:
            raise dsl_error(f"join is missing 'project {{ ... }}' (found {describe(tok)})")
    if decl.on is None:
        raise dsl_error("join requires an 'on (...)' predicate")
    if decl.jtype is None:
        decl.jtype = "inner"
    program.joins.append(decl)


def parse_join_on(r):
    toks = []
    depth = 0
    while True:
        tok = r.peek()
        if tok.kind == "eof":
            break
        if tok.kind == "nl":
            r.next()
            continue
        if depth <= 0:
            if tok.kind == "op" and tok.value in ("[", "}"):
                break
            if (tok.kind == "ident" and tok.value in ("within", "type", "project")
                    and not (toks and toks[-1].kind == "op" and toks[-1].value == ".")):
                break
        if tok.kind == "op" and tok.value in "([":
            depth += 1
        elif tok.kind == "op" and tok.value in ")]":
            depth -= 1
        toks.append(r.next())
    if not toks:
        raise dsl_error("join 'on' requires a predicate")
    end = toks[-1].end
    p = Parser(tokens=toks + [Token("eof", None, end, end)])
    expr = p.parse_expr()
    p.expect_eof()
    return expr


def parse_within_duration(r):
    num = r.next()
    unit = r.next()
    if (
        num.kind != "num"
        or not re.fullmatch(r"\d+", num.value)
        or unit.kind != "ident"
        or unit.value not in WITHIN_UNITS
    ):
        raise dsl_error("invalid 'within' duration; expected e.g. 30s, 10m, 1h, 1d")
    return int(num.value) * WITHIN_UNITS[unit.value] * 1_000_000, num.value + unit.value


def parse_project(r):
    r.skip_nl()
    r.expect_op("{")
    entries = [[]]
    depth = 0
    while True:
        tok = r.next()
        if tok.kind == "eof":
            raise dsl_error("project block is missing a closing '}'")
        if tok.kind == "nl":
            continue
        if tok.kind == "op":
            if tok.value == "}" and depth == 0:
                break
            if tok.value in "([{":
                depth += 1
            elif tok.value in ")]}":
                depth -= 1
            elif tok.value == "," and depth == 0:
                entries.append([])
                continue
        entries[-1].append(tok)
    if not entries[-1]:
        entries.pop()
    if not entries:
        raise dsl_error("project block must define at least one column")
    project = []
    for toks in entries:
        if not toks:
            raise dsl_error("empty entry in project block")
        end = toks[-1].end
        p = Parser(tokens=toks + [Token("eof", None, end, end)])
        expr = p.parse_expr()
        if p.at("ident", "as"):
            p.next()
            name = p.expect_name("column name")
        elif isinstance(expr, Col):
            name = expr.name.rsplit(".", 1)[-1]
        else:
            raise dsl_error(f"project entry needs 'as <name>', found {describe(p.peek())}")
        p.expect_eof()
        if name in RESERVED_WORDS or "." in name:
            raise dsl_error(f"'{name}' cannot be used as a column name")
        if any(n == name for _, n in project):
            raise dsl_error(f"duplicate column name '{name}' in project; disambiguate with 'as'")
        project.append((expr, name))
    return project


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


def parse_calc(p, default_stage):
    p.next()  # 'calc'
    name = p.expect_ident("calc name")
    if name in RESERVED_WORDS:
        raise dsl_error(f"'{name}' is a reserved word and cannot be a field name")
    p.expect_op("=")
    expr = p.parse_expr()
    p.expect_op(":")
    typ = parse_type(p)
    stage = parse_stage(p) if p.at_op("@") else default_stage
    p.expect_eof()
    return CalcDecl(name, expr, typ, stage)


def parse_pipeline_statement(program, p):
    if p.at("ident", "calc"):
        calc = parse_calc(p, "post_agg" if program.aggregates is not None else "pre")
        if calc.stage == "pre":
            program.steps.append(("calc", calc))
        else:
            program.post_calcs.append(calc)
        return
    head = p.peek()
    if head.kind == "ident" and head.value == "sources":
        raise dsl_error("'sources { ... }' must appear before any other statements")
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


def validate_multi_source(program):
    """Structural checks of sources / with / join statements (DSL errors)."""
    if program.sources is None:
        if program.joins:
            raise dsl_error("join requires a 'sources { ... }' block declaring the joined sources")
        if program.with_blocks:
            raise dsl_error("'with' blocks require a 'sources { ... }' block")
        return
    if not program.joins:
        raise dsl_error("multi-source pipelines must combine their sources with 'join'")
    aliases = [a for _, a in program.sources]
    for alias, _ in program.with_blocks:
        if alias not in aliases:
            raise dsl_error(f"'with {alias}' refers to an unknown source alias")
    join_aliases = {}
    used = set()
    for i, j in enumerate(program.joins):
        keys = []
        for side in (j.left, j.right):
            if side == "_":
                if i == 0:
                    raise dsl_error("'_' refers to the previous join result, but no join precedes it")
                key = i - 1
            elif side in aliases:
                key = side
            elif side in join_aliases:
                key = join_aliases[side]
            else:
                raise dsl_error(f"join refers to unknown source or join alias '{side}'")
            keys.append(key)
            used.add(key)
        if keys[0] == keys[1]:
            raise dsl_error(f"cannot join '{j.left}' with itself; bind the source twice under different aliases")
        if j.alias is not None:
            if j.alias in aliases or j.alias in join_aliases:
                raise dsl_error(f"join alias '{j.alias}' is already in use")
            join_aliases[j.alias] = i
    for alias in aliases:
        if alias not in used:
            raise dsl_error(f"source alias '{alias}' is never joined; multi-source pipelines must combine all sources")
    for i in range(len(program.joins) - 1):
        if i not in used:
            raise dsl_error(f"the result of join #{i + 1} is never used by a later join")


def finalize_block_program(program, schemas, cli_params):
    if program.schema_name not in schemas:
        raise dsl_error(f"pipeline uses unknown schema '{program.schema_name}'")
    resolved = resolve_schemas(schemas, program.deferred_errors)
    program.resolved_schemas = resolved
    fields, order = resolved[program.schema_name]
    program.schema_fields = fields
    program.schema_calc_order = order
    params = program.params
    validate_multi_source(program)

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
    for _, steps in program.with_blocks:
        for step in steps:
            check_expr_structure(step[1].expr if step[0] == "calc" else step[1], params, post=False)
    for j in program.joins:
        check_expr_structure(j.on, params, post=False)
        for expr, _ in j.project:
            check_expr_structure(expr, params, post=False)
    if program.window_param is not None and program.window_param not in params:
        raise dsl_error(f"unknown parameter '{program.window_param}'")

    if program.joins:
        # the working schema after the final join is defined by its project block
        fields = {name: None for _, name in program.joins[-1].project}
        fields.setdefault("timestamp", None)
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


# --------------------------------------------------------------------------- DSL versioning

VERSION_LINE_RE = re.compile(r"mtl_version(?![A-Za-z0-9_])")
VERSION_HEADER_RE = re.compile(r"mtl_version[ \t]+(\d+)\.(\d+)")

# minimum DSL version of each feature family
V_BLOCKS = (1, 2)  # schemas with inheritance, params, pre/post calcs, lag/lead
V_NULLS = (1, 3)  # multi-format I/O, null/3VL, count(col)
V_SOURCES = (1, 4)  # ingest config, sources, joins, UDFs
V_RESUME = (1, 5)  # resumption + run metadata


def version_text(version):
    return f"{version[0]}.{version[1]}"


def split_version_header(text):
    """Return ((major, minor), text without the header) for a DSL whose first non-comment line is the header.

    The header line is blanked rather than removed so that diagnostics keep their line numbers."""
    lines = text.split("\n")
    for i, raw in enumerate(lines):
        stripped = raw.strip()
        if not stripped or stripped.startswith("#"):
            continue
        code = stripped.split("#", 1)[0].strip()
        if not VERSION_LINE_RE.match(code):
            raise artifact_error(
                f"line {i + 1}: missing version header; the first non-comment line must be 'mtl_version <MAJOR>.<MINOR>'")
        m = VERSION_HEADER_RE.fullmatch(code)
        if not m:
            raise dsl_error(f"line {i + 1}: invalid version header {code!r}; expected 'mtl_version <MAJOR>.<MINOR>'")
        version = (int(m.group(1)), int(m.group(2)))
        if version[0] != SUPPORTED_MAJOR:
            raise artifact_error(f"unsupported mtl_version {version_text(version)}; this runtime supports "
                                 f"{SUPPORTED_MAJOR}.x (up to {SUPPORTED_MAJOR}.{SUPPORTED_MINOR})")
        lines[i] = ""
        return version, "\n".join(lines)
    raise artifact_error("missing version header; the DSL must begin with 'mtl_version <MAJOR>.<MINOR>'")


def require_version(declared, needed, what):
    if declared < needed:
        raise dsl_error(f"{what} requires mtl_version {version_text(needed)} or later "
                        f"(the DSL declares mtl_version {version_text(declared)})")


def program_expressions(program):
    for step in program.steps:
        yield step[1].expr if step[0] == "calc" else step[1]
    for fields, _ in program.resolved_schemas.values():
        for f in fields.values():
            if f.expr is not None:
                yield f.expr
    for calc in program.post_calcs:
        yield calc.expr
    for _, steps in program.with_blocks:
        for kind, item in steps:
            yield item.expr if kind == "calc" else item
    for j in program.joins:
        yield j.on
        for expr, _ in j.project or []:
            yield expr


def check_feature_gates(program, declared):
    """Reject constructs that need a newer DSL minor version than the one declared (DSL error)."""
    if program.block:
        require_version(declared, V_BLOCKS, "schema/pipeline blocks")
    for fn, col, _ in program.aggregates:
        if fn == "count" and col is not None:
            require_version(declared, V_NULLS, f"count({col})")
    if program.sources is not None:
        require_version(declared, V_SOURCES, "'sources { ... }'")
    if program.with_blocks:
        require_version(declared, V_SOURCES, "'with <alias> { ... }'")
    if program.joins:
        require_version(declared, V_SOURCES, "join")
    for expr in program_expressions(program):
        for n in walk(expr):
            if isinstance(n, Call) and n.name in UDFS and n.name not in FUNCTION_ARITY:
                require_version(declared, V_SOURCES, f"user-defined function '{n.name}'")


def version_warning(declared, args):
    """A single advisory line when the DSL declares an older minor than this runtime implements, else None."""
    if declared[1] >= SUPPORTED_MINOR:
        return None
    notes = [f"constructs introduced after {version_text(declared)} are disabled"]
    if args.state_dir or args.meta_out:
        notes.append(f"resumable state and run metadata follow mtl_version {version_text(V_RESUME)} semantics")
    return (f"WARNING:version:DSL declares mtl_version {version_text(declared)} but this runtime implements "
            f"{SUPPORTED_MAJOR}.{SUPPORTED_MINOR}; " + "; ".join(notes))


# --------------------------------------------------------------------------- input discovery & loading

NUMBER_RE = re.compile(r"[+-]?(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?|[+-]?(?:inf|infinity|nan)", re.IGNORECASE)
INT_RE = re.compile(r"[+-]?\d+")

DEFAULT_NULLS = ("null", "NULL", "NaN")
FORMATS = ("csv", "tsv", "parquet")
FORMAT_EXTENSIONS = (
    (".csv.gz", "csv"),
    (".tsv.gz", "tsv"),
    (".csv", "csv"),
    (".tsv", "tsv"),
    (".parquet", "parquet"),
)
AMBIGUOUS_EXTENSIONS = ("", ".gz", ".txt", ".dat")
GLOB_CHARS = "*?["

# bad record classifications
PARSE_TYPE_MISMATCH = "PARSE_TYPE_MISMATCH"
TIMESTAMP_PARSE_ERROR = "TIMESTAMP_PARSE_ERROR"
RUNTIME_ERROR = "RUNTIME_ERROR"
TYPE_ERROR = "TYPE_ERROR"
MISSING_REQUIRED_FIELD = "MISSING_REQUIRED_FIELD"
PARQUET_TYPE_MISMATCH = "PARQUET_TYPE_MISMATCH"

NAIVE_EPOCH = datetime(1970, 1, 1)


class RowError(Exception):
    """A record that cannot be processed; becomes a bad record (or aborts in strict mode)."""

    def __init__(self, kind, message, column=None, value=None):
        super().__init__(message)
        self.kind = kind
        self.message = message
        self.column = column
        self.value = value


class LoadOptions:
    def __init__(self, tz, parse_ts, nulls, strict):
        self.tz = tz
        self.parse_ts = parse_ts  # textual timestamps (honours --timestamp-format)
        self.parse_iso = make_ts_parser(tz, None)  # string-typed Parquet timestamps
        self.nulls = nulls
        self.strict = strict
        self.legacy = False


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


def parse_null_markers(text):
    if text is None:
        return frozenset(DEFAULT_NULLS)
    return frozenset(m.strip() for m in text.split(",") if m.strip())


def detect_format(path, forced):
    low = os.path.basename(path).lower()
    for ext, fmt in FORMAT_EXTENSIONS:
        if low.endswith(ext):
            return fmt
    return None if forced == "auto" else forced


def scan_format(path, forced):
    """Format of a file found by directory traversal or glob; None means skip it."""
    fmt = detect_format(path, "auto")
    if fmt is not None:
        return fmt
    if forced != "auto" and os.path.splitext(os.path.basename(path).lower())[1] in AMBIGUOUS_EXTENSIONS:
        return forced
    return None


def resolve_inputs(patterns, recursive, forced):
    """Expand --input values into a sorted, de-duplicated list of (display_path, format)."""
    found = {}

    def add(path, fmt):
        key = os.path.realpath(path)
        disp = os.path.normpath(path)
        prev = found.get(key)
        if prev is None or disp < prev[0]:
            found[key] = (disp, fmt)

    def add_dir(top):
        for root, dirs, files in os.walk(top):
            dirs[:] = sorted(d for d in dirs if not d.startswith(".")) if recursive else []
            for name in sorted(files):
                if name.startswith("."):
                    continue
                path = os.path.join(root, name)
                fmt = scan_format(path, forced)
                if fmt is not None and os.path.isfile(path):
                    add(path, fmt)

    for pattern in patterns:
        if os.path.isdir(pattern):
            add_dir(pattern)
        elif os.path.exists(pattern):
            fmt = detect_format(pattern, forced)
            if fmt is None:
                raise io_error(f"cannot determine the format of input file {pattern}; use --format")
            add(pattern, fmt)
        elif any(ch in pattern for ch in GLOB_CHARS):
            for match in sorted(glob.glob(pattern, recursive=True)):
                if os.path.isdir(match):
                    add_dir(match)
                elif os.path.isfile(match):
                    fmt = scan_format(match, forced)
                    if fmt is not None:
                        add(match, fmt)
        else:
            raise io_error(f"input not found: {pattern}")
    if not found:
        raise io_error("no input files matched " + ", ".join(patterns))
    return sorted(found.values())


def read_bytes(path):
    try:
        with open(path, "rb") as f:
            return f.read()
    except FileNotFoundError:
        raise io_error(f"input file not found: {path}")
    except IsADirectoryError:
        raise io_error(f"input path is a directory: {path}")
    except OSError as e:
        raise io_error(f"cannot read input file {path}: {e.strerror or e}")


def is_blank(rec):
    return not rec or (len(rec) == 1 and rec[0].strip() == "")


class TextSource:
    def __init__(self, path, fmt):
        self.path = path
        self.fmt = fmt
        data = read_bytes(path)
        if data[:2] == b"\x1f\x8b" or path.lower().endswith(".gz"):
            try:
                data = gzip.decompress(data)
            except (OSError, EOFError, zlib.error) as e:
                raise io_error(f"cannot decompress gzip file {path}: {e}")
        try:
            text = data.decode("utf-8-sig")
        except UnicodeDecodeError:
            raise io_error(f"input file is not valid UTF-8: {path}")
        reader = csv.reader(
            io.StringIO(text, newline=""),
            delimiter="," if fmt == "csv" else "\t",
            quotechar='"',
            doublequote=True,
        )
        records = []
        prev = 0
        try:
            for rec in reader:
                records.append((prev + 1, rec))
                prev = reader.line_num
        except csv.Error as e:
            raise io_error(f"malformed {fmt.upper()} file {path}: {e}")
        while records and is_blank(records[0][1]):
            records.pop(0)
        if not records:
            raise io_error(f"{fmt.upper()} file {path} is empty; a header row is required")
        self.header = [h.strip() for h in records[0][1]]
        named = [h for h in self.header if h]
        if len(set(named)) != len(named):
            raise io_error(f"{fmt.upper()} header in {path} contains duplicate column names")
        self.body = [(line, rec) for line, rec in records[1:] if not is_blank(rec)]
        self.index = {}
        for i, name in enumerate(self.header):
            if name:
                self.index[name] = i

    def columns(self):
        return set(self.index)

    def row_count(self):
        return len(self.body)

    def column_text(self, name):
        i = self.index[name]
        return [rec[i] for _, rec in self.body if i < len(rec)]

    def records(self, fields, required, opts):
        check_columns(self, fields, required, opts)
        width = len(self.header)
        for n, (line, rec) in enumerate(self.body, 1):
            try:
                if len(rec) > width:
                    raise RowError(PARSE_TYPE_MISMATCH, f"record has {len(rec)} fields, expected {width}")
                row = {}
                for name, typ in fields.items():
                    i = self.index.get(name)
                    if i is None:
                        row[name] = None
                    elif i >= len(rec):
                        raise RowError(
                            MISSING_REQUIRED_FIELD,
                            f"record has {len(rec)} fields, expected {width}; field '{name}' is missing",
                            name,
                        )
                    else:
                        row[name] = convert_text(rec[i], typ, name, opts)
                yield line, n, row, None, rec
            except RowError as e:
                yield line, n, None, e, rec

    def raw_records(self, opts):
        """Records as {column: ("text", raw)} cells; missing trailing fields are simply absent."""
        width = len(self.header)
        for n, (line, rec) in enumerate(self.body, 1):
            if len(rec) > width:
                yield line, n, None, RowError(PARSE_TYPE_MISMATCH, f"record has {len(rec)} fields, expected {width}"), rec
                continue
            cells = {name: ("text", rec[i]) for name, i in self.index.items() if i < len(rec)}
            yield line, n, cells, None, rec

    def context(self, rec):
        record = {}
        for i, value in enumerate(rec):
            key = self.header[i] if i < len(self.header) and self.header[i] else f"_{i + 1}"
            record[key] = value
        return record


def convert_text(raw, typ, name, opts):
    s = raw.strip()
    if s == "" or raw in opts.nulls or s in opts.nulls:
        return None
    if typ == STR:
        return raw
    if typ == FLOAT:
        try:
            x = parse_number(s)
        except ValueError:
            raise RowError(PARSE_TYPE_MISMATCH, f"column '{name}' has invalid float value {raw!r}", name, raw)
        return None if math.isnan(x) else x
    if typ == INT:
        if INT_RE.fullmatch(s):
            try:
                return int(s)
            except ValueError:
                pass
        elif s.lower().lstrip("+-") == "nan":
            return None
        raise RowError(PARSE_TYPE_MISMATCH, f"column '{name}' has invalid int value {raw!r}", name, raw)
    if typ == BOOL:
        low = s.lower()
        if low not in ("true", "false"):
            raise RowError(PARSE_TYPE_MISMATCH, f"column '{name}' has invalid bool value {raw!r}", name, raw)
        return low == "true"
    try:
        return opts.parse_ts(s)
    except (ValueError, OverflowError):
        raise RowError(TIMESTAMP_PARSE_ERROR, f"column '{name}' has invalid timestamp value {raw!r}", name, raw)


def check_columns(src, fields, required, opts):
    available = src.columns()
    missing = [n for n in fields if n in required and n not in available]
    if missing and opts.strict:
        raise type_error(f"{src.path}: missing required column(s): {', '.join(missing)}")


# -- Parquet

def require_pyarrow():
    try:
        import pyarrow
        import pyarrow.parquet
    except ImportError:
        raise io_error("reading Parquet files requires the 'pyarrow' package")
    return pyarrow


def arrow_kind(t):
    pa = require_pyarrow()
    if pa.types.is_dictionary(t):
        return arrow_kind(t.value_type)
    if pa.types.is_null(t):
        return "null"
    if pa.types.is_boolean(t):
        return BOOL
    if pa.types.is_integer(t):
        return INT
    if pa.types.is_floating(t):
        return FLOAT
    if pa.types.is_decimal(t):
        return "decimal"
    if pa.types.is_string(t) or pa.types.is_large_string(t) or getattr(pa.types, "is_string_view", lambda _: False)(t):
        return STR
    if pa.types.is_binary(t) or pa.types.is_large_binary(t) or pa.types.is_fixed_size_binary(t):
        return "binary"
    if pa.types.is_timestamp(t):
        return TS
    if pa.types.is_date(t):
        return "date"
    return None


ARROW_KIND_TO_TYPE = {INT: INT, FLOAT: FLOAT, "decimal": FLOAT, BOOL: BOOL, STR: STR, "binary": STR, TS: TS, "date": TS}


def jsonable(v):
    if v is None or isinstance(v, (bool, int, str)):
        return v
    if isinstance(v, float):
        return v if math.isfinite(v) else repr(v)
    if isinstance(v, datetime):
        return format_ts(v) if v.tzinfo is not None else v.isoformat()
    if isinstance(v, bytes):
        return v.decode("utf-8", errors="replace")
    return str(v)


class ParquetSource:
    def __init__(self, path):
        pa = require_pyarrow()
        self.path = path
        self.fmt = "parquet"
        read_bytes(path)  # uniform not-found / permission errors
        try:
            self.table = pa.parquet.read_table(path)
        except Exception as e:  # pyarrow raises a variety of error types for corrupt files
            raise io_error(f"cannot read Parquet file {path}: {' '.join(str(e).split())}")
        names = self.table.column_names
        if len(set(names)) != len(names):
            raise io_error(f"Parquet file {path} contains duplicate column names")
        self.num_rows = self.table.num_rows

    def columns(self):
        return set(self.table.column_names)

    def row_count(self):
        return self.num_rows

    def column_type(self, name):
        return self.table.schema.field(name).type

    def records(self, fields, required, opts):
        check_columns(self, fields, required, opts)
        available = self.columns()
        decoded = {}
        for name, typ in fields.items():
            if name in available:
                decoded[name] = self.decode_column(name, typ, opts)
        for i in range(self.num_rows):
            row = {}
            err = None
            for name in fields:
                col = decoded.get(name)
                if col is None:
                    row[name] = None
                    continue
                v = col[0][i]
                if isinstance(v, RowError):
                    err = v
                    break
                row[name] = v
            ctx = (decoded, i)
            if err is None:
                yield None, i + 1, row, None, ctx
            else:
                yield None, i + 1, None, err, ctx

    def context(self, ctx):
        decoded, i = ctx
        return {name: col[1][i] for name, col in decoded.items()}

    def raw_records(self, opts):
        """Records as {column: ("pq", kind, arrow_type, value)} cells."""
        columns = {}
        display = {}
        for name in self.table.column_names:
            kind, t, items = self.column_items(name, opts)
            columns[name] = (kind, t, items)
            display[name] = (None, [jsonable(v) for v in items])
        for i in range(self.num_rows):
            cells = {name: ("pq", kind, t, items[i]) for name, (kind, t, items) in columns.items()}
            yield None, i + 1, cells, None, (display, i)

    def column_items(self, name, opts):
        """(kind, arrow type, Python values) of a column; timestamps become aware UTC datetimes."""
        pa = require_pyarrow()
        col = self.table.column(name)
        t = col.type
        if pa.types.is_dictionary(t):
            col = pa.chunked_array([c.dictionary_decode() for c in col.chunks], type=t.value_type)
            t = t.value_type
        kind = arrow_kind(t)
        if kind == TS:
            raw = col.cast(pa.int64()).to_pylist()
            factor = {"s": 1_000_000, "ms": 1000, "us": 1, "ns": None}[t.unit]
            items = []
            for v in raw:
                if v is None:
                    items.append(None)
                    continue
                us = v // 1000 if factor is None else v * factor
                try:
                    if t.tz is not None:
                        items.append(EPOCH + timedelta(microseconds=us))
                    else:
                        local = (NAIVE_EPOCH + timedelta(microseconds=us)).replace(tzinfo=opts.tz)
                        items.append(local.astimezone(timezone.utc))
                except (OverflowError, ValueError):
                    items.append(f"{v} ({t})")
        else:
            try:
                items = col.to_pylist()
            except Exception:  # e.g. dates outside Python's range
                items = [None if v is None else str(v) for v in col.cast(pa.string()).to_pylist()]
                kind = "unreadable"
        return kind, t, items

    def decode_column(self, name, typ, opts):
        """Return (values, display) lists; a value is a Python value, None, or a RowError."""
        kind, t, items = self.column_items(name, opts)
        display = [jsonable(v) for v in items]
        values = []
        for v, shown in zip(items, display):
            if v is None:
                values.append(None)
                continue
            try:
                values.append(convert_parquet_value(v, kind, t, typ, name, opts))
            except RowError as e:
                e.value = shown
                values.append(e)
        return values, display

def convert_parquet_value(v, kind, t, typ, name, opts):
    def mismatch():
        return RowError(
            PARQUET_TYPE_MISMATCH,
            f"column '{name}' has Parquet type {t} which cannot be read as {typ}",
            name,
        )

    if kind == "binary" and typ in (STR, TS):
        if isinstance(v, str):
            raise mismatch()
        try:
            v = v.decode("utf-8")
        except UnicodeDecodeError:
            raise mismatch()
        kind = STR
    if kind == STR and (v.strip() == "" or v in opts.nulls or v.strip() in opts.nulls):
        return None
    if typ == STR:
        if kind == STR:
            return v
        if opts.legacy and kind in (INT, FLOAT, BOOL, "decimal", TS, "date"):
            if kind == BOOL:
                return "true" if v else "false"
            if kind == TS:
                return format_ts(v)
            if kind == FLOAT:
                return repr(v)
            return str(v)
        raise mismatch()
    if typ == INT:
        if kind == INT:
            return v
        if kind == "decimal" and t.scale <= 0:
            return int(v)
        raise mismatch()
    if typ == FLOAT:
        if kind in (INT, FLOAT, "decimal"):
            x = float(v)
            return None if math.isnan(x) else x
        raise mismatch()
    if typ == BOOL:
        if kind == BOOL:
            return v
        raise mismatch()
    # timestamp
    if kind == TS:
        if isinstance(v, str):
            raise RowError(TIMESTAMP_PARSE_ERROR, f"column '{name}' has out-of-range timestamp {v}", name)
        return v
    if kind == "date":
        try:
            return datetime(v.year, v.month, v.day, tzinfo=opts.tz).astimezone(timezone.utc)
        except (OverflowError, ValueError):
            raise RowError(TIMESTAMP_PARSE_ERROR, f"column '{name}' has out-of-range date {v}", name)
    if kind == STR:
        try:
            return opts.parse_iso(v)
        except (ValueError, OverflowError):
            raise RowError(TIMESTAMP_PARSE_ERROR, f"column '{name}' has invalid timestamp value {v!r}", name)
    raise mismatch()


def load_source(path, fmt):
    return ParquetSource(path) if fmt == "parquet" else TextSource(path, fmt)


class StoredSource:
    """Stands in for a file restored from a checkpoint: its records' contexts were saved as plain dicts."""

    def __init__(self, path, fmt):
        self.path = path
        self.fmt = fmt

    def context(self, raw):
        return raw


# -- legacy (schema-less DSL) column typing

def infer_type(values, opts):
    present = [v.strip() for v in values if v.strip() != "" and v not in opts.nulls and v.strip() not in opts.nulls]
    if not present:
        return None
    if all(INT_RE.fullmatch(v) for v in present):
        return INT
    if all(NUMBER_RE.fullmatch(v) for v in present):
        return FLOAT
    if all(v.lower() in ("true", "false") for v in present):
        return BOOL
    if all(":" in v for v in present):
        try:
            for v in present:
                opts.parse_ts(v)
            return TS
        except (ValueError, OverflowError):
            pass
    return STR


def legacy_file_types(src, opts):
    """The inferred type (or None) of every extra column of one file."""
    types = {}
    for name in sorted(src.columns()):
        if name in REQUIRED_COLUMNS:
            continue
        if isinstance(src, ParquetSource):
            kind = arrow_kind(src.column_type(name))
            if kind is None:
                continue
            types[name] = ARROW_KIND_TO_TYPE.get(kind)
        else:
            types[name] = infer_type(src.column_text(name), opts)
    return types


def infer_legacy_schema(per_file_types):
    """Required columns plus every extra column, typed consistently across all files."""
    found = {}
    for file_types in per_file_types:
        for name, typ in file_types.items():
            types = found.setdefault(name, set())
            if typ is not None:
                types.add(typ)
    schema = dict(REQUIRED_COLUMNS)
    for name in sorted(found):
        types = found[name]
        if len(types) == 1:
            schema[name] = next(iter(types))
        elif types and types <= {INT, FLOAT}:
            schema[name] = FLOAT
        else:
            schema[name] = STR
    return schema


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

            def negate(row):
                v = f(row)
                return None if v is None else not v

            return BOOL, negate
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
            if v is None or needle is None:
                return None
            return needle in v

        return BOOL, contains

    if op in STRING_OPS:
        return compile_string_test(op, node.left, node.right, schema, ctx)

    lt, lf = compile_expr(node.left, schema, ctx)
    rt, rf = compile_expr(node.right, schema, ctx)

    if op in ("&", "|"):
        if lt != BOOL or rt != BOOL:
            raise type_error(f"'{op}' requires boolean operands, got {type_name(lt)} and {type_name(rt)}")
        # Kleene three-valued logic: a known operand can decide the result even when the other is null.
        decisive = op == "|"

        def logical(row):
            a = lf(row)
            if a is decisive:
                return decisive
            b = rf(row)
            if b is decisive:
                return decisive
            if a is None or b is None:
                return None
            return not decisive

        return BOOL, logical

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
                return None
            b = rf(row)
            if b is None:
                return None
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
            return None
        x = rf(row)
        if x is None:
            return None
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
    if name in UDFS:
        return compile_udf(node, schema, ctx)
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


def compile_udf(node, schema, ctx):
    udf = UDFS[node.name]
    compiled = [compile_expr(a, schema, ctx) for a in node.args]
    widen = []
    for i, ((t, _), want) in enumerate(zip(compiled, udf.args), 1):
        if t != want and not (t == INT and want == FLOAT):
            raise type_error(f"argument {i} of {udf.name}() must be {want}, got {type_name(t)}")
        widen.append(t == INT and want == FLOAT)
    fns = [f for _, f in compiled]

    def call(row):
        values = []
        for f, w in zip(fns, widen):
            v = f(row)
            if v is None:  # UDFs are null-propagating
                return None
            values.append(float(v) if w else v)
        try:
            result = udf.fn(*values)
        except MTLError:
            raise
        except Exception as e:  # anything raised by user code is a runtime error for this row
            raise runtime_error(f"udf {udf.name}() raised {type(e).__name__}: {e}")
        return udf_result(udf, result)

    return udf.returns, call


def udf_result(udf, v):
    if v is None:
        return None
    typ = udf.returns
    if typ == FLOAT and isinstance(v, (int, float)) and not isinstance(v, bool):
        v = float(v)
        if not math.isfinite(v):
            raise runtime_error(f"udf {udf.name}() returned a non-finite number")
        return v
    if typ == INT and isinstance(v, int) and not isinstance(v, bool):
        return v
    if typ == STR and isinstance(v, str):
        return v
    if typ == BOOL and isinstance(v, bool):
        return v
    if typ == TS and isinstance(v, datetime):
        return (v if v.tzinfo is not None else v.replace(tzinfo=timezone.utc)).astimezone(timezone.utc)
    raise type_error(f"udf {udf.name}() is declared to return {typ} but returned {type(v).__name__} {v!r}")


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
    # Integers sum exactly; floats use math.fsum (correctly rounded), so results never depend on row order.
    if all(isinstance(v, int) for v in vals):
        return sum(vals)
    try:
        return math.fsum(vals)
    except OverflowError:
        raise runtime_error("numeric overflow in sum")
    except ValueError:
        raise runtime_error("sum produced a non-finite number")


def agg_mean(vals):
    return agg_sum(vals) / len(vals)


def agg_var(vals):
    mean = agg_mean(vals)
    return agg_sum([(v - mean) * (v - mean) for v in vals]) / len(vals)


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
    except (OverflowError, ValueError):
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
        self.window_text = None
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
    plan.window_text = program.window_text
    if program.window_param is not None:
        t, value = ctx.params[program.window_param]
        m = DURATION_RE.fullmatch(value) if t == STR else None
        if not m or int(m.group(1)) <= 0:
            raise type_error(f"parameter '{program.window_param}' is not a valid window duration (e.g. 10m, 1h, 7d)")
        window = int(m.group(1)) * DURATION_UNITS[m.group(2)] * 1_000_000
        plan.window_text = m.group(1) + m.group(2)
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


def run_row(plan, row):
    """Evaluate schema calcs and pre-stage steps on one row; False when a filter drops it."""
    label = None
    try:
        for name, f, conv in plan.prelude:
            label = f"calculated field '{name}'"
            v = f(row)
            row[name] = conv(v) if conv else v
        for kind, f, name, conv in plan.steps:
            if kind == "filter":
                label = "filter"
                if f(row) is not True:  # null counts as false
                    return False
            else:
                label = f"'{name}'"
                v = f(row)
                row[name] = conv(v) if conv else v
    except MTLError as e:
        raise RowError(TYPE_ERROR if e.kind == "type_error" else RUNTIME_ERROR, f"{label}: {e.message}")
    except TypeError as e:
        raise RowError(TYPE_ERROR, f"{label}: {e}")
    except (ArithmeticError, ValueError) as e:
        raise RowError(RUNTIME_ERROR, f"{label}: {type(e).__name__}: {e}")
    return True


STRICT_EXIT_KIND = {RUNTIME_ERROR: "runtime_error"}  # every other classification exits as a type error


def bad_record(src, line, rownum, err, raw):
    return {
        "file": src.path,
        "line": line,
        "row": rownum,
        "format": src.fmt,
        "error_type": err.kind,
        "classification": err.kind,
        "message": err.message,
        "column": err.column,
        "value": err.value,
        "context": {"record": src.context(raw)},
    }


def process_input_files(plan, files, loaded, reused, fields, required, opts, run, kind):
    """Validate and evaluate every record in a deterministic (file, line) order, one file unit at a time.

    Files in `reused` were completed by an earlier run and contribute their checkpointed rows instead."""
    kept = []
    bad = run.bad
    for path, fmt in files:
        res = reused.get(path)
        if res is None:
            src = loaded[path]
            res = FileResult(src.row_count())
            res.types = run.legacy_types.get(path)
            res.schema = fields if kind == "legacy" else None
            for line, rownum, row, err, raw in src.records(fields, required, opts):
                if err is None:
                    ts = row.get("timestamp")
                    try:
                        if run_row(plan, row):
                            res.rows.append(row)
                        res.observe(ts)
                        continue
                    except RowError as e:
                        err = e
                bad.append(bad_record(src, line, rownum, err, raw))
                if opts.strict:
                    where = f"{src.path}:{line}" if line is not None else f"{src.path} row {rownum}"
                    raise MTLError(STRICT_EXIT_KIND.get(err.kind, "type_error"), f"{where}: {err.kind}: {err.message}")
        else:
            bad.extend(res.bad)
        run.tracker.commit(DEFAULT_SOURCE, path, fmt, res, bad, None, kind)
        kept.extend(res.rows)
    return kept


def write_bad_records(path, bad):
    if not path or not bad:
        return
    entries = sorted(bad, key=lambda b: (b["file"] is None, b["file"] or "", b.get("source") or "",
                                         b["line"] if b["line"] is not None else 0, b["row"]))
    text = "".join(json.dumps(b, sort_keys=True, ensure_ascii=False) + "\n" for b in entries)
    try:
        parent = os.path.dirname(path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)
    except OSError as e:
        raise io_error(f"cannot write bad records file {path}: {e.strerror or e}")


def execute(plan, rows):
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


# --------------------------------------------------------------------------- ingest config

SOURCE_KEYS = ("name", "inputs", "recursive", "format", "schema", "precedence", "tz", "nulls", "mapping", "required")
MAPPING_KEYS = ("drop", "rename", "cast", "defaults")
YAML_NULL_MARKERS = ("null", "NULL", "Null", "~")


class SourceConfig:
    def __init__(self, name):
        self.name = name
        self.inputs = []
        self.recursive = None
        self.format = None
        self.schema = None
        self.precedence = 0
        self.tz = None
        self.nulls = None
        self.drop = []
        self.rename = {}
        self.cast = {}
        self.defaults = {}
        self.required = []


def read_config_text(path):
    try:
        with open(path, "rb") as f:
            data = f.read()
    except FileNotFoundError:
        raise io_error(f"ingest config not found: {path}")
    except IsADirectoryError:
        raise io_error(f"ingest config path is a directory: {path}")
    except OSError as e:
        raise io_error(f"cannot read ingest config {path}: {e.strerror or e}")
    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise config_error(f"ingest config is not valid UTF-8: {path}")


def parse_config_document(text, path):
    ext = os.path.splitext(path)[1].lower()
    stripped = text.strip()
    if not stripped:
        raise config_error(f"ingest config {path} is empty")
    if ext == ".json" or (stripped[0] in "{[" and ext not in (".yaml", ".yml")):
        try:
            return json.loads(text)
        except ValueError as e:
            if ext == ".json":
                raise config_error(f"malformed JSON in ingest config {path}: {e}")
    try:
        import yaml
    except ImportError:
        try:
            return MiniYaml(text).load()
        except ValueError as e:
            raise config_error(f"malformed YAML in ingest config {path}: {e}")
    try:
        return yaml.safe_load(text)
    except Exception as e:  # yaml.YAMLError, or ValueError from e.g. impossible dates
        first = str(e).strip().splitlines()[0] if str(e).strip() else type(e).__name__
        raise config_error(f"malformed YAML in ingest config {path}: {first}")


class MiniYaml:
    """Fallback parser for the YAML subset used by ingest configs (block/flow collections, scalars)."""

    def __init__(self, text):
        self.lines = []
        for lineno, raw in enumerate(text.splitlines(), 1):
            line = self.strip_comment(raw).rstrip()
            if not line.strip() or line.strip() in ("---", "..."):
                continue
            body = line.lstrip(" ")
            if body.startswith("\t"):
                raise ValueError(f"line {lineno}: tabs are not allowed for indentation")
            self.lines.append([len(line) - len(body), body, lineno])

    @staticmethod
    def strip_comment(line):
        quote = None
        for i, ch in enumerate(line):
            if quote:
                if ch == quote:
                    quote = None
            elif ch in "'\"":
                quote = ch
            elif ch == "#" and (i == 0 or line[i - 1] in " \t"):
                return line[:i]
        return line

    def load(self):
        if not self.lines:
            return None
        value, i = self.node(0, self.lines[0][0])
        if i < len(self.lines):
            raise ValueError(f"line {self.lines[i][2]}: unexpected content")
        return value

    def node(self, i, indent):
        body = self.lines[i][1]
        if body == "-" or body.startswith("- "):
            return self.sequence(i, indent)
        if self.split_key(body) is not None:
            return self.mapping(i, indent)
        text, i = self.flow_text(i)
        return self.scalar_or_flow(text, self.lines[i - 1][2]), i

    def flow_text(self, i):
        text = self.lines[i][1]
        i += 1
        while self.unbalanced(text) and i < len(self.lines):
            text += " " + self.lines[i][1]
            i += 1
        return text, i

    @staticmethod
    def unbalanced(text):
        depth = 0
        quote = None
        for ch in text:
            if quote:
                if ch == quote:
                    quote = None
            elif ch in "'\"":
                quote = ch
            elif ch in "[{":
                depth += 1
            elif ch in "]}":
                depth -= 1
        return depth > 0

    @staticmethod
    def split_key(body):
        if body[:1] in "[{":
            return None
        quote = None
        for i, ch in enumerate(body):
            if quote:
                if ch == quote:
                    quote = None
            elif ch in "'\"" and i == 0:
                quote = ch
            elif ch == ":" and (i + 1 == len(body) or body[i + 1] == " "):
                return body[:i].strip(), body[i + 1:].strip()
        return None

    def child(self, i, indent, lineno):
        """Value of a key or '-' whose inline part is empty: an indented block (or null)."""
        if i < len(self.lines):
            nxt_indent, nxt_body = self.lines[i][0], self.lines[i][1]
            if nxt_indent > indent or (nxt_indent == indent and (nxt_body == "-" or nxt_body.startswith("- "))):
                return self.node(i, nxt_indent)
        return None, i

    def mapping(self, i, indent):
        result = {}
        while i < len(self.lines) and self.lines[i][0] == indent:
            _, body, lineno = self.lines[i]
            kv = self.split_key(body)
            if kv is None:
                raise ValueError(f"line {lineno}: expected 'key: value'")
            key = self.scalar_or_flow(kv[0], lineno)
            if not isinstance(key, (str, int, float, bool)) and key is not None:
                raise ValueError(f"line {lineno}: invalid mapping key")
            if key in result:
                raise ValueError(f"line {lineno}: duplicate key {key!r}")
            if kv[1]:
                self.lines[i][1] = kv[1]
                text, i = self.flow_text(i)
                result[key] = self.scalar_or_flow(text, lineno)
            else:
                result[key], i = self.child(i + 1, indent, lineno)
        if i < len(self.lines) and self.lines[i][0] > indent:
            raise ValueError(f"line {self.lines[i][2]}: bad indentation")
        return result, i

    def sequence(self, i, indent):
        result = []
        while i < len(self.lines) and self.lines[i][0] == indent:
            _, body, lineno = self.lines[i]
            if not (body == "-" or body.startswith("- ")):
                break
            rest = body[1:].lstrip(" ")
            if not rest:
                value, i = self.child(i + 1, indent + 1, lineno)
                result.append(value)
                continue
            self.lines[i] = [indent + len(body) - len(rest), rest, lineno]
            value, i = self.node(i, self.lines[i][0])
            result.append(value)
        if i < len(self.lines) and self.lines[i][0] > indent:
            raise ValueError(f"line {self.lines[i][2]}: bad indentation")
        return result, i

    def scalar_or_flow(self, text, lineno):
        if text[:1] in "[{":
            value, pos = self.flow(text, 0, lineno)
            if text[pos:].strip():
                raise ValueError(f"line {lineno}: unexpected content after flow collection")
            return value
        return self.scalar(text, lineno)

    def flow(self, text, pos, lineno):
        def skip(p):
            while p < len(text) and text[p] in " \t":
                p += 1
            return p

        pos = skip(pos)
        if pos >= len(text):
            raise ValueError(f"line {lineno}: unexpected end of flow collection")
        ch = text[pos]
        if ch in "[{":
            close = "]" if ch == "[" else "}"
            result = [] if ch == "[" else {}
            pos = skip(pos + 1)
            while True:
                if pos >= len(text):
                    raise ValueError(f"line {lineno}: unterminated flow collection")
                if text[pos] == close:
                    return result, pos + 1
                if ch == "[":
                    value, pos = self.flow(text, pos, lineno)
                    result.append(value)
                else:
                    key, pos = self.flow_scalar(text, pos, lineno, ":,}")
                    pos = skip(pos)
                    if pos < len(text) and text[pos] == ":":
                        value, pos = self.flow(text, pos + 1, lineno)
                    else:
                        value = None
                    result[key] = value
                pos = skip(pos)
                if pos < len(text) and text[pos] == ",":
                    pos = skip(pos + 1)
                elif pos >= len(text) or text[pos] != close:
                    raise ValueError(f"line {lineno}: expected ',' or '{close}' in flow collection")
        return self.flow_scalar(text, pos, lineno, ",]}")

    def flow_scalar(self, text, pos, lineno, stops):
        if text[pos] in "'\"":
            q = text[pos]
            end = pos + 1
            while True:
                end = text.find(q, end)
                if end < 0:
                    raise ValueError(f"line {lineno}: unterminated quoted string")
                if q == "'" and text[end + 1:end + 2] == "'":
                    end += 2
                    continue
                if q == '"' and text[end - 1] == "\\":
                    end += 1
                    continue
                break
            return self.scalar(text[pos:end + 1], lineno), end + 1
        end = pos
        while end < len(text) and text[end] not in stops:
            if text[end] == ":" and ":" in stops and not (end + 1 == len(text) or text[end + 1] in " ,}"):
                end += 1
                continue
            end += 1
        return self.scalar(text[pos:end].strip(), lineno), end

    @staticmethod
    def scalar(text, lineno):
        if len(text) >= 2 and text[0] == text[-1] and text[0] in "'\"":
            inner = text[1:-1]
            if text[0] == "'":
                return inner.replace("''", "'")
            try:
                return json.loads(text)
            except ValueError:
                raise ValueError(f"line {lineno}: invalid double-quoted string")
        if text[:1] in "'\"":
            raise ValueError(f"line {lineno}: unterminated quoted string")
        if text in ("", "~", "null", "Null", "NULL"):
            return None
        if text in ("true", "True", "TRUE"):
            return True
        if text in ("false", "False", "FALSE"):
            return False
        if re.fullmatch(r"[-+]?\d+", text):
            return int(text)
        if re.fullmatch(r"[-+]?(\d+\.\d*|\.\d+|\d+)([eE][-+]?\d+)?", text):
            return float(text)
        return text


def load_ingest_config(path):
    doc = parse_config_document(read_config_text(path), path)
    if isinstance(doc, dict):
        if "sources" not in doc:
            raise config_error("ingest config must define a 'sources' list")
        entries = doc["sources"]
    elif isinstance(doc, list):
        entries = doc
    else:
        raise config_error("ingest config must be a mapping with a 'sources' list")
    if not isinstance(entries, list) or not entries:
        raise config_error("'sources' in the ingest config must be a non-empty list")
    configs = []
    for i, entry in enumerate(entries, 1):
        sc = parse_source_config(entry, i)
        if any(c.name == sc.name for c in configs):
            raise config_error(f"source name '{sc.name}' is declared more than once")
        configs.append(sc)
    return configs


def config_string_list(value, what, allow_single=True):
    if isinstance(value, str) and allow_single:
        value = [value]
    if not isinstance(value, list):
        raise config_error(f"{what} must be a list of strings")
    for v in value:
        if not isinstance(v, str) or not v.strip():
            raise config_error(f"{what} must contain only non-empty strings")
    return [v.strip() for v in value]


def config_string_map(value, what):
    if not isinstance(value, dict):
        raise config_error(f"{what} must be a mapping")
    for k in value:
        if not isinstance(k, str) or not k.strip():
            raise config_error(f"{what} has an invalid field name {k!r}")
    return value


def parse_source_config(entry, index):
    where = f"sources[{index}]"
    if not isinstance(entry, dict):
        raise config_error(f"{where} must be a mapping")
    for key in entry:
        if key not in SOURCE_KEYS:
            raise config_error(f"{where}: unknown key {key!r}")
    name = entry.get("name")
    if not isinstance(name, str) or not name.strip():
        raise config_error(f"{where}: 'name' must be a non-empty string")
    sc = SourceConfig(name.strip())
    where = f"source '{sc.name}'"

    if "inputs" not in entry or entry["inputs"] is None:
        raise config_error(f"{where}: 'inputs' is required")
    sc.inputs = config_string_list(entry["inputs"], f"{where}: 'inputs'")
    if not sc.inputs:
        raise config_error(f"{where}: 'inputs' must not be empty")

    if entry.get("recursive") is not None:
        if not isinstance(entry["recursive"], bool):
            raise config_error(f"{where}: 'recursive' must be true or false")
        sc.recursive = entry["recursive"]

    if entry.get("format") is not None:
        fmt = entry["format"]
        if not isinstance(fmt, str) or fmt.strip().lower() not in ("auto",) + FORMATS:
            raise config_error(f"{where}: invalid format {fmt!r}; expected auto, csv, tsv or parquet")
        sc.format = fmt.strip().lower()

    if entry.get("schema") is not None:
        if not isinstance(entry["schema"], str) or not entry["schema"].strip():
            raise config_error(f"{where}: 'schema' must be a schema name")
        sc.schema = entry["schema"].strip()

    if entry.get("precedence") is not None:
        prec = entry["precedence"]
        if isinstance(prec, float) and prec.is_integer():
            prec = int(prec)
        if isinstance(prec, bool) or not isinstance(prec, int):
            raise config_error(f"{where}: 'precedence' must be an integer")
        sc.precedence = prec

    if entry.get("tz") is not None:
        if not isinstance(entry["tz"], str) or not entry["tz"].strip():
            raise config_error(f"{where}: 'tz' must be an IANA timezone name")
        try:
            sc.tz = resolve_tz(entry["tz"].strip())
        except MTLError:
            raise config_error(f"{where}: unknown timezone {entry['tz']!r}")

    if "nulls" in entry:
        nulls = entry["nulls"]
        if nulls is None:
            nulls = []
        if isinstance(nulls, str):
            nulls = nulls.split(",")
        if not isinstance(nulls, list):
            raise config_error(f"{where}: 'nulls' must be a list of strings")
        markers = set()
        for m in nulls:
            if m is None:
                markers.update(YAML_NULL_MARKERS)
            elif isinstance(m, (str, int, float)) and not isinstance(m, bool):
                markers.add(str(m))
            else:
                raise config_error(f"{where}: 'nulls' must be a list of strings")
        sc.nulls = frozenset(markers)

    mapping = entry.get("mapping")
    if mapping is not None:
        if not isinstance(mapping, dict):
            raise config_error(f"{where}: 'mapping' must be a mapping")
        for key in mapping:
            if key not in MAPPING_KEYS:
                raise config_error(f"{where}: unknown mapping directive {key!r}; expected drop, rename, cast or defaults")
        if mapping.get("drop") is not None:
            sc.drop = config_string_list(mapping["drop"], f"{where}: mapping.drop")
        if mapping.get("rename") is not None:
            rename = config_string_map(mapping["rename"], f"{where}: mapping.rename")
            targets = set()
            for old, new in rename.items():
                if not isinstance(new, str) or not new.strip():
                    raise config_error(f"{where}: mapping.rename target for '{old}' must be a non-empty string")
                if new.strip() in targets:
                    raise config_error(f"{where}: mapping.rename maps several fields to '{new.strip()}'")
                targets.add(new.strip())
                sc.rename[old.strip()] = new.strip()
        if mapping.get("cast") is not None:
            cast = config_string_map(mapping["cast"], f"{where}: mapping.cast")
            for field, typ in cast.items():
                if not isinstance(typ, str) or typ.strip() not in TYPES:
                    raise config_error(
                        f"{where}: mapping.cast of '{field}' to unknown type {typ!r}; expected one of {', '.join(TYPES)}")
                sc.cast[field.strip()] = typ.strip()
        if mapping.get("defaults") is not None:
            defaults = config_string_map(mapping["defaults"], f"{where}: mapping.defaults")
            for field, value in defaults.items():
                if isinstance(value, (list, dict)):
                    raise config_error(f"{where}: mapping.defaults value for '{field}' must be a scalar")
                sc.defaults[field.strip()] = value

    if entry.get("required") is not None:
        sc.required = config_string_list(entry["required"], f"{where}: 'required'")
    return sc


def bind_config(program, configs):
    """Cross-check the ingest config against the DSL (config errors)."""
    by_name = {sc.name: sc for sc in configs}
    for sc in configs:
        sc.schema_name = sc.schema or program.schema_name
        if sc.schema_name not in program.resolved_schemas:
            raise config_error(f"source '{sc.name}' uses schema '{sc.schema_name}' which is not defined in the DSL")
        fields = program.resolved_schemas[sc.schema_name][0]
        for name in sc.cast:
            if name in fields and fields[name].expr is not None:
                raise config_error(f"source '{sc.name}': mapping.cast targets calculated field '{name}'")
    if program.sources is not None:
        for name, _ in program.sources:
            if name not in by_name:
                raise config_error(f"sources block refers to unknown source '{name}' (not declared in the ingest config)")
    return by_name


# --------------------------------------------------------------------------- file assignment

def expand_source_inputs(sc, cfg_dir, cli_format, cli_recursive, needed):
    """Files matched by a source's patterns: {realpath: (abspath, format)}."""
    forced = sc.format or cli_format
    recursive = cli_recursive if sc.recursive is None else sc.recursive
    found = {}

    def add(path, fmt):
        real = os.path.realpath(path)
        absp = os.path.abspath(path)
        prev = found.get(real)
        if prev is None or absp < prev[0]:
            found[real] = (absp, fmt)

    def add_dir(top):
        for root, dirs, files in os.walk(top):
            dirs[:] = sorted(d for d in dirs if not d.startswith(".")) if recursive else []
            for name in sorted(files):
                if name.startswith("."):
                    continue
                path = os.path.join(root, name)
                fmt = scan_format(path, forced)
                if fmt is not None and os.path.isfile(path):
                    add(path, fmt)

    def expand(pattern):
        """True when the pattern resolved to something (possibly an empty directory)."""
        if os.path.isdir(pattern):
            add_dir(pattern)
            return True
        if os.path.exists(pattern):
            fmt = detect_format(pattern, forced)
            if fmt is None:
                if needed:
                    raise io_error(f"source '{sc.name}': cannot determine the format of input file {pattern}; set 'format'")
                return True
            add(pattern, fmt)
            return True
        if any(ch in pattern for ch in GLOB_CHARS):
            matched = False
            for match in sorted(glob.glob(pattern, recursive=True)):
                if os.path.isdir(match):
                    add_dir(match)
                    matched = True
                elif os.path.isfile(match):
                    fmt = scan_format(match, forced)
                    if fmt is not None:
                        add(match, fmt)
                        matched = True
            return matched
        return False

    for pattern in sc.inputs:
        pattern = os.path.expanduser(pattern)
        candidates = [pattern]
        if not os.path.isabs(pattern) and cfg_dir and os.path.abspath(cfg_dir) != os.getcwd():
            candidates.append(os.path.join(cfg_dir, pattern))
        if not any(expand(c) for c in candidates):
            if needed and not any(ch in pattern for ch in GLOB_CHARS):
                raise io_error(f"source '{sc.name}': input not found: {pattern}")
    return found


def assign_files(configs, needed, cfg_dir, cli_format, cli_recursive):
    """Assign every matched file to exactly one source (lowest precedence wins)."""
    owners = {}  # realpath -> [abspath, {config index: format}]
    for idx, sc in enumerate(configs):
        found = expand_source_inputs(sc, cfg_dir, cli_format, cli_recursive, sc.name in needed)
        if not found and sc.name in needed:
            raise io_error(f"source '{sc.name}': no input files matched {', '.join(sc.inputs)}")
        for real, (absp, fmt) in found.items():
            entry = owners.setdefault(real, [absp, {}])
            entry[0] = min(entry[0], absp)
            entry[1][idx] = fmt
    assigned = {sc.name: [] for sc in configs}
    for absp, cands in sorted(owners.values(), key=lambda e: e[0]):
        best = min(configs[i].precedence for i in cands)
        winners = [i for i in sorted(cands) if configs[i].precedence == best]
        if len(winners) > 1:
            names = ", ".join(f"'{configs[i].name}'" for i in winners)
            raise config_error(f"file {absp} matches sources {names} with equal precedence {best}")
        assigned[configs[winners[0]].name].append((absp, cands[winners[0]]))
    for files in assigned.values():
        files.sort()
    return assigned


# --------------------------------------------------------------------------- per-source mapping & validation

def parse_ts_any(s, opts):
    try:
        return opts.parse_ts(s)
    except (ValueError, OverflowError):
        return opts.parse_iso(s)


def cell_is_null(cell, opts):
    if cell[0] == "text":
        raw = cell[1]
        s = raw.strip()
        return s == "" or raw in opts.nulls or s in opts.nulls
    if cell[0] == "pq":
        v = cell[3]
        if v is None:
            return True
        if isinstance(v, str) and cell[1] == STR:
            return v.strip() == "" or v in opts.nulls or v.strip() in opts.nulls
        return isinstance(v, float) and math.isnan(v)
    return cell[2] is None


def cell_display(cell):
    if cell[0] == "text":
        return cell[1]
    return jsonable(cell[3] if cell[0] == "pq" else cell[2])


def cell_value(cell, typ, name, opts):
    """Convert a (possibly mapped) cell to the schema type `typ`; raises RowError."""
    if cell[0] == "text":
        return convert_text(cell[1], typ, name, opts)
    if cell[0] == "pq":
        _, kind, t, v = cell
        if v is None:
            return None
        try:
            return convert_parquet_value(v, kind, t, typ, name, opts)
        except RowError as e:
            e.value = jsonable(v)
            raise
    _, vt, v = cell
    if v is None or vt == typ:
        return v
    if vt == INT and typ == FLOAT:
        return float(v)
    raise RowError(TYPE_ERROR, f"column '{name}' is {vt} after mapping but the schema requires {typ}", name, jsonable(v))


def cast_cell(cell, typ, name, opts):
    """Apply a mapping.cast directive; returns a ("typed", typ, value) cell."""
    if cell_is_null(cell, opts):
        return ("typed", typ, None)
    if cell[0] == "text":
        if typ == TS:
            try:
                return ("typed", typ, parse_ts_any(cell[1].strip(), opts))
            except (ValueError, OverflowError):
                raise RowError(TIMESTAMP_PARSE_ERROR, f"column '{name}' has invalid timestamp value {cell[1]!r}", name, cell[1])
        return ("typed", typ, convert_text(cell[1], typ, name, opts))
    if cell[0] == "pq":
        _, kind, t, v = cell
        src = ARROW_KIND_TO_TYPE.get(kind)
        if src is None:
            raise RowError(PARQUET_TYPE_MISMATCH, f"column '{name}' has Parquet type {t} which cannot be cast to {typ}", name)
        try:
            v = convert_parquet_value(v, kind, t, src, name, opts)
        except RowError as e:
            e.value = jsonable(v)
            raise
    else:
        _, src, v = cell
    if src == STR and typ != STR:
        try:
            if typ == TS:
                return ("typed", typ, parse_ts_any(v.strip(), opts))
            return ("typed", typ, convert_text(v, typ, name, opts))
        except (ValueError, OverflowError):
            raise RowError(TIMESTAMP_PARSE_ERROR, f"column '{name}' has invalid timestamp value {v!r}", name, v)
    if (src, typ) in ((BOOL, TS), (TS, BOOL)):
        raise RowError(PARSE_TYPE_MISMATCH, f"column '{name}' cannot be cast from {src} to {typ}", name, jsonable(v))
    try:
        return ("typed", typ, cast_value(v, src, typ, None))
    except (ValueError, OverflowError, TypeError, MTLError):
        raise RowError(PARSE_TYPE_MISMATCH, f"column '{name}' value {jsonable(v)!r} cannot be cast to {typ}", name, jsonable(v))


def convert_default(sc, name, value, typ, opts):
    """Convert a mapping.defaults literal to `typ` (or its natural type); config error when impossible."""
    def bad():
        return config_error(f"source '{sc.name}': mapping.defaults value {value!r} for '{name}' is not a valid {typ}")

    if value is None:
        return typ, None
    if isinstance(value, datetime):
        v = value if value.tzinfo is not None else value.replace(tzinfo=opts.tz)
        src, v = TS, v.astimezone(timezone.utc)
    elif hasattr(value, "year") and hasattr(value, "month") and hasattr(value, "day"):
        src, v = TS, datetime(value.year, value.month, value.day, tzinfo=opts.tz).astimezone(timezone.utc)
    elif isinstance(value, bool):
        src, v = BOOL, value
    elif isinstance(value, int):
        src, v = INT, value
    elif isinstance(value, float):
        if not math.isfinite(value):
            raise bad()
        src, v = FLOAT, value
    elif isinstance(value, str):
        src, v = STR, value
    else:
        raise bad()
    if typ is None or typ == src:
        return src, v
    if src == STR:
        try:
            if typ == TS:
                return typ, parse_ts_any(v.strip(), opts)
            converted = convert_text(v, typ, name, opts)
        except (RowError, ValueError, OverflowError):
            raise bad()
        if converted is None:
            raise bad()
        return typ, converted
    if typ == STR:
        return typ, cast_value(v, src, typ, None)
    if src == INT and typ == FLOAT:
        return typ, float(v)
    if src == FLOAT and typ == INT and v.is_integer():
        return typ, int(v)
    if src in NUMERIC and typ == TS:
        try:
            return typ, cast_value(v, src, typ, None)
        except (OverflowError, ValueError):
            raise bad()
    raise bad()


class SourceRuntime:
    """Everything needed to ingest one configured source."""

    def __init__(self, sc, program, args, ctx, with_calcs):
        self.sc = sc
        fields, order = program.resolved_schemas[sc.schema_name]
        self.base = {n: f.typ for n, f in fields.items() if f.expr is None}
        self.env = {n: f.typ for n, f in fields.items()} if with_calcs else dict(self.base)
        self.calc_names = {n for n, f in fields.items() if f.expr is not None} if with_calcs else set()
        tz = sc.tz or args.tz_obj
        self.opts = LoadOptions(tz, make_ts_parser(tz, args.timestamp_format),
                                sc.nulls if sc.nulls is not None else args.nulls_set, args.strict)
        self.defaults = {}
        for name, value in sc.defaults.items():
            target = sc.cast.get(name) or self.base.get(name)
            self.defaults[name] = convert_default(sc, name, value, target, self.opts)
        self.plan = Plan()
        if with_calcs:
            for d in program.deferred_errors:
                raise d
            for name in order:
                f = fields[name]
                t, fn = compile_expr(f.expr, self.env, ctx)
                self.plan.prelude.append((name, fn, declared_conv(f.typ, t, f"calculated field '{name}'")))

    def map_record(self, cells):
        sc, opts = self.sc, self.opts
        for name in sc.drop:
            cells.pop(name, None)
        if sc.rename:
            mapped = {k: v for k, v in cells.items() if k not in sc.rename}
            for old, new in sc.rename.items():
                if old in cells:
                    mapped[new] = cells[old]
            cells = mapped
        for name, typ in sc.cast.items():
            if name in cells:
                cells[name] = cast_cell(cells[name], typ, name, opts)
        for name, (typ, value) in self.defaults.items():
            cell = cells.get(name)
            if cell is None or cell_is_null(cell, opts):
                cells[name] = ("typed", typ, value)
        row = {}
        for name, typ in self.base.items():
            cell = cells.get(name)
            row[name] = None if cell is None else cell_value(cell, typ, name, opts)
        for name in sc.required:
            if name in self.base:
                missing = row[name] is None
            elif name in self.calc_names:
                continue
            else:
                missing = name not in cells or cell_is_null(cells[name], opts)
            if missing:
                raise RowError(MISSING_REQUIRED_FIELD, f"required field '{name}' is missing or null", name)
        return row

    def check_required_calcs(self, row):
        for name in self.sc.required:
            if name in self.calc_names and row.get(name) is None:
                raise RowError(MISSING_REQUIRED_FIELD, f"required field '{name}' is missing or null", name)


def reject(bad, record, err, where, strict):
    bad.append(record)
    if strict:
        raise MTLError(STRICT_EXIT_KIND.get(err.kind, "type_error"), f"{where}: {err.kind}: {err.message}")


def source_bad_record(name, src, line, rownum, err, raw):
    record = bad_record(src, line, rownum, err, raw)
    record["source"] = name
    return record


def ingest_file(rt, path, fmt, bad, strict):
    """Read, map and validate every record of one file of a source; result rows are (row, meta) in line order."""
    src = load_source(path, fmt)
    res = FileResult(src.row_count())
    for line, rownum, cells, err, raw in src.raw_records(rt.opts):
        meta = (src, line, rownum, raw)
        if err is None:
            try:
                row = rt.map_record(cells)
                run_row(rt.plan, row)
                rt.check_required_calcs(row)
                res.rows.append((row, meta))
                res.observe(row.get("timestamp"))
                continue
            except RowError as e:
                err = e
        reject(bad, source_bad_record(rt.sc.name, src, line, rownum, err, raw), err, meta_where(meta), strict)
    return res


def ingest_units(rt, files, run, kind, strict):
    """[(path, format, FileResult)] for a source's files, restoring unchanged completed files from checkpoints."""
    units = []
    for path, fmt in files:
        res = run.tracker.lookup(rt.sc.name, path, fmt, kind)
        if res is None:
            res = ingest_file(rt, path, fmt, run.bad, strict)
        else:
            run.bad.extend(res.bad)
        units.append((path, fmt, res))
    return units


def meta_where(meta):
    src, line, rownum, _ = meta
    return f"{src.path}:{line}" if line is not None else f"{src.path} row {rownum}"


# --------------------------------------------------------------------------- joins

class PairRow:
    """A (left, right) row pair addressed by canonical '<side>:<column>' keys; a missing side reads as nulls."""

    __slots__ = ("left", "right")

    def __init__(self, left, right):
        self.left = left
        self.right = right

    def __getitem__(self, key):
        row = self.left if key[0] == "0" else self.right
        return None if row is None else row[key[2:]]


class JoinPlan:
    def __init__(self, decl, index):
        self.decl = decl
        self.index = index
        self.label = decl.alias or f"join #{index + 1}"
        self.left_key = None
        self.right_key = None
        self.on = None
        self.keys = []  # [(left column, right column)] equality conjuncts usable for hashing
        self.within = decl.within
        self.jtype = decl.jtype
        self.project = []  # [(name, evaluator)]
        self.env = {}


def bind_join_refs(expr, sides):
    """Rewrite column references in a join expression to canonical '<side>:<column>' keys."""
    for n in walk(expr):
        if not isinstance(n, Col):
            continue
        name = n.name
        if "." in name:
            q, col = name.split(".", 1)
            idx = [i for i, (_, quals, _) in enumerate(sides) if q in quals]
            if not idx:
                raise dsl_error(f"'{name}' refers to '{q}', which is not one of the joined relations")
            if col not in sides[idx[0]][2]:
                raise type_error(f"unknown column '{name}'")
            n.name = f"{idx[0]}:{col}"
            continue
        present = [i for i, (_, _, env) in enumerate(sides) if name in env]
        if not present:
            raise type_error(f"unknown column '{name}'")
        if len(present) > 1:
            q = [sorted(sides[i][1] - {"_"} or sides[i][1])[0] for i in present]
            raise dsl_error(f"column '{name}' exists on both sides of the join; qualify it as {q[0]}.{name} or {q[1]}.{name}")
        n.name = f"{present[0]}:{name}"


def conjuncts(node):
    if isinstance(node, Binary) and node.op == "&":
        return conjuncts(node.left) + conjuncts(node.right)
    return [node]


def compile_with_blocks(program, alias, env, ctx):
    """Type-check the alias-scoped pre-stage calcs/filters; returns (plan, env with calc columns)."""
    env = dict(env)
    plan = Plan()
    for block_alias, steps in program.with_blocks:
        if block_alias != alias:
            continue
        for kind, item in steps:
            expr = item.expr if kind == "calc" else item
            for n in walk(expr):
                if isinstance(n, Col) and "." in n.name:
                    q, col = n.name.split(".", 1)
                    if q != alias:
                        raise dsl_error(f"'with {alias}' block cannot reference '{n.name}'")
                    n.name = col
            t, f = compile_expr(expr, env, ctx)
            if kind == "filter":
                if t != BOOL:
                    raise type_error(f"filter expression in 'with {alias}' must be boolean, got {type_name(t)}")
                plan.steps.append(("filter", f, None, None))
            else:
                if item.name in env:
                    raise dsl_error(f"calc '{item.name}' in 'with {alias}' collides with an existing field")
                conv = declared_conv(item.typ, t, f"calc '{item.name}'")
                env[item.name] = item.typ
                plan.steps.append(("set", f, item.name, conv))
    return plan, env


def compile_joins(program, alias_envs, ctx):
    rel_envs = dict(alias_envs)
    join_aliases = {}
    plans = []
    for i, decl in enumerate(program.joins):
        jp = JoinPlan(decl, i)
        sides = []
        for name in (decl.left, decl.right):
            if name == "_":
                key = i - 1
            elif name in alias_envs:
                key = name
            else:
                key = join_aliases[name]
            if isinstance(key, int):
                quals = {"_"} if key == i - 1 else set()
                if program.joins[key].alias:
                    quals.add(program.joins[key].alias)
            else:
                quals = {key}
            sides.append((key, quals, rel_envs[key]))
        jp.left_key, jp.right_key = sides[0][0], sides[1][0]
        schema = {f"{idx}:{col}": typ for idx, (_, _, env) in enumerate(sides) for col, typ in env.items()}

        bind_join_refs(decl.on, sides)
        t, jp.on = compile_expr(decl.on, schema, ctx)
        if t != BOOL:
            raise type_error(f"join 'on' predicate must be boolean, got {type_name(t)}")
        for c in conjuncts(decl.on):
            if isinstance(c, Binary) and c.op == "==" and isinstance(c.left, Col) and isinstance(c.right, Col):
                a, b = c.left.name, c.right.name
                if a[0] != b[0]:
                    if a[0] == "1":
                        a, b = b, a
                    jp.keys.append((a[2:], b[2:]))

        if decl.within is not None:
            for idx, (_, quals, env) in enumerate(sides):
                if "timestamp" not in env:
                    side = "left" if idx == 0 else "right"
                    raise dsl_error(f"'within' requires a 'timestamp' column on both sides of the join; the {side} side has none")
                if env["timestamp"] != TS:
                    raise type_error(f"'within' requires 'timestamp' to be a timestamp, got {type_name(env['timestamp'])}")

        env = {}
        for expr, name in decl.project:
            bind_join_refs(expr, sides)
            t, f = compile_expr(expr, schema, ctx)
            env[name] = t
            jp.project.append((name, f))
        if "timestamp" in env:
            if env["timestamp"] != TS:
                raise type_error(f"projected 'timestamp' must be a timestamp, got {type_name(env['timestamp'])}")
        else:
            left_ts = "timestamp" in sides[0][2]
            right_ts = "timestamp" in sides[1][2]
            if left_ts and right_ts:
                raise type_error("ambiguous timestamp after join: both sides have 'timestamp'; project one of them as 'timestamp'")
            if not left_ts:
                raise type_error("missing timestamp after join: project a timestamp column as 'timestamp'")
            if sides[0][2]["timestamp"] != TS:
                raise type_error("the left side's 'timestamp' is not a timestamp")
            env["timestamp"] = TS
            jp.project.append(("timestamp", lambda pair: pair["0:timestamp"]))
        jp.env = env
        rel_envs[i] = env
        if decl.alias:
            join_aliases[decl.alias] = i
        plans.append(jp)
    return plans


def join_bad_record(label, n, err, record):
    return {
        "file": None,
        "line": None,
        "row": n,
        "format": None,
        "source": label,
        "error_type": err.kind,
        "classification": err.kind,
        "message": err.message,
        "column": err.column,
        "value": err.value,
        "context": {"record": {k: jsonable(v) for k, v in record.items()}},
    }


def row_error(e, label):
    if isinstance(e, MTLError):
        return RowError(TYPE_ERROR if e.kind == "type_error" else RUNTIME_ERROR, f"{label}: {e.message}")
    if isinstance(e, TypeError):
        return RowError(TYPE_ERROR, f"{label}: {e}")
    return RowError(RUNTIME_ERROR, f"{label}: {type(e).__name__}: {e}")


def run_join(jp, left_rows, right_rows, bad, strict):
    out = []
    index = None
    if jp.keys:
        index = {}
        for ri, r in enumerate(right_rows):
            key = tuple(r[c] for _, c in jp.keys)
            if None not in key:
                index.setdefault(key, []).append(ri)
    matched = [False] * len(right_rows)
    within = timedelta(microseconds=jp.within) if jp.within is not None else None

    def emit(left, right):
        pair = PairRow(left, right)
        row = {}
        try:
            for name, f in jp.project:
                row[name] = f(pair)
        except (MTLError, TypeError, ArithmeticError, ValueError) as e:
            err = row_error(e, f"project column '{name}'")
            context = {f"left.{k}": v for k, v in (left or {}).items()}
            context.update({f"right.{k}": v for k, v in (right or {}).items()})
            reject(bad, join_bad_record(jp.label, len(out) + 1, err, context), err, jp.label, strict)
            return
        out.append(row)

    def matches(left, right):
        if within is not None:
            a, b = left.get("timestamp"), right.get("timestamp")
            if a is None or b is None or abs(a - b) > within:
                return False
        try:
            return jp.on(PairRow(left, right)) is True
        except (MTLError, TypeError, ArithmeticError, ValueError) as e:
            if strict:
                err = row_error(e, "join 'on' predicate")
                raise MTLError(STRICT_EXIT_KIND.get(err.kind, "type_error"), f"{jp.label}: {err.kind}: {err.message}")
            return False

    for left in left_rows:
        if index is not None:
            key = tuple(left[c] for c, _ in jp.keys)
            candidates = () if None in key else index.get(key, ())
        else:
            candidates = range(len(right_rows))
        hit = False
        for ri in candidates:
            right = right_rows[ri]
            if matches(left, right):
                hit = True
                matched[ri] = True
                emit(left, right)
        if not hit and jp.jtype in ("left", "full"):
            emit(left, None)
    if jp.jtype in ("right", "full"):
        for ri, right in enumerate(right_rows):
            if not matched[ri]:
                emit(None, right)
    return out


# --------------------------------------------------------------------------- multi-source driver

def run_ingest(args, program, cli_params, ctx, run):
    configs = load_ingest_config(args.ingest_config)
    by_name = bind_config(program, configs)
    ctx.params = resolve_params(program, cli_params, ctx.parse_ts)
    run.params = ctx.params
    bad = run.bad
    if program.sources is None:
        return run_union(args, program, configs, ctx, run)

    # type-check: per-alias environments, with-blocks, joins, then the post-join pipeline
    for d in program.deferred_errors:
        raise d
    needed = []
    for name, _ in program.sources:
        if name not in needed:
            needed.append(name)
    runtimes = {name: SourceRuntime(by_name[name], program, args, ctx, True) for name in needed}
    alias_plans = {}
    alias_envs = {}
    for name, alias in program.sources:
        alias_plans[alias], alias_envs[alias] = compile_with_blocks(program, alias, runtimes[name].env, ctx)
    join_plans = compile_joins(program, alias_envs, ctx)
    program.schema_calc_order = []
    plan = compile_plan(program, join_plans[-1].env, ctx)
    run.plan = plan

    assigned = assign_files(configs, set(needed), os.path.dirname(os.path.abspath(args.ingest_config)),
                            args.format, args.recursive)
    try:
        source_rows = {}
        for sc in configs:
            if sc.name in runtimes:
                run.tracker.declare_source(sc.name)
                rows = []
                for path, fmt, res in ingest_units(runtimes[sc.name], assigned[sc.name], run, "ingest", args.strict):
                    run.tracker.commit(sc.name, path, fmt, res, bad, sc.name, "ingest")
                    rows.extend(res.rows)
                source_rows[sc.name] = rows
        relations = {}
        for name, alias in program.sources:
            kept = []
            for row, meta in source_rows[name]:
                row = dict(row)
                try:
                    if run_row(alias_plans[alias], row):
                        kept.append(row)
                except RowError as e:
                    reject(bad, source_bad_record(name, meta[0], meta[1], meta[2], e, meta[3]), e, meta_where(meta), args.strict)
            relations[alias] = kept
        for jp in join_plans:
            relations[jp.index] = run_join(jp, relations[jp.left_key], relations[jp.right_key], bad, args.strict)
        rows = []
        label = join_plans[-1].label
        for n, row in enumerate(relations[len(join_plans) - 1], 1):
            try:
                if plan.window is not None and row.get("timestamp") is None:
                    raise RowError(MISSING_REQUIRED_FIELD, "row has a null 'timestamp' after the join and cannot be windowed",
                                   "timestamp")
                if run_row(plan, row):
                    rows.append(row)
            except RowError as e:
                reject(bad, join_bad_record(label, n, e, row), e, f"{label} row {n}", args.strict)
    finally:
        write_bad_records(args.bad_records_out, bad)
    return execute(plan, rows)


def run_union(args, program, configs, ctx, run):
    """A single-input pipeline fed by every configured source, each mapped to the pipeline schema."""
    bad = run.bad
    env = {name: f.typ for name, f in program.schema_fields.items()}
    base = {name: f.typ for name, f in program.schema_fields.items() if f.expr is None}
    plan = compile_plan(program, env, ctx)
    run.plan = plan
    runtimes = [SourceRuntime(sc, program, args, ctx, False) for sc in configs]
    for rt in runtimes:
        for name, typ in base.items():
            st = rt.base.get(name)
            if st is not None and st != typ and not (st == INT and typ == FLOAT):
                raise type_error(f"source '{rt.sc.name}' field '{name}' is {st} but pipeline schema "
                                 f"'{program.schema_name}' requires {typ}")
    assigned = assign_files(configs, {sc.name for sc in configs}, os.path.dirname(os.path.abspath(args.ingest_config)),
                            args.format, args.recursive)
    rows = []
    try:
        for rt in runtimes:
            name = rt.sc.name
            run.tracker.declare_source(name)
            for path, fmt, res in ingest_units(rt, assigned[name], run, "union", args.strict):
                if not res.reused:
                    kept = []
                    for row, meta in res.rows:
                        row = {col: (float(row[col]) if typ == FLOAT and isinstance(row.get(col), int) else row.get(col))
                               for col, typ in base.items()}
                        try:
                            if run_row(plan, row):
                                kept.append(row)
                        except RowError as e:
                            reject(bad, source_bad_record(name, meta[0], meta[1], meta[2], e, meta[3]), e,
                                   meta_where(meta), args.strict)
                    res.rows = kept
                run.tracker.commit(name, path, fmt, res, bad, name, "union")
                rows.extend(res.rows)
    finally:
        write_bad_records(args.bad_records_out, bad)
    return execute(plan, rows)


# --------------------------------------------------------------------------- user-defined functions

UDF_TYPE_NAMES = {
    "int": INT, "integer": INT,
    "float": FLOAT, "double": FLOAT, "number": FLOAT,
    "string": STR, "str": STR,
    "bool": BOOL, "boolean": BOOL,
    "timestamp": TS, "datetime": TS,
}
UDF_ANNOTATIONS = {int: INT, float: FLOAT, str: STR, bool: BOOL, datetime: TS}
UDF_SPEC_KEYS = {
    "fn": ("fn", "func", "function", "callable", "impl"),
    "args": ("args", "arg_types", "params", "signature"),
    "returns": ("returns", "return", "return_type", "ret"),
}


class Udf:
    def __init__(self, name, fn, args, returns, digest):
        self.name = name
        self.fn = fn
        self.args = args
        self.returns = returns
        self.hash = digest


def udf_type(value, what):
    if isinstance(value, type) and value in UDF_ANNOTATIONS:
        return UDF_ANNOTATIONS[value]
    if isinstance(value, str) and value.strip().lower() in UDF_TYPE_NAMES:
        return UDF_TYPE_NAMES[value.strip().lower()]
    raise config_error(f"{what}: unknown type {value!r}; expected one of {', '.join(TYPES)}")


class UdfRegistry:
    """Collects registrations from one --udf file (decorator, register() hook or a UDFS table)."""

    def __init__(self, path):
        self.path = path
        self.entries = []  # (name, fn, args, returns)

    def register(self, name=None, fn=None, args=None, returns=None, **aliases):
        if callable(name) and fn is None:
            name, fn = None, name
        for key, names in UDF_SPEC_KEYS.items():
            for alias in names:
                if alias in aliases:
                    value = aliases.pop(alias)
                    if key == "fn":
                        fn = value
                    elif key == "args":
                        args = value
                    else:
                        returns = value
        if aliases:
            raise config_error(f"UDF file {self.path}: unknown registration option(s) {', '.join(sorted(aliases))}")
        if fn is None:
            # used as a decorator factory: register("name", args=[...], returns=...)
            def decorator(f):
                self.register(name, f, args, returns)
                return f
            return decorator
        self.entries.append((name, fn, args, returns))
        return fn

    __call__ = register

    def decorator(self, *types, name=None, args=None, returns=None, **aliases):
        """@udf, @udf(args=[...], returns=...), @udf("float", "float", returns="float")."""
        if len(types) == 1 and callable(types[0]) and not isinstance(types[0], type) and args is None and returns is None:
            self.register(None, types[0])
            return types[0]
        if types:
            args = list(types)

        def wrap(f):
            self.register(name, f, args, returns, **aliases)
            return f
        return wrap

    def add_table(self, table):
        if isinstance(table, dict):
            items = []
            for key, spec in table.items():
                if isinstance(spec, dict):
                    spec = dict(spec)
                    spec.setdefault("name", key)
                    items.append(spec)
                elif isinstance(spec, (list, tuple)):
                    items.append({"name": key, "fn": spec[0], "args": spec[1] if len(spec) > 1 else None,
                                  "returns": spec[2] if len(spec) > 2 else None})
                else:
                    items.append({"name": key, "fn": spec})
            table = items
        if not isinstance(table, (list, tuple)):
            raise config_error(f"UDF file {self.path}: UDFS must be a mapping or a list of UDF specifications")
        for spec in table:
            if callable(spec):
                self.register(None, spec)
                continue
            if not isinstance(spec, dict):
                raise config_error(f"UDF file {self.path}: invalid UDF specification {spec!r}")
            spec = dict(spec)
            self.register(spec.pop("name", None), **spec)


def annotated_signature(fn, what):
    """(args, returns) from a function's type annotations, or None when they are incomplete."""
    import inspect
    try:
        sig = inspect.signature(fn)
    except (TypeError, ValueError):
        return None
    params = list(sig.parameters.values())
    if any(p.kind not in (p.POSITIONAL_ONLY, p.POSITIONAL_OR_KEYWORD) for p in params):
        return None
    if sig.return_annotation is sig.empty or any(p.annotation is p.empty for p in params):
        return None
    return [udf_type(p.annotation, what) for p in params], udf_type(sig.return_annotation, what)


def load_udf_file(path, index):
    try:
        with open(path, "rb") as f:
            data = f.read()
    except FileNotFoundError:
        raise io_error(f"UDF file not found: {path}")
    except IsADirectoryError:
        raise io_error(f"UDF path is a directory: {path}")
    except OSError as e:
        raise io_error(f"cannot read UDF file {path}: {e.strerror or e}")
    digest = hashlib.sha256(data).hexdigest()
    registry = UdfRegistry(path)
    module_name = f"mtl_udf_{index}"
    namespace = {"__name__": module_name, "__file__": os.path.abspath(path), "__builtins__": __builtins__,
                 "udf": registry.decorator, "register_udf": registry.register}
    try:
        exec(compile(data, path, "exec"), namespace)
        hook = namespace.get("register")
        if callable(hook) and getattr(hook, "__module__", None) == module_name:
            hook(registry)
        for key in ("UDFS", "udfs"):
            if key in namespace and not callable(namespace[key]):
                registry.add_table(namespace[key])
    except MTLError:
        raise
    except Exception as e:  # syntax errors and anything raised while registering
        raise config_error(f"cannot load UDF file {path}: {type(e).__name__}: {' '.join(str(e).split())}")
    if not registry.entries:
        # fall back to every fully annotated public function defined in the file
        for name, obj in namespace.items():
            if (not name.startswith("_") and callable(obj) and getattr(obj, "__module__", None) == module_name
                    and not isinstance(obj, type) and name != "register"):
                sig = annotated_signature(obj, f"UDF '{name}' in {path}")
                if sig is not None:
                    registry.entries.append((name, obj, sig[0], sig[1]))
    if not registry.entries:
        raise config_error(f"UDF file {path} does not register any functions")
    udfs = []
    for name, fn, args, returns in registry.entries:
        if name is None:
            name = getattr(fn, "__name__", None)
        what = f"UDF '{name}' in {path}"
        if not isinstance(name, str) or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name):
            raise config_error(f"UDF file {path}: invalid function name {name!r}")
        if not callable(fn):
            raise config_error(f"{what} is not callable")
        if args is None or returns is None:
            sig = annotated_signature(fn, what)
            if sig is None:
                raise config_error(f"{what} needs argument and return types (args=[...], returns=...)")
            args = sig[0] if args is None else args
            returns = sig[1] if returns is None else returns
        if isinstance(args, str):
            args = [a for a in (x.strip() for x in args.split(",")) if a]
        if not isinstance(args, (list, tuple)):
            raise config_error(f"{what}: args must be a list of types")
        udfs.append(Udf(name, fn, [udf_type(a, what) for a in args], udf_type(returns, what), digest))
    return udfs


def load_udfs(paths):
    registry = {}
    for i, path in enumerate(paths):
        for udf in load_udf_file(path, i):
            if udf.name in FUNCTION_ARITY or udf.name in ("cast",) + RESERVED_WORDS:
                raise config_error(f"UDF '{udf.name}' in {path} collides with a built-in function or keyword")
            if udf.name in registry:
                raise config_error(f"UDF '{udf.name}' is registered more than once")
            registry[udf.name] = udf
    return registry


# --------------------------------------------------------------------------- file fingerprints

XXH_P1 = 11400714785074694791
XXH_P2 = 14029467366897019727
XXH_P3 = 1609587929392839161
XXH_P4 = 9650029242287828579
XXH_P5 = 2870177450012600261
U64 = (1 << 64) - 1


def xxh64_round(acc, lane):
    acc = (acc + lane * XXH_P2) & U64
    acc = ((acc << 31) | (acc >> 33)) & U64
    return (acc * XXH_P1) & U64


def xxh64_merge(h, v):
    h ^= xxh64_round(0, v)
    return (h * XXH_P1 + XXH_P4) & U64


def xxh64_py(data, seed=0):
    """Reference XXH64 (used when the 'xxhash' package is unavailable)."""
    n = len(data)
    i = 0
    if n >= 32:
        v1 = (seed + XXH_P1 + XXH_P2) & U64
        v2 = (seed + XXH_P2) & U64
        v3 = seed & U64
        v4 = (seed - XXH_P1) & U64
        unpack = struct.Struct("<4Q").unpack_from
        while i <= n - 32:
            a, b, c, d = unpack(data, i)
            v1, v2, v3, v4 = xxh64_round(v1, a), xxh64_round(v2, b), xxh64_round(v3, c), xxh64_round(v4, d)
            i += 32
        h = (((v1 << 1) | (v1 >> 63)) + ((v2 << 7) | (v2 >> 57)) + ((v3 << 12) | (v3 >> 52))
             + ((v4 << 18) | (v4 >> 46))) & U64
        for v in (v1, v2, v3, v4):
            h = xxh64_merge(h, v)
    else:
        h = (seed + XXH_P5) & U64
    h = (h + n) & U64
    while i + 8 <= n:
        h ^= xxh64_round(0, struct.unpack_from("<Q", data, i)[0])
        h = ((((h << 27) | (h >> 37)) & U64) * XXH_P1 + XXH_P4) & U64
        i += 8
    if i + 4 <= n:
        h ^= (struct.unpack_from("<I", data, i)[0] * XXH_P1) & U64
        h = ((((h << 23) | (h >> 41)) & U64) * XXH_P2 + XXH_P3) & U64
        i += 4
    while i < n:
        h ^= (data[i] * XXH_P5) & U64
        h = ((((h << 11) | (h >> 53)) & U64) * XXH_P1) & U64
        i += 1
    h ^= h >> 33
    h = (h * XXH_P2) & U64
    h ^= h >> 29
    h = (h * XXH_P3) & U64
    h ^= h >> 32
    return h


def xxh64_hex(data):
    try:
        import xxhash
    except ImportError:
        return f"{xxh64_py(data):016x}"
    return xxhash.xxh64_hexdigest(data)


FINGERPRINT_SCHEMES = ("mtime_size", "xxhash64")


def file_fingerprint(path, scheme):
    if scheme == "mtime_size":
        try:
            st = os.stat(path)
        except OSError as e:
            raise io_error(f"cannot stat input file {path}: {e.strerror or e}")
        return {"scheme": "mtime_size", "mtime_epoch_ms": st.st_mtime_ns // 1_000_000, "size_bytes": st.st_size}
    data = read_bytes(path)
    if data[:2] == b"\x1f\x8b" or path.lower().endswith(".gz"):
        try:
            data = gzip.decompress(data)
        except (OSError, EOFError, zlib.error):
            pass  # hash the raw bytes; reading the file reports the corruption
    return {"scheme": "xxhash64", "hash": xxh64_hex(data)}


# --------------------------------------------------------------------------- file-level checkpoints

DEFAULT_SOURCE = "default"


class FileResult:
    """The committed contribution of one input file: its surviving rows plus bookkeeping."""

    def __init__(self, rows_read):
        self.rows = []  # row dicts, or (row, meta) pairs for sources feeding joins
        self.rows_read = rows_read
        self.max_ts = None
        self.types = None  # legacy DSL: inferred types of the file's extra columns
        self.schema = None  # legacy DSL: the column types the rows were read with
        self.bad = []  # bad records restored from a checkpoint
        self.reused = False

    def observe(self, ts):
        if isinstance(ts, datetime) and (self.max_ts is None or ts > self.max_ts):
            self.max_ts = ts


def encode_value(v):
    if isinstance(v, datetime):
        return {"ts": (v - EPOCH) // ONE_US}
    return v


def decode_value(v):
    if isinstance(v, dict):
        return EPOCH + timedelta(microseconds=v["ts"])
    return v


def ts_to_us(ts):
    return None if ts is None else (ts - EPOCH) // ONE_US


def us_to_ts(us):
    return None if us is None else EPOCH + timedelta(microseconds=us)


def encode_checkpoint(res, kind, file_bad):
    rows = [r[0] for r in res.rows] if kind == "ingest" else res.rows
    columns = list(rows[0]) if rows else []
    encoded = []
    for row in rows:
        if list(row) == columns:
            encoded.append([encode_value(v) for v in row.values()])
        else:
            encoded.append({k: encode_value(v) for k, v in row.items()})
    cp = {
        "kind": kind,
        "rows_read": res.rows_read,
        "max_ts_us": ts_to_us(res.max_ts),
        "bad": file_bad,
        "columns": columns,
        "rows": encoded,
    }
    if kind == "ingest":
        cp["meta"] = [[m[1], m[2], m[0].context(m[3])] for _, m in res.rows]
    if kind == "legacy":
        cp["types"] = res.types
        cp["schema"] = res.schema
    return cp


def decode_checkpoint(cp, path, fmt):
    res = FileResult(int(cp["rows_read"]))
    res.reused = True
    res.max_ts = us_to_ts(cp["max_ts_us"])
    res.bad = [dict(b, file=path) if b.get("file") is not None else dict(b) for b in cp["bad"]]
    columns = cp["columns"]
    rows = []
    for item in cp["rows"]:
        if isinstance(item, dict):
            rows.append({k: decode_value(v) for k, v in item.items()})
        else:
            if len(item) != len(columns):
                raise ValueError("checkpoint row width mismatch")
            rows.append({k: decode_value(v) for k, v in zip(columns, item)})
    if cp["kind"] == "ingest":
        src = StoredSource(path, fmt)
        meta = cp["meta"]
        if len(meta) != len(rows):
            raise ValueError("checkpoint metadata mismatch")
        res.rows = [(row, (src, m[0], m[1], m[2])) for row, m in zip(rows, meta)]
    else:
        res.rows = rows
    if cp["kind"] == "legacy":
        if not isinstance(cp["types"], dict) or not isinstance(cp["schema"], dict):
            raise ValueError("legacy checkpoint without types")
        res.types = cp["types"]
        res.schema = cp["schema"]
    return res


class Tracker:
    """Fingerprints input files, restores unchanged completed files and records each file unit once it is done."""

    def __init__(self, scheme, fingerprints, keep, previous):
        self.scheme = scheme
        self.fingerprints = fingerprints  # compute fingerprints (state or metadata requested)
        self.keep = keep  # keep checkpoint payloads for the state file
        self.previous = previous  # (source, canonical path) -> (fingerprint, checkpoint)
        self.units = {}  # (source, canonical path) -> unit
        self.sources = []
        self.seen = {}  # (source, display path) -> (canonical path, fingerprint)

    def declare_source(self, name):
        if name not in self.sources:
            self.sources.append(name)

    def identify(self, source, path):
        key = (source, path)
        if key not in self.seen:
            fp = file_fingerprint(path, self.scheme) if self.fingerprints else None
            self.seen[key] = (os.path.realpath(path), fp)
        return self.seen[key]

    def lookup(self, source, path, fmt, kind):
        """The checkpointed result of an unchanged, completed file; None when the file must be processed."""
        canon, fp = self.identify(source, path)
        prev = self.previous.get((source, canon))
        if prev is None or fp is None:
            return None
        prev_fp, cp = prev
        if prev_fp != fp or cp.get("kind") != kind or cp.get("format") != fmt:
            return None
        try:
            return decode_checkpoint(cp, path, fmt)
        except (KeyError, TypeError, ValueError, IndexError, AttributeError, OverflowError):
            return None

    def commit(self, source, path, fmt, res, bad, bad_source, kind):
        """Mark a file unit done once its rows are committed to the run's accumulators."""
        self.declare_source(source)
        canon, fp = self.identify(source, path)
        unit = {
            "source": source,
            "path": canon,
            "display": path,
            "bad_key": (bad_source, path),
            "fingerprint": fp,
            "format": fmt,
            "rows_read": res.rows_read,
            "max_ts": res.max_ts,
        }
        if self.keep:
            if res.reused:
                file_bad = res.bad
            else:
                file_bad = [b for b in bad if b.get("source") == bad_source and b.get("file") == path]
            cp = encode_checkpoint(res, kind, file_bad)
            cp["source"] = source
            cp["path"] = canon
            cp["format"] = fmt
            unit["checkpoint"] = cp
        self.units[(source, canon)] = unit

    def sorted_units(self):
        return sorted(self.units.values(), key=lambda u: (u["path"], u["source"]))

    def watermarks(self):
        marks = {}
        for name in sorted(set(self.sources)):
            stamps = [u["max_ts"] for u in self.units.values() if u["source"] == name and u["max_ts"] is not None]
            marks[name] = {"max_timestamp_utc": format_ts(max(stamps)) if stamps else None}
        return marks


class Run:
    def __init__(self, tracker):
        self.tracker = tracker
        self.bad = []
        self.plan = None
        self.params = {}
        self.legacy_types = {}  # display path -> inferred extra column types (legacy DSL)


# --------------------------------------------------------------------------- resumable state

STATE_FILE_KEYS = ("pipeline", "dsl_version", "dsl_sha256", "ingest_config_sha256", "created_at", "last_run")


def iso_now():
    return datetime.now(timezone.utc)


def format_instant(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def sha256_hex(data):
    return hashlib.sha256(data).hexdigest()


def prepare_state_dir(path):
    if os.path.exists(path) and not os.path.isdir(path):
        raise artifact_error(f"state directory conflict: {path} exists and is not a directory")
    try:
        os.makedirs(path, exist_ok=True)
    except OSError as e:
        raise artifact_error(f"state directory conflict: cannot create {path}: {e.strerror or e}")


def state_file_path(state_dir, pipeline):
    return os.path.join(state_dir, f"{pipeline}.state.json")


def load_state(path, pipeline):
    if os.path.isdir(path):
        raise artifact_error(f"state directory conflict: {path} is a directory")
    if not os.path.exists(path):
        raise artifact_error(f"cannot resume: state file {path} does not exist (run once without --resume)")
    try:
        with open(path, "rb") as f:
            doc = json.loads(f.read().decode("utf-8"))
    except (OSError, UnicodeDecodeError, ValueError) as e:
        raise artifact_error(f"malformed state file {path}: {' '.join(str(e).split())}")

    def malformed(what):
        return artifact_error(f"malformed state file {path}: {what}")

    if not isinstance(doc, dict):
        raise malformed("expected a JSON object")
    for key in STATE_FILE_KEYS:
        if key not in doc:
            raise malformed(f"missing '{key}'")
    for key in ("pipeline", "dsl_version", "dsl_sha256", "created_at"):
        if not isinstance(doc[key], str):
            raise malformed(f"'{key}' must be a string")
    if doc["ingest_config_sha256"] is not None and not isinstance(doc["ingest_config_sha256"], str):
        raise malformed("'ingest_config_sha256' must be a string or null")
    last = doc["last_run"]
    if not isinstance(last, dict) or not isinstance(last.get("files"), list):
        raise malformed("'last_run.files' must be a list")
    for entry in last["files"]:
        if (not isinstance(entry, dict) or not isinstance(entry.get("source"), str)
                or not isinstance(entry.get("path"), str) or not isinstance(entry.get("fingerprint"), dict)
                or not isinstance(entry.get("status"), str)):
            raise malformed("invalid entry in 'last_run.files'")
    if doc["pipeline"] != pipeline:
        raise artifact_error(f"state directory conflict: {path} belongs to pipeline '{doc['pipeline']}', not '{pipeline}'")
    return doc


def previous_checkpoints(doc, settings_sha):
    """(source, path) -> (fingerprint, checkpoint) for files the previous run completed under identical settings."""
    if doc.get("runtime") != MTL_RUNTIME_VERSION or doc.get("settings_sha256") != settings_sha:
        return {}
    done = {(f["source"], f["path"]): f["fingerprint"] for f in doc["last_run"]["files"] if f["status"] == "done"}
    out = {}
    cps = doc.get("checkpoints")
    if not isinstance(cps, list):
        return {}
    for cp in cps:
        if not isinstance(cp, dict):
            continue
        key = (cp.get("source"), cp.get("path"))
        if key in done:
            out[key] = (done[key], cp)
    return out


def write_state(state_dir, path, doc, checkpoints):
    head = json.dumps(doc, indent=2, ensure_ascii=False)
    body = json.dumps(checkpoints, ensure_ascii=False, separators=(",", ":"))
    text = head[:-2] + ',\n  "checkpoints": ' + body + "\n}\n"
    tmp = None
    try:
        fd, tmp = tempfile.mkstemp(prefix=f".{os.path.basename(path)}.", suffix=".tmp", dir=state_dir)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
        tmp = None
    except OSError as e:
        raise artifact_error(f"cannot write state file {path}: {e.strerror or e}")
    finally:
        if tmp is not None:
            try:
                os.unlink(tmp)
            except OSError:
                pass


# --------------------------------------------------------------------------- run metadata

BAD_RECORD_KINDS = (PARSE_TYPE_MISMATCH, TIMESTAMP_PARSE_ERROR, RUNTIME_ERROR, TYPE_ERROR, MISSING_REQUIRED_FIELD,
                    PARQUET_TYPE_MISMATCH)


def metadata_value(v):
    if isinstance(v, datetime):
        return format_ts(v)
    return v


def build_metadata(args, info, program, run, result, started, completed):
    tracker = run.tracker
    plan = run.plan
    bad_counts = {}
    for b in run.bad:
        key = (b.get("source"), b.get("file"))
        bad_counts[key] = bad_counts.get(key, 0) + 1
    sources = []
    for name in sorted(set(tracker.sources)):
        files = []
        for u in tracker.sorted_units():
            if u["source"] != name:
                continue
            rows_bad = bad_counts.get(u["bad_key"], 0)
            files.append({
                "path": u["path"],
                "fingerprint": u["fingerprint"],
                "format": u["format"],
                "rows_read": u["rows_read"],
                "rows_valid": max(u["rows_read"] - rows_bad, 0),
                "rows_bad": rows_bad,
            })
        sources.append({"name": name, "files": files})
    kinds = {k: 0 for k in BAD_RECORD_KINDS}
    for b in run.bad:
        kinds[b["classification"]] = kinds.get(b["classification"], 0) + 1
    windowed = plan.window is not None
    joins = []
    for j in program.joins:
        joins.append({
            "left": j.left,
            "right": j.right,
            "type": j.jtype,
            "temporal_within": j.within_text,
            "on_keys": list(j.on_keys),
        })
    udfs = sorted(UDFS.values(), key=lambda u: (u.name, u.args, u.returns))
    return {
        "run": {
            "run_id": info["run_id"],
            "started_at": format_instant(started),
            "completed_at": format_instant(completed),
            "duration_ms": max(int((completed - started) / timedelta(milliseconds=1)), 0),
            "resume": bool(args.resume),
        },
        "versions": {
            "mtl_runtime": MTL_RUNTIME_VERSION,
            "dsl_version": info["dsl_version"],
            "dsl_sha256": info["dsl_sha256"],
            "ingest_config_sha256": info["ingest_config_sha256"],
        },
        "inputs": {
            "sources": sources,
            "params": {name: metadata_value(run.params[name][1]) for name in sorted(run.params)},
            "tz": args.tz,
            "timestamp_format": args.timestamp_format,
            "null_markers": sorted(set(args.nulls_set) | {""}),
        },
        "pipeline": {
            "name": info["pipeline"],
            "schema": program.schema_name,
            "group_by": list(program.group_by or []),
            "window": {"duration": plan.window_text, "aligned_to_epoch": True} if windowed else None,
            "aggregates": sorted(a[2] for a in program.aggregates),
            "post_agg_calcs": sorted(c.name for c in program.post_calcs),
            "joins": joins,
        },
        "udfs": [{"name": u.name, "args": list(u.args), "returns": u.returns, "hash": u.hash} for u in udfs],
        "quality": {
            "strict": bool(args.strict),
            "bad_record_counts": kinds,
        },
        "output": {
            "shape": "object" if isinstance(result, dict) else "array",
            "row_count": 1 if isinstance(result, dict) else len(result),
            "ordering": {
                "primary": "window_start" if windowed else None,
                "secondary": list(plan.group_cols),
            },
            "key_ordering": {
                "window_keys_first": True,
                "aggregate_aliases_lex": True,
                "post_agg_calcs_lex": True,
            },
        },
    }


def write_json_file(path, obj, what):
    text = json.dumps(obj, indent=2, ensure_ascii=False) + "\n"
    try:
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)
    except OSError as e:
        raise io_error(f"cannot write {what} {path}: {e.strerror or e}")


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
    """The DSL as (raw bytes, text)."""
    try:
        if path == "-":
            data = sys.stdin.buffer.read()
        else:
            with open(path, "rb") as f:
                data = f.read()
    except FileNotFoundError:
        raise io_error(f"DSL file not found: {path}")
    except IsADirectoryError:
        raise io_error(f"DSL path is a directory: {path}")
    except OSError as e:
        where = "STDIN" if path == "-" else f"DSL file {path}"
        raise io_error(f"cannot read {where}: {e.strerror or e}")
    try:
        return data, data.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise io_error("DSL from STDIN is not valid UTF-8" if path == "-" else f"DSL file is not valid UTF-8: {path}")


def read_config_bytes(path):
    try:
        with open(path, "rb") as f:
            return f.read()
    except FileNotFoundError:
        raise io_error(f"ingest config not found: {path}")
    except IsADirectoryError:
        raise io_error(f"ingest config path is a directory: {path}")
    except OSError as e:
        raise io_error(f"cannot read ingest config {path}: {e.strerror or e}")


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


def run_settings_sha(args, cli_params):
    """Everything besides the DSL and ingest config that shapes how a single file is read and evaluated."""
    settings = {
        "runtime": MTL_RUNTIME_VERSION,
        "tz": args.tz,
        "timestamp_format": args.timestamp_format,
        "nulls": sorted(args.nulls_set),
        "strict": bool(args.strict),
        "format": args.format,
        "recursive": bool(args.recursive),
        "params": sorted(cli_params.items()),
        "udfs": sorted((u.name, u.args, u.returns, u.hash) for u in UDFS.values()),
        "mode": "ingest" if args.ingest_config is not None else "input",
    }
    return sha256_hex(json.dumps(settings, sort_keys=True).encode("utf-8"))


def main(argv=None):
    parser = ArgParser(prog="mtl.py", description="Run an MTL pipeline over CSV/TSV/Parquet files of sales events.")
    parser.add_argument("--input", "--csv", dest="input", action="append", nargs="+", default=[], metavar="PATH")
    parser.add_argument("--dsl", required=True)
    parser.add_argument("--out", default=None)
    parser.add_argument("--tz", default="UTC")
    parser.add_argument("--timestamp-format", dest="timestamp_format", default=None)
    parser.add_argument("--strict", action="store_true")
    parser.add_argument("--param", action="append", nargs="+", default=[], metavar="KEY=VALUE")
    parser.add_argument("--recursive", action="store_true")
    parser.add_argument("--format", dest="format", default="auto", choices=("auto",) + FORMATS)
    parser.add_argument("--nulls", default=None)
    parser.add_argument("--bad-records-out", dest="bad_records_out", default=None)
    parser.add_argument("--ingest-config", dest="ingest_config", default=None)
    parser.add_argument("--udf", action="append", nargs="+", default=[], metavar="PATH")
    parser.add_argument("--meta-out", dest="meta_out", default=None)
    parser.add_argument("--state-dir", dest="state_dir", default=None)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--fingerprint", default="mtime_size", choices=FINGERPRINT_SCHEMES)
    parser.add_argument("--checkpoint-granularity", dest="checkpoint_granularity", default="file",
                        choices=("file", "rowgroup", "line"))
    args = parser.parse_args(argv)
    started = iso_now()
    if args.resume and not args.state_dir:
        raise artifact_error("--resume requires --state-dir")
    inputs = [p for group in args.input for p in group]
    udf_paths = [p for group in args.udf for p in group]

    dsl_bytes, dsl_text = read_dsl(args.dsl)
    version, dsl_text = split_version_header(dsl_text)
    if args.ingest_config is not None:
        require_version(version, V_SOURCES, "--ingest-config")
    if udf_paths:
        require_version(version, V_SOURCES, "--udf")
    UDFS.clear()
    UDFS.update(load_udfs(udf_paths))
    cli_params = parse_cli_params(args.param)

    if not inputs and args.ingest_config is None:
        has_sources = False
        try:
            program = parse_program(dsl_text, cli_params)
            has_sources = program.block and program.sources is not None
        except MTLError:
            pass
        if has_sources:
            raise config_error("--ingest-config is required for pipelines with a 'sources { ... }' block")
        raise io_error("invalid arguments: the following arguments are required: --input or --ingest-config")

    tz = resolve_tz(args.tz)
    parse_ts = make_ts_parser(tz, args.timestamp_format)
    opts = LoadOptions(tz, parse_ts, parse_null_markers(args.nulls), args.strict)
    args.tz_obj = tz
    args.nulls_set = opts.nulls
    program = parse_program(dsl_text, cli_params)
    check_feature_gates(program, version)
    ctx = Context(tz, parse_ts, {}, args.strict)
    if program.with_errors:
        raise program.with_errors[0]
    if args.ingest_config is None and program.sources is not None:
        raise config_error("--ingest-config is required for pipelines with a 'sources { ... }' block")

    # resumable state
    pipeline_name = program.name or DEFAULT_SOURCE
    config_sha = sha256_hex(read_config_bytes(args.ingest_config)) if args.ingest_config is not None else None
    info = {
        "run_id": str(uuid.uuid4()),
        "pipeline": pipeline_name,
        "dsl_version": version_text(version),
        "dsl_sha256": sha256_hex(dsl_bytes),
        "ingest_config_sha256": config_sha,
    }
    previous = {}
    prior_state = None
    state_path = None
    settings_sha = run_settings_sha(args, cli_params)
    if args.state_dir:
        prepare_state_dir(args.state_dir)
        state_path = state_file_path(args.state_dir, pipeline_name)
        if args.resume:
            prior_state = load_state(state_path, pipeline_name)
            changed = [key for key in ("dsl_sha256", "ingest_config_sha256") if prior_state[key] != info[key]]
            if changed:
                raise artifact_error(f"breaking change: {' and '.join(changed)} mismatch with the state in {state_path}; "
                                     "the DSL or ingest config changed since the last run (start a fresh run without --resume)")
            previous = previous_checkpoints(prior_state, settings_sha)
        elif os.path.isdir(state_path):
            raise artifact_error(f"state directory conflict: {state_path} is a directory")
    tracker = Tracker(args.fingerprint, bool(args.state_dir or args.meta_out), bool(args.state_dir), previous)
    run = Run(tracker)

    if args.ingest_config is not None:
        if not program.block:
            load_ingest_config(args.ingest_config)
            raise config_error("--ingest-config requires a DSL with schema and pipeline blocks")
        result = run_ingest(args, program, cli_params, ctx, run)
    else:
        result = run_inputs(args, program, cli_params, ctx, opts, inputs, run)

    write_result(args, result)
    completed = iso_now()
    if args.meta_out:
        write_json_file(args.meta_out, build_metadata(args, info, program, run, result, started, completed),
                        "metadata file")
    if args.state_dir:
        units = tracker.sorted_units()
        doc = {
            "pipeline": pipeline_name,
            "dsl_version": info["dsl_version"],
            "dsl_sha256": info["dsl_sha256"],
            "ingest_config_sha256": config_sha,
            "created_at": prior_state["created_at"] if prior_state is not None else format_instant(started),
            "last_run": {
                "run_id": info["run_id"],
                "completed_at": format_instant(completed),
                "files": [{"source": u["source"], "path": u["path"], "fingerprint": u["fingerprint"], "status": "done"}
                          for u in units],
                "watermarks": tracker.watermarks(),
            },
            "runtime": MTL_RUNTIME_VERSION,
            "settings_sha256": settings_sha,
            "fingerprint_scheme": args.fingerprint,
            "checkpoint_granularity": args.checkpoint_granularity,
        }
        write_state(args.state_dir, state_path, doc, [u["checkpoint"] for u in units])
    warning = version_warning(version, args)
    if warning:
        sys.stderr.write(warning + "\n")
    return 0


def run_inputs(args, program, cli_params, ctx, opts, inputs, run):
    """Pipelines fed by --input files (block DSL with a schema, or the legacy schema-less DSL)."""
    tracker = run.tracker
    tracker.declare_source(DEFAULT_SOURCE)
    if program.block:
        ctx.params = resolve_params(program, cli_params, ctx.parse_ts)
        run.params = ctx.params
        env = {name: f.typ for name, f in program.schema_fields.items()}
        plan = compile_plan(program, env, ctx)
        fields = {name: f.typ for name, f in program.schema_fields.items() if f.expr is None}
        required = set(fields)
        kind = "rows"
    else:
        opts.legacy = True
        kind = "legacy"
    files = resolve_inputs(inputs, args.recursive, args.format)
    reused = {}
    for path, fmt in files:
        res = tracker.lookup(DEFAULT_SOURCE, path, fmt, kind)
        if res is not None:
            reused[path] = res
    loaded = {path: load_source(path, fmt) for path, fmt in files if path not in reused}
    if not program.block:
        for path, _ in files:
            run.legacy_types[path] = reused[path].types if path in reused else legacy_file_types(loaded[path], opts)
        fields = infer_legacy_schema([run.legacy_types[path] for path, _ in files])
        for path, fmt in files:
            if path in reused and reused[path].schema != fields:
                del reused[path]  # typed with a different schema: read it again
                loaded[path] = load_source(path, fmt)
        required = set(REQUIRED_COLUMNS)
        plan = compile_plan(program, fields, ctx)
    run.plan = plan
    try:
        rows = process_input_files(plan, files, loaded, reused, fields, required, opts, run, kind)
    finally:
        write_bad_records(args.bad_records_out, run.bad)
    return execute(plan, rows)


def write_result(args, result):
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
