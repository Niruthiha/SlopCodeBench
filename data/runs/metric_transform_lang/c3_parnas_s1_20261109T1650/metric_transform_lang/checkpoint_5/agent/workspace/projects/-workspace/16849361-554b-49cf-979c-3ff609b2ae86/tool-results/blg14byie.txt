"""MTL parser.

Secret: the concrete syntax of the DSL -- tokens, comments, how statements
are delimited (including multi-line continuation and `{ }` blocks), operator
precedence, the shapes of statements and declarations, and the structural
rules (exactly one aggregate, at most one group_by/window, unique aliases,
exactly one pipeline block when blocks are used).
"""

import re

from . import program as P
from .errors import DslError, TypeCheckError

_TRANSFORM_ARITY = {
    "len": (1, 1), "day": (1, 1), "month": (1, 1), "year": (1, 1), "round": (1, 2),
    "coalesce": (2, None), "lag": (1, 2), "lead": (1, 2),
    "starts_with": (2, 2), "ends_with": (2, 2), "contains": (2, 2),
}
_STRING_OPS = ("starts_with", "ends_with", "contains")
TYPE_NAMES = ("string", "int", "float", "bool", "timestamp")
AGGREGATE_FUNCTIONS = ("average", "median", "sum", "count", "std", "var", "min", "max")
_RESERVED_OUTPUT = ("window_start", "window_end")
_STAGES = (P.STAGE_PRE, P.STAGE_POST)
JOIN_TYPES = ("inner", "left", "right", "full")
_JOIN_CLAUSES = ("on", "within", "type", "project")
_DURATION_UNITS = ("s", "m", "h", "d")
WORKING_RELATION = "_"

_TOKEN_RE = re.compile(r"""
    (?P<ws>\s+)
  | (?P<float>(\d+\.\d*|\.\d+)([eE][+-]?\d+)?|\d+[eE][+-]?\d+)
  | (?P<int>\d+)
  | (?P<string>'[^'\n]*'|"[^"\n]*")
  | (?P<ident>[A-Za-z_][A-Za-z0-9_]*)
  | (?P<op><=|>=|==|!=|[<>!&|()\[\],*+\-/%=:@.])
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
    Outside brackets, '{' and '}' end the current statement and are yielded
    as statements of their own.  Yields (line_number, statement_text).
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
        if ch in "'\"":
            end = text.find(ch, i + 1)
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
        if ch in "{}" and depth <= 0:
            flush()
            statements.append((line, ch))
            start_line = None
            depth = 0
            i += 1
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

    def is_word(self, text):
        tok = self.peek()
        return tok.kind == "ident" and tok.text == text

    def expect_op(self, text):
        if not self.is_op(text):
            self.fail("expected %r" % text)
        return self.advance()

    def expect_word(self, text):
        if not self.is_word(text):
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

    def type_name(self):
        tok = self.peek()
        name = self.expect_ident("a type name")
        if name not in TYPE_NAMES:
            self.fail("unknown type %r" % name, tok)
        return name

    # -- block headers and declarations --------------------------------
    def schema_header(self):
        self.expect_word("schema")
        name = self.expect_ident("a schema name")
        base = None
        if self.is_word("extends"):
            self.advance()
            base = self.expect_ident("a base schema name")
            if self.is_op(","):
                self.fail("multiple inheritance is not allowed")
        self.expect_end()
        return name, base

    def pipeline_header(self):
        self.expect_word("pipeline")
        name = self.expect_ident("a pipeline name")
        schema = None
        if not self.is_op("{") and self.peek().kind != "eof":
            self.expect_word("using")
            schema = self.expect_ident("a schema name")
        self.expect_end()
        return name, schema

    # -- multi-source constructs ---------------------------------------
    def source_bindings(self):
        """name [as alias] {, name [as alias]}  (a trailing comma is allowed)"""
        bindings = []
        while self.peek().kind != "eof":
            name = self.expect_ident("a source name")
            alias = name
            if self.is_word("as"):
                self.advance()
                alias = self.expect_ident("a source alias")
            if alias == WORKING_RELATION:
                self.fail("%r is reserved for the working relation" % WORKING_RELATION)
            bindings.append(P.SourceBinding(name, alias))
            if not self.is_op(","):
                break
            self.advance()
        self.expect_end()
        return bindings

    def with_header(self):
        self.expect_word("with")
        alias = self.expect_ident("a source alias")
        self.expect_end()
        return alias

    def join_header(self):
        """join <left> with <right> on (<expr>) [within <duration>] [type <kind>] project"""
        self.expect_word("join")
        left = self.join_operand()
        self.expect_word("with")
        right = self.join_operand()
        on = within = kind = None
        while not self.is_word("project"):
            tok = self.peek()
            if tok.kind == "eof":
                raise DslError("line %d: join requires a project { ... } clause" % self.line)
            if self.is_word("on") and on is None:
                self.advance()
                on = self.expression()
            elif self.is_word("within") and within is None:
                self.advance()
                within = self.duration()
            elif self.is_word("type") and kind is None:
                self.advance()
                tok = self.peek()
                kind = self.expect_ident("a join type")
                if kind not in JOIN_TYPES:
                    self.fail("unknown join type %r (expected inner, left, right or full)"
                              % kind, tok)
            else:
                self.fail("expected on, within, type or project in join")
        self.advance()
        self.expect_end()
        if on is None:
            raise DslError("line %d: join requires an on (...) predicate" % self.line)
        return left, right, on, within, kind or "inner"

    def join_operand(self):
        return self.expect_ident("a source alias, join alias or _")

    def duration(self):
        if self.is_word("param") and self.peek(1).kind == "op" and self.peek(1).text == "(":
            self.advance()
            return P.Duration(None, None, self.param_ref().name)
        tok = self.peek()
        if tok.kind != "int":
            self.fail("expected a duration such as 10m")
        self.advance()
        amount = int(tok.text)
        unit_tok = self.peek()
        unit = self.expect_ident("a duration unit (s, m, h or d)")
        if unit not in _DURATION_UNITS:
            self.fail("unknown duration unit %r" % unit, unit_tok)
        if unit_tok.pos != tok.pos + len(tok.text):
            self.fail("expected a duration such as 10m", unit_tok)
        return P.Duration(amount, unit, None)

    def project_items(self):
        """<expr> [as <name>] {, ...}; a bare column reference keeps its column name."""
        items = []
        while self.peek().kind != "eof":
            start = self.peek()
            expr = self.expression()
            if self.is_word("as"):
                self.advance()
                tok = self.peek()
                if tok.kind == "string" and len(tok.text) > 2:
                    name = self.advance().text[1:-1]
                else:
                    name = self.expect_ident("a projected column name")
            elif isinstance(expr, P.ColumnRef):
                name = expr.name.rsplit(".", 1)[-1]
            else:
                self.fail("project entries need 'as <name>'", start)
            items.append(P.ProjectItem(expr, name))
            if not self.is_op(","):
                break
            self.advance()
        self.expect_end()
        return items

    def join_alias(self):
        self.expect_word("as")
        alias = self.expect_ident("a join alias")
        self.expect_end()
        return alias

    def field_list(self):
        """name: type [= expr] {, name: type [= expr]}"""
        fields = [self.field()]
        while self.is_op(","):
            self.advance()
            fields.append(self.field())
        self.expect_end()
        return fields

    def field(self):
        name = self.expect_ident("a field name")
        self.expect_op(":")
        value_type = self.type_name()
        expr = None
        if self.is_op("="):
            self.advance()
            expr = self.expression()
        return P.FieldDef(name, value_type, expr)

    def param_list(self):
        """name [: type] [= literal] {, ...}"""
        params = [self.param_decl()]
        while self.is_op(","):
            self.advance()
            params.append(self.param_decl())
        self.expect_end()
        return params

    def param_decl(self):
        name = self.expect_ident("a parameter name")
        value_type = default = None
        if self.is_op(":"):
            self.advance()
            value_type = self.type_name()
        if self.is_op("="):
            self.advance()
            default = self.literal()
        return P.ParamDef(name, value_type, default)

    def literal(self):
        sign = None
        if self.peek().kind == "op" and self.peek().text in ("-", "+"):
            sign = self.advance().text
        tok = self.peek()
        if tok.kind in ("int", "float"):
            self.advance()
            value = int(tok.text) if tok.kind == "int" else float(tok.text)
            return P.Literal(tok.kind, -value if sign == "-" else value)
        if sign is None:
            if tok.kind == "string":
                self.advance()
                return P.Literal("string", tok.text[1:-1])
            if tok.kind == "ident" and tok.text in ("true", "false"):
                self.advance()
                return P.Literal("bool", tok.text == "true")
        self.fail("expected a literal value")

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
        if name == "calc":
            return self.calc_statement()
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
        columns = [self.group_column()]
        while self.is_op(","):
            self.advance()
            columns.append(self.group_column())
        if bracketed:
            self.expect_op("]")
        self.expect_op(")")
        self.expect_end()
        if len(set(columns)) != len(columns):
            raise DslError("line %d: duplicate column in group_by" % self.line)
        return P.GroupBy(tuple(columns))

    def group_column(self):
        tok = self.peek()
        if tok.kind == "string" and len(tok.text) > 2:
            return self.advance().text[1:-1]
        return self.expect_ident("a column name")

    def window_statement(self):
        m = re.match(r"^window\s*\(\s*(\d+)([mhd])\s*\)$", self.stmt)
        if m:
            amount = int(m.group(1))
            if amount <= 0:
                raise DslError("line %d: window duration must be positive" % self.line)
            return P.Window(amount, m.group(2))
        self.advance()
        self.expect_op("(")
        if self.is_word("param") and self.peek(1).kind == "op" and self.peek(1).text == "(":
            self.advance()
            ref = self.param_ref()
            self.expect_op(")")
            self.expect_end()
            return P.Window(None, None, ref.name)
        raise DslError("line %d: invalid window statement, expected window(<n><m|h|d>)"
                       % self.line)

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
        self.expect_word("as")
        alias = self.expect_ident("an alias")
        return P.AggregateItem(fn, column, alias)

    def calc_statement(self):
        """calc name = expr : type [@stage(pre|post_agg)]  (or calc name: type = expr ...)"""
        self.advance()
        name = self.expect_ident("a calculated field name")
        if self.is_op(":"):
            self.advance()
            value_type = self.type_name()
            self.expect_op("=")
            expr = self.expression()
        else:
            self.expect_op("=")
            expr = self.expression()
            self.expect_op(":")
            value_type = self.type_name()
        stage = P.STAGE_PRE
        if self.is_op("@"):
            self.advance()
            self.expect_word("stage")
            self.expect_op("(")
            tok = self.peek()
            stage = self.expect_ident("a stage name")
            if stage not in _STAGES:
                self.fail("unknown stage %r (expected pre or post_agg)" % stage, tok)
            self.expect_op(")")
        self.expect_end()
        return P.Calc(name, expr, value_type, stage)

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
        if tok.kind == "ident" and tok.text in _STRING_OPS:
            op = self.advance().text
            right = self.additive()
            self.reject_chain()
            return P.Call(op, (left, right))
        return left

    def reject_chain(self):
        tok = self.peek()
        if (tok.kind == "op" and tok.text in ("<", "<=", ">", ">=", "==", "!=")) or \
                (tok.kind == "ident" and tok.text in ("in",) + _STRING_OPS):
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
            if self.is_op(".") and self.peek(1).kind == "ident":
                self.advance()
                return P.ColumnRef("%s.%s" % (tok.text, self.advance().text))
            if self.is_op("("):
                if tok.text == "param":
                    return self.param_ref()
                if tok.text == "cast":
                    return self.cast()
                return self.call(tok)
            return P.ColumnRef(tok.text)
        if self.is_op("("):
            self.advance()
            inner = self.expression()
            self.expect_op(")")
            return inner
        self.fail("expected an expression")

    def param_ref(self):
        self.expect_op("(")
        tok = self.peek()
        if tok.kind != "string" or len(tok.text) <= 2:
            self.fail("param() expects a quoted parameter name")
        self.advance()
        self.expect_op(")")
        return P.Param(tok.text[1:-1])

    def cast(self):
        self.expect_op("(")
        inner = self.expression()
        self.expect_word("as")
        value_type = self.type_name()
        self.expect_op(")")
        return P.Cast(inner, value_type)

    def call(self, tok):
        self.expect_op("(")
        args = []
        if not self.is_op(")"):
            args.append(self.expression())
            while self.is_op(","):
                self.advance()
                args.append(self.expression())
        self.expect_op(")")
        if tok.text not in _TRANSFORM_ARITY:
            self.fail("unknown function %r" % tok.text, tok)
        low, high = _TRANSFORM_ARITY[tok.text]
        if len(args) < low or (high is not None and len(args) > high):
            self.fail("wrong number of arguments to %s()" % tok.text, tok)
        return P.Call(tok.text, tuple(args))


def _first_word(stmt):
    m = re.match(r"[A-Za-z_][A-Za-z0-9_]*", stmt)
    return m.group() if m else None


def parse_program(text):
    """Parse DSL source into a program.Program; raises DslError."""
    statements = _logical_lines(text)
    if any(stmt in ("{", "}") or _first_word(stmt) in ("schema", "pipeline")
           for _, stmt in statements):
        return _parse_blocks(statements)
    return _build_program(statements)


def _build_program(statements, **extra):
    steps = []
    calcs = []
    group_by = window = aggregate = None
    for line, stmt in statements:
        node = _StatementParser(stmt, line).statement()
        if isinstance(node, (P.Filter, P.Apply)):
            steps.append(node)
        elif isinstance(node, P.Calc):
            calcs.append(node)
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
    _check_calc_names(calcs)
    _check_output_names(group_by, window, aggregate, calcs)
    return P.Program(steps, group_by, window, aggregate, calcs=calcs, **extra)


class _Cursor:
    def __init__(self, statements):
        self.statements = statements
        self.i = 0

    def done(self):
        return self.i >= len(self.statements)

    def next(self, what):
        if self.done():
            raise DslError("unexpected end of DSL: expected %s" % what)
        item = self.statements[self.i]
        self.i += 1
        return item

    def expect_open(self, what):
        line, stmt = self.next("'{' after %s header" % what)
        if stmt != "{":
            raise DslError("line %d: expected '{' after %s header" % (line, what))

    def block(self, what):
        """Yield (line, stmt) up to the closing brace of the current block."""
        while True:
            line, stmt = self.next("'}' closing %s block" % what)
            if stmt == "}":
                return
            if stmt == "{":
                raise DslError("line %d: unexpected '{' in %s block" % (line, what))
            yield line, stmt


def _parse_blocks(statements):
    cursor = _Cursor(statements)
    schemas = {}
    pipeline = None
    while not cursor.done():
        line, stmt = cursor.next("a block")
        word = _first_word(stmt)
        if word == "schema":
            name, base = _StatementParser(stmt, line).schema_header()
            if name in schemas:
                raise DslError("line %d: schema %r is defined more than once" % (line, name))
            cursor.expect_open("schema")
            fields = []
            seen = set()
            for fline, fstmt in cursor.block("schema"):
                for field in _StatementParser(fstmt, fline).field_list():
                    if field.name in seen:
                        raise DslError("line %d: field %r declared twice in schema %r"
                                       % (fline, field.name, name))
                    seen.add(field.name)
                    fields.append(field)
            schemas[name] = P.SchemaDef(name, base, tuple(fields))
        elif word == "pipeline":
            if pipeline is not None:
                raise DslError("line %d: only one pipeline block is allowed" % line)
            pipeline = (line,) + _StatementParser(stmt, line).pipeline_header()
            cursor.expect_open("pipeline")
            pipeline += _pipeline_body(cursor)
        else:
            raise DslError("line %d: expected a schema or pipeline block" % line)
    if pipeline is None:
        raise DslError("DSL has no pipeline block")
    line, name, schema_name, body, params, sources, scoped, joins = pipeline
    if schema_name is None:
        if sources is None:
            raise DslError("line %d: pipeline requires 'using <schema>'" % line)
    elif schema_name not in schemas:
        raise DslError("line %d: pipeline uses unknown schema %r" % (line, schema_name))
    _check_sources(sources, scoped, joins)
    return _build_program(body, params=params, schemas=schemas,
                          schema_name=schema_name, name=name, sources=sources,
                          scoped=scoped, joins=joins)


def _pipeline_body(cursor):
    body = []
    params = None
    sources = None
    scoped = []
    joins = []
    started = False
    while True:
        line, stmt = cursor.next("'}' closing pipeline block")
        if stmt == "}":
            break
        if stmt == "{":
            raise DslError("line %d: unexpected '{' in pipeline block" % line)
        word = _first_word(stmt)
        if word == "sources" and stmt.strip() == "sources":
            if sources is not None:
                raise DslError("line %d: sources block may appear at most once" % line)
            if started:
                raise DslError("line %d: sources block must precede all other statements"
                               % line)
            cursor.expect_open("sources")
            sources = []
            for bline, bstmt in cursor.block("sources"):
                sources.extend(_StatementParser(bstmt, bline).source_bindings())
            if not sources:
                raise DslError("line %d: sources block binds no source" % line)
            started = True
            continue
        if word == "with":
            scoped.append(_scoped_block(cursor, line, stmt))
            started = True
            continue
        if word == "join":
            joins.append(_join(cursor, line, stmt))
            started = True
            continue
        if word == "params" and stmt.strip() == "params":
            if params is not None:
                raise DslError("line %d: params block may appear at most once" % line)
            cursor.expect_open("params")
            params = []
            seen = set()
            for pline, pstmt in cursor.block("params"):
                for decl in _StatementParser(pstmt, pline).param_list():
                    if decl.name in seen:
                        raise DslError("line %d: parameter %r declared twice"
                                       % (pline, decl.name))
                    seen.add(decl.name)
                    params.append(decl)
        else:
            body.append((line, stmt))
            started = True
    return body, tuple(params or ()), sources, scoped, joins


def _scoped_block(cursor, line, stmt):
    alias = _StatementParser(stmt, line).with_header()
    cursor.expect_open("with")
    steps = []
    for sline, sstmt in cursor.block("with"):
        node = _StatementParser(sstmt, sline).statement()
        if isinstance(node, (P.GroupBy, P.Window, P.Aggregate)):
            raise DslError("line %d: with %s { } accepts only pre-stage calcs and filters"
                           % (sline, alias))
        if isinstance(node, P.Calc) and node.stage != P.STAGE_PRE:
            raise TypeCheckError("line %d: calc %r: @stage(%s) is not allowed inside with %s { }"
                                 % (sline, node.name, node.stage, alias))
        steps.append(node)
    return P.ScopedBlock(alias, tuple(steps), line)


def _join(cursor, line, stmt):
    parts = [stmt]
    while not re.search(r"\bproject\s*$", parts[-1]) and not cursor.done():
        nstmt = cursor.statements[cursor.i][1]
        if _first_word(nstmt) not in _JOIN_CLAUSES:
            break
        cursor.i += 1
        parts.append(nstmt)
    header = " ".join(parts)
    left, right, on, within, kind = _StatementParser(header, line).join_header()
    if cursor.done() or cursor.statements[cursor.i][1] != "{":
        raise DslError("line %d: expected '{' after project" % line)
    cursor.i += 1
    items = []
    for pline, pstmt in cursor.block("project"):
        items.extend(_StatementParser(pstmt, pline).project_items())
    if not items:
        raise DslError("line %d: project { } must define at least one column" % line)
    names = [item.name for item in items]
    for name in names:
        if names.count(name) > 1:
            raise DslError("line %d: column %r appears more than once in project; "
                           "disambiguate it with 'as'" % (line, name))
    alias = None
    if not cursor.done() and _first_word(cursor.statements[cursor.i][1]) == "as":
        aline, astmt = cursor.next("a join alias")
        alias = _StatementParser(astmt, aline).join_alias()
    return P.Join(left, right, on, within, kind, tuple(items), alias, line)


def _check_sources(sources, scoped, joins):
    if sources is None:
        if joins:
            raise DslError("line %d: join requires a sources { } block" % joins[0].line)
        if scoped:
            raise DslError("line %d: with blocks require a sources { } block" % scoped[0].line)
        return
    aliases = set()
    for binding in sources:
        if binding.alias in aliases:
            raise DslError("source alias %r is bound more than once" % binding.alias)
        aliases.add(binding.alias)
    if not joins:
        raise DslError("pipeline declares sources but no join combines them")
    for block in scoped:
        if block.alias not in aliases:
            raise DslError("line %d: with refers to unknown source alias %r"
                           % (block.line, block.alias))
    known = set(aliases)
    for index, join in enumerate(joins):
        for operand in (join.left, join.right):
            if operand == WORKING_RELATION:
                if index == 0:
                    raise DslError("line %d: '_' refers to the previous join, but this is the "
                                   "first join" % join.line)
            elif operand not in known:
                raise DslError("line %d: join refers to unknown alias %r" % (join.line, operand))
        if join.left == join.right:
            raise DslError("line %d: cannot join %r with itself; bind the source twice under "
                           "different aliases" % (join.line, join.left))
        if join.alias is not None:
            if join.alias in known or join.alias == WORKING_RELATION:
                raise DslError("line %d: join alias %r is already in use"
                               % (join.line, join.alias))
            known.add(join.alias)


def _check_calc_names(calcs):
    seen = set()
    for calc in calcs:
        if calc.name in seen:
            raise DslError("calculated field %r is declared more than once" % calc.name)
        seen.add(calc.name)


def _check_output_names(group_by, window, aggregate, calcs):
    taken = set(group_by.columns) if group_by else set()
    if window:
        clash = taken.intersection(_RESERVED_OUTPUT)
        if clash:
            raise DslError("group_by column %r collides with a window field" % sorted(clash)[0])
        taken.update(_RESERVED_OUTPUT)
    for item in aggregate.items:
        if item.alias in taken:
            raise DslError("aggregate alias %r collides with another output field" % item.alias)
        taken.add(item.alias)
    for calc in calcs:
        if calc.stage == P.STAGE_POST and calc.name in taken:
            raise DslError("calculated field %r collides with another output field" % calc.name)
