#!/usr/bin/env python3
"""mtl.py - run a small pipeline DSL (MTL) over sales events read from CSV, TSV
(optionally gzipped) and Parquet files and emit deterministic JSON.  Missing
values are nulls with three-valued logic; rows that cannot be read or
evaluated are rejected as bad records (skipped, logged, or fatal with --strict).
With --ingest-config (YAML or JSON) inputs come from named sources, each with its
own file patterns, schema and mapping; a pipeline binds them with sources { },
filters them per alias with with <alias> { } and combines them with join."""
import sys

EXIT_CODES = {'bad_dsl': 1, 'type_error': 2, 'bad_io': 3, 'runtime_error': 4, 'config_error': 5}


class MTLError(Exception):
    def __init__(self, kind, msg):
        Exception.__init__(self, msg)
        self.kind = kind
        self.msg = msg


def fail(kind, msg):
    raise MTLError(kind, msg)


# --------------------------------------------------------------------------
# Tokenizer
# --------------------------------------------------------------------------
from math import fsum, isqrt
from _json import encode_basestring as json_str
import _csv

_DIGITS = frozenset('0123456789')
_OPS1 = frozenset('<>()[],*+-/&|!{}:=@.\u22c8')    # '.' qualifies columns, '\u22c8' is the join symbol
_OPS2 = frozenset(('<=', '>=', '==', '!='))


def tokenize(src):
    toks = []
    append = toks.append
    digits = _DIGITS
    i = 0
    n = len(src)
    line = 1
    depth = 0
    while i < n:
        ch = src[i]
        if ch == '\n':
            if depth == 0 and toks and toks[-1][0] != 'nl':
                append(('nl', '\n', line))
            line += 1
            i += 1
        elif ch in ' \t\r\f\v':
            i += 1
        elif ch == '#':
            j = src.find('\n', i)
            i = n if j < 0 else j
        elif ch in digits or (ch == '.' and i + 1 < n and src[i + 1] in digits):
            j = i
            while j < n and src[j] in digits:
                j += 1
            if (j > i and j < n and src[j] in 'mhd'
                    and not (j + 1 < n and (src[j + 1].isalnum() or src[j + 1] in '_.'))):
                append(('dur', src[i:j + 1], line))
                i = j + 1
                continue
            if j < n and src[j] == '.':
                j += 1
                while j < n and src[j] in digits:
                    j += 1
            if j < n and src[j] in 'eE':
                k = j + 1
                if k < n and src[k] in '+-':
                    k += 1
                if k < n and src[k] in digits:
                    while k < n and src[k] in digits:
                        k += 1
                    j = k
            append(('num', src[i:j], line))
            i = j
        elif ch == "'":
            j = src.find("'", i + 1)
            nl = src.find('\n', i + 1)
            if j < 0 or 0 <= nl < j:
                fail('bad_dsl', f"line {line}: unterminated string literal")
            text = src[i + 1:j]
            if '\\' in text:
                fail('bad_dsl', f"line {line}: escape sequences are not allowed in string literals")
            append(('str', text, line))
            i = j + 1
        elif ch.isalpha() or ch == '_':
            j = i + 1
            while j < n and (src[j].isalnum() or src[j] == '_'):
                j += 1
            append(('id', src[i:j], line))
            i = j
        elif src[i:i + 2] in _OPS2:
            append(('op', src[i:i + 2], line))
            i += 2
        elif ch in _OPS1:
            if ch == '(' or ch == '[':
                depth += 1
            elif (ch == ')' or ch == ']') and depth:
                depth -= 1
            append(('op', ch, line))
            i += 1
        elif ch == '"':
            # only accepted where the grammar allows it (param("name"), group_by
            # lists, params defaults); the parser rejects it elsewhere
            j = src.find('"', i + 1)
            nl = src.find('\n', i + 1)
            if j < 0 or 0 <= nl < j:
                fail('bad_dsl', f"line {line}: unterminated string literal")
            text = src[i + 1:j]
            if '\\' in text:
                fail('bad_dsl', f"line {line}: escape sequences are not allowed in string literals")
            append(('dstr', text, line))
            i = j + 1
        else:
            fail('bad_dsl', f"line {line}: unexpected character {ch!r}")
    append(('nl', '\n', line))
    append(('eof', '', line))
    return toks


# --------------------------------------------------------------------------
# Parser
# --------------------------------------------------------------------------
AGG_FUNCS = frozenset(('average', 'median', 'sum', 'count', 'std', 'var', 'min', 'max'))
JOIN_TYPES = ('inner', 'left', 'right', 'full')
SCALAR_FUNCS = {'len': (1, 1), 'day': (1, 1), 'month': (1, 1), 'year': (1, 1), 'round': (1, 2)}
STR_OPS = frozenset(('starts_with', 'ends_with', 'contains'))
CMP_OPS = frozenset(('<', '<=', '>', '>=', '==', '!='))
DUR_UNITS = {'m': 60, 'h': 3600, 'd': 86400}
# DSL type name -> internal type tag
TYPE_KW = {'string': 'str', 'int': 'int', 'float': 'float', 'bool': 'bool', 'timestamp': 'ts'}
DSL_TYPE = {v: k for k, v in TYPE_KW.items()}
WINDOW_KEYS = ('window_start', 'window_end')


def _desc(tok):
    if tok[0] == 'eof':
        return 'end of input'
    if tok[0] == 'nl':
        return 'end of line'
    if tok[0] == 'str' or tok[0] == 'dstr':
        return repr(tok[1])
    return f"'{tok[1]}'"


class Parser:
    def __init__(self, toks):
        self.toks = toks
        self.i = 0

    def peek(self):
        return self.toks[self.i]

    def err(self, msg, tok=None):
        tok = tok or self.toks[self.i]
        fail('bad_dsl', f"line {tok[2]}: {msg} near {_desc(tok)}")

    def is_op(self, op):
        t = self.toks[self.i]
        return t[0] == 'op' and t[1] == op

    def is_kw(self, kw):
        t = self.toks[self.i]
        return t[0] == 'id' and t[1] == kw

    def expect_op(self, op):
        t = self.toks[self.i]
        if t[0] != 'op' or t[1] != op:
            self.err(f"expected '{op}'")
        self.i += 1

    def expect_id(self, what):
        t = self.toks[self.i]
        if t[0] != 'id':
            self.err(f"expected {what}")
        self.i += 1
        return t[1]

    def skip_nl(self):
        while self.toks[self.i][0] == 'nl':
            self.i += 1

    def type_name(self):
        t = self.peek()
        name = self.expect_id('a type')
        typ = TYPE_KW.get(name)
        if typ is None:
            self.err(f"unknown type '{name}' (expected string, int, float, bool or timestamp)", t)
        return typ

    def end_line(self, block):
        t = self.peek()
        if t[0] in ('nl', 'eof') or (block and t[0] == 'op' and t[1] == '}'):
            return
        self.err('expected end of statement')

    # -- top level ---------------------------------------------------------
    def document(self):
        """schema/pipeline blocks -> (schemas, pipeline)."""
        schemas = {}
        pipeline = None
        while True:
            self.skip_nl()
            t = self.peek()
            if t[0] == 'eof':
                break
            kw = self.expect_id("'schema' or 'pipeline'")
            if kw == 'schema':
                name = self.expect_id('a schema name')
                if name in schemas:
                    self.err(f"duplicate schema '{name}'", t)
                base = None
                if self.is_kw('extends'):
                    self.i += 1
                    base = self.expect_id('a base schema name')
                    if self.is_op(','):
                        self.err('multiple inheritance is not allowed')
                self.skip_nl()
                self.expect_op('{')
                schemas[name] = (base, self.schema_fields(), t)
            elif kw == 'pipeline':
                if pipeline is not None:
                    self.err('only one pipeline block is allowed', t)
                name = self.expect_id('a pipeline name')
                using = None
                if self.is_kw('using'):
                    self.i += 1
                    using = self.expect_id('a schema name')
                self.skip_nl()
                self.expect_op('{')
                stmts = self.statements(True)
                self.expect_op('}')
                pipeline = (name, using, stmts, t)
            else:
                self.err("expected 'schema' or 'pipeline'", t)
            self.end_line(False)
        if pipeline is None:
            fail('bad_dsl', 'exactly one pipeline block is required')
        return schemas, pipeline

    def schema_fields(self):
        fields = []
        seen = set()
        while True:
            self.skip_nl()
            if self.is_op('}'):
                self.i += 1
                return fields
            t = self.peek()
            if t[0] == 'eof':
                self.err("expected '}'")
            name = self.expect_id('a field name')
            if name in seen:
                self.err(f"duplicate field '{name}' in schema", t)
            seen.add(name)
            self.expect_op(':')
            typ = self.type_name()
            e = None
            if self.is_op('='):
                self.i += 1
                e = self.expr()
            fields.append((name, typ, e, t))
            self.end_line(True)

    def params_block(self):
        self.skip_nl()
        self.expect_op('{')
        decls = []
        while True:
            self.skip_nl()
            if self.is_op('}'):
                self.i += 1
                return decls
            t = self.peek()
            if t[0] == 'eof':
                self.err("expected '}'")
            name = self.expect_id('a parameter name')
            typ = dflt = None
            if self.is_op(':'):
                self.i += 1
                typ = self.type_name()
            if self.is_op('='):
                self.i += 1
                dflt = self.literal()
            decls.append((name, typ, dflt, t))
            self.end_line(True)

    def literal(self):
        t = self.peek()
        sign = 1
        if t[0] == 'op' and t[1] in ('-', '+'):
            sign = -1 if t[1] == '-' else 1
            self.i += 1
            t = self.peek()
            if t[0] != 'num':
                self.err('expected a number')
        self.i += 1
        if t[0] == 'num':
            if t[1].isdigit():
                return ('lit', 'int', sign * int(t[1]))
            return ('lit', 'float', sign * float(t[1]))
        if t[0] == 'str' or t[0] == 'dstr':
            return ('lit', 'str', t[1])
        if t[0] == 'id' and t[1] in ('true', 'false'):
            return ('lit', 'bool', t[1] == 'true')
        self.i -= 1
        self.err('expected a literal value')

    # -- statements --------------------------------------------------------
    def program(self):
        return self.statements(False)

    def statements(self, block):
        stmts = []
        while True:
            self.skip_nl()
            t = self.peek()
            if t[0] == 'eof':
                if block:
                    self.err("expected '}'")
                break
            if block and t[0] == 'op' and t[1] == '}':
                break
            if t[0] != 'id':
                self.err('expected a statement')
            kw = t[1]
            self.i += 1
            if kw == 'filter':
                self.expect_op('(')
                e = self.expr()
                self.expect_op(')')
                stmts.append(('filter', e))
            elif kw == 'apply':
                self.expect_op('(')
                e = self.expr()
                self.expect_op(',')
                name = self.expect_id('a new column name')
                self.expect_op(')')
                stmts.append(('apply', e, name))
            elif kw == 'group_by':
                self.expect_op('(')
                if self.is_op('['):
                    self.i += 1
                    cols = self.id_list()
                    self.expect_op(']')
                else:
                    cols = self.id_list()
                self.expect_op(')')
                stmts.append(('group_by', cols, t))
            elif kw == 'window':
                self.expect_op('(')
                d = self.peek()
                if d[0] == 'id' and d[1] == 'param':
                    w = self.primary()
                else:
                    if d[0] != 'dur':
                        self.err('expected a duration literal such as 10m, 1h or 7d')
                    self.i += 1
                    w = int(d[1][:-1]) * DUR_UNITS[d[1][-1]]
                    if w <= 0:
                        self.err('window duration must be positive', d)
                self.expect_op(')')
                stmts.append(('window', w, t))
            elif kw == 'aggregate':
                self.skip_nl()
                items = [self.agg_item()]
                toks = self.toks
                while True:
                    j = self.i
                    while toks[j][0] == 'nl':
                        j += 1
                    if toks[j][0] == 'op' and toks[j][1] == ',':
                        self.i = j + 1
                        self.skip_nl()
                        items.append(self.agg_item())
                    else:
                        break
                stmts.append(('aggregate', items, t))
            elif kw == 'calc':
                name = self.expect_id('a calc name')
                self.expect_op('=')
                e = self.expr()
                self.expect_op(':')
                typ = self.type_name()
                stage = 'pre'
                if self.is_op('@'):
                    self.i += 1
                    if self.expect_id("'stage'") != 'stage':
                        self.err("expected '@stage(pre|post_agg)'", self.toks[self.i - 1])
                    self.expect_op('(')
                    st = self.peek()
                    stage = self.expect_id("'pre' or 'post_agg'")
                    if stage not in ('pre', 'post_agg'):
                        self.err("stage must be 'pre' or 'post_agg'", st)
                    self.expect_op(')')
                stmts.append(('calc', name, e, typ, stage, t))
            elif kw == 'params' and block and self.is_op('{'):
                stmts.append(('params', self.params_block(), t))
            elif kw == 'sources' and block:
                stmts.append(('sources', self.sources_block(), t))
            elif kw == 'with' and block:
                alias = self.expect_id('a source alias')
                self.skip_nl()
                self.expect_op('{')
                body = self.statements(True)
                self.expect_op('}')
                stmts.append(('with', alias, body, t))
            elif kw == 'join' and block:
                stmts.append(self.join_stmt(t))
            else:
                self.err(f"unknown statement '{kw}'", t)
            self.end_line(block)
        return stmts

    def list_sep(self):
        """Entries of sources {} / project {} are separated by ',' or newlines."""
        j = self.i
        self.skip_nl()
        if self.is_op(','):
            self.i += 1
        elif not (self.is_op('}') or self.i > j):
            self.err("expected ',' or '}'")

    def sources_block(self):
        self.skip_nl()
        self.expect_op('{')
        binds = []
        while True:
            self.skip_nl()
            if self.is_op('}'):
                self.i += 1
                return binds
            t = self.peek()
            if t[0] == 'eof':
                self.err("expected '}'")
            name = self.expect_id('a source name')
            alias = name
            if self.is_kw('as'):
                self.i += 1
                alias = self.expect_id('an alias')
            binds.append((name, alias, t))
            self.list_sep()

    def rel_ref(self):
        """Join operand: an alias, '_' (the previous join) or '(A ⋈ B)'."""
        t = self.peek()
        if self.is_op('('):
            self.i += 1
            a = self.expect_id('a source or join alias')
            if not (self.is_op('⋈') or self.is_kw('join')):
                self.err("expected '⋈'")
            self.i += 1
            b = self.expect_id('a source or join alias')
            self.expect_op(')')
            return ('pair', a, b, t)
        return ('ref', self.expect_id('a source or join alias'), t)

    def join_stmt(self, t):
        left = self.rel_ref()
        self.skip_nl()
        if not self.is_kw('with'):
            self.err("expected 'with' in join")
        self.i += 1
        right = self.rel_ref()
        on = within = jtype = proj = alias = None
        while True:
            j = self.i
            self.skip_nl()
            c = self.peek()
            kw = c[1] if c[0] == 'id' else None
            if kw == 'on' and on is None:
                self.i += 1
                on = self.expr()
            elif kw == 'within' and within is None:
                self.i += 1
                d = self.peek()
                if d[0] != 'dur':
                    self.err('expected a duration literal such as 10m, 1h or 7d after within')
                self.i += 1
                within = int(d[1][:-1]) * DUR_UNITS[d[1][-1]]
            elif kw == 'type' and jtype is None:
                self.i += 1
                tt = self.peek()
                jtype = self.expect_id('a join type')
                if jtype not in JOIN_TYPES:
                    self.err('join type must be inner, left, right or full', tt)
                if jtype != 'inner' and self.is_kw('outer'):
                    self.i += 1
            elif kw == 'project' and proj is None:
                self.i += 1
                proj = self.project_block()
                k = self.i
                self.skip_nl()
                if self.is_kw('as'):
                    self.i += 1
                    alias = self.expect_id('a join alias')
                else:
                    self.i = k
                break
            else:
                self.i = j
                break
        if on is None:
            self.err("join requires 'on (<condition>)'", t)
        if proj is None:
            self.err("join requires a 'project { ... }' clause")
        return ('join', left, right, on, within, jtype or 'inner', proj, alias, t)

    def project_block(self):
        self.skip_nl()
        self.expect_op('{')
        items = []
        while True:
            self.skip_nl()
            if self.is_op('}'):
                self.i += 1
                break
            t = self.peek()
            if t[0] == 'eof':
                self.err("expected '}'")
            e = self.expr()
            if self.is_kw('as'):
                self.i += 1
                name = self.expect_id('a column name')
            elif e[0] == 'col':
                name = e[1].rsplit('.', 1)[-1]
            else:
                self.err("expected 'as <name>' in project")
            items.append((e, name, t))
            self.list_sep()
        if not items:
            self.err('project { } must define at least one column', self.toks[self.i - 1])
        return items

    def id_list(self):
        cols = [self.col_name()]
        while self.is_op(','):
            self.i += 1
            cols.append(self.col_name())
        return cols

    def col_name(self):
        t = self.peek()
        if t[0] in ('id', 'str', 'dstr'):
            self.i += 1
            return t[1]
        self.err('expected a column name')

    def agg_item(self):
        t = self.peek()
        fn = self.expect_id('an aggregate function')
        if fn not in AGG_FUNCS:
            self.err(f"unknown aggregate function '{fn}'", t)
        self.expect_op('(')
        if self.is_op('*'):
            self.i += 1
            col = '*'
        else:
            col = self.expect_id("a column name or '*'")
        self.expect_op(')')
        a = self.peek()
        if a[0] != 'id' or a[1] != 'as':
            self.err("expected 'as <alias>'")
        self.i += 1
        alias = self.expect_id('an alias')
        return (fn, col, alias)

    # -- expressions -------------------------------------------------------
    def expr(self):
        left = self.and_expr()
        while self.is_op('|'):
            self.i += 1
            left = ('or', left, self.and_expr())
        return left

    def and_expr(self):
        left = self.not_expr()
        while self.is_op('&'):
            self.i += 1
            left = ('and', left, self.not_expr())
        return left

    def not_expr(self):
        if self.is_op('!'):
            self.i += 1
            return ('not', self.not_expr())
        return self.cmp_expr()

    def _at_cmp(self):
        t = self.peek()
        return (t[0] == 'op' and t[1] in CMP_OPS) or (t[0] == 'id' and (t[1] == 'in' or t[1] in STR_OPS))

    def cmp_expr(self):
        left = self.add_expr()
        t = self.peek()
        if t[0] == 'op' and t[1] in CMP_OPS:
            self.i += 1
            node = ('cmp', t[1], left, self.add_expr())
        elif t[0] == 'id' and t[1] == 'in':
            self.i += 1
            node = ('in', left, self.add_expr())
        elif t[0] == 'id' and t[1] in STR_OPS:
            self.i += 1
            node = ('strop', t[1], left, self.add_expr())
        else:
            return left
        if self._at_cmp():
            self.err('comparisons cannot be chained; use parentheses')
        return node

    def add_expr(self):
        left = self.mul_expr()
        while True:
            t = self.peek()
            if t[0] == 'op' and (t[1] == '+' or t[1] == '-'):
                self.i += 1
                left = ('arith', t[1], left, self.mul_expr())
            else:
                return left

    def mul_expr(self):
        left = self.unary()
        while True:
            t = self.peek()
            if t[0] == 'op' and (t[1] == '*' or t[1] == '/'):
                self.i += 1
                left = ('arith', t[1], left, self.unary())
            else:
                return left

    def unary(self):
        t = self.peek()
        if t[0] == 'op':
            if t[1] == '-':
                self.i += 1
                return ('neg', self.unary())
            if t[1] == '+':
                self.i += 1
                return ('pos', self.unary())
        return self.primary()

    def call_args(self, name, t, lo, hi):
        args = []
        if not self.is_op(')'):
            args.append(self.expr())
            while self.is_op(','):
                self.i += 1
                args.append(self.expr())
        self.expect_op(')')
        if not lo <= len(args) <= hi:
            self.err(f"wrong number of arguments for '{name}'", t)
        return args

    def primary(self):
        t = self.peek()
        k = t[0]
        if k == 'num':
            self.i += 1
            txt = t[1]
            if txt.isdigit():
                return ('lit', 'int', int(txt))
            return ('lit', 'float', float(txt))
        if k == 'str':
            self.i += 1
            return ('lit', 'str', t[1])
        if k == 'dstr':
            self.err('string literals must use single quotes')
        if k == 'id':
            name = t[1]
            if name == 'true' or name == 'false':
                self.i += 1
                return ('lit', 'bool', name == 'true')
            if name == 'in' or name in STR_OPS and not self.toks[self.i + 1][1] == '(':
                self.err(f"unexpected keyword '{name}'")
            self.i += 1
            if self.is_op('.'):
                q = self.toks[self.i + 1]
                if q[0] != 'id':
                    self.i += 1
                    self.err("expected a column name after '.'")
                self.i += 2
                return ('col', name + '.' + q[1])
            if self.is_op('('):
                self.i += 1
                if name == 'param':
                    a = self.peek()
                    if a[0] not in ('str', 'dstr'):
                        self.err('param() expects a quoted parameter name')
                    self.i += 1
                    self.expect_op(')')
                    return ('param', a[1])
                if name == 'cast':
                    e = self.expr()
                    if not self.is_kw('as'):
                        self.err("expected 'as <type>' in cast()")
                    self.i += 1
                    typ = self.type_name()
                    self.expect_op(')')
                    return ('cast', e, typ)
                if name == 'lag' or name == 'lead':
                    e, kn = self.call_args(name, t, 2, 2)
                    if kn[0] == 'lit' and kn[1] == 'int':
                        if kn[2] <= 0:
                            self.err(f"{name}() offset must be a positive integer", t)
                    elif kn[0] == 'neg' and kn[1][0] == 'lit':
                        self.err(f"{name}() offset must be a positive integer", t)
                    elif kn[0] not in ('lit', 'param'):
                        self.err(f"{name}() offset must be a positive integer literal or an int param", t)
                    return (name, e, kn)
                if name == 'coalesce':
                    a, b = self.call_args(name, t, 2, 2)
                    return ('coalesce', a, b)
                if name in STR_OPS:
                    a, b = self.call_args(name, t, 2, 2)
                    return ('strop', name, a, b)
                if name not in SCALAR_FUNCS:
                    self.err(f"unknown function '{name}'", t)
                lo, hi = SCALAR_FUNCS[name]
                return ('call', name, self.call_args(name, t, lo, hi))
            return ('col', name)
        if k == 'op' and t[1] == '(':
            self.i += 1
            e = self.expr()
            self.expect_op(')')
            return e
        if k == 'dur':
            self.err('duration literals are only allowed in window()')
        self.err('expected an expression')


def node_refs(n, out):
    """Collect the column names referenced by an expression tree."""
    k = n[0]
    if k == 'col':
        out.append(n[1])
    elif k in ('neg', 'pos', 'not'):
        node_refs(n[1], out)
    elif k in ('arith', 'cmp', 'strop'):
        node_refs(n[2], out)
        node_refs(n[3], out)
    elif k in ('in', 'and', 'or', 'coalesce'):
        node_refs(n[1], out)
        node_refs(n[2], out)
    elif k == 'call':
        for a in n[2]:
            node_refs(a, out)
    elif k in ('cast', 'lag', 'lead'):
        node_refs(n[1], out)
    return out


class Program:
    schemas = None      # name -> (base, fields, tok) when the DSL uses blocks
    using = None        # schema name of the pipeline
    params = ()         # [(name, type|None, default lit|None, tok)]
    sources = None      # [(source name, alias, tok)] of a multi-source pipeline
    withs = ()          # [(alias, statements, tok)]
    joins = ()          # [{left, right, lq, rq, on, within, type, proj, tok}]


def parse_dsl(src):
    toks = tokenize(src)
    p = Parser(toks)
    prog = Program()
    p.skip_nl()
    t = p.peek()
    if t[0] == 'id' and t[1] in ('schema', 'pipeline'):
        prog.schemas, pipe = p.document()
        prog.using = pipe[1]
        stmts = pipe[2]
    else:
        stmts = p.program()
    rows = []
    pre = []
    post = []
    group = window = agg = params = None
    sources = None
    withs = []
    joins = []
    last_join = max((i for i, s in enumerate(stmts) if s[0] == 'join'), default=-1)
    other = False
    for idx, s in enumerate(stmts):
        k = s[0]
        if k == 'sources':
            if sources is not None:
                fail('bad_dsl', f"line {s[2][2]}: only one sources block is allowed")
            if other:
                fail('bad_dsl', f"line {s[2][2]}: sources {{ ... }} must appear before any other statement")
            if not s[1]:
                fail('bad_dsl', f"line {s[2][2]}: sources {{ }} must bind at least one source")
            sources = s[1]
            continue
        if k != 'params':
            other = True
        if k == 'with':
            withs.append(s)
            continue
        if k == 'join':
            joins.append(s)
            continue
        if idx < last_join and (k in ('filter', 'apply') or (k == 'calc' and s[4] == 'pre')):
            what = 'calc' if k == 'calc' else k
            fail('bad_dsl', f"'{what}' statements of the pipeline must follow the join statements "
                            f"(use with <alias> {{ ... }} for per-source filters)")
        if k == 'group_by':
            if group is not None:
                fail('bad_dsl', f"line {s[2][2]}: only one group_by is allowed")
            if len(set(s[1])) != len(s[1]):
                fail('bad_dsl', f"line {s[2][2]}: duplicate column in group_by")
            group = s[1]
        elif k == 'window':
            if window is not None:
                fail('bad_dsl', f"line {s[2][2]}: only one window is allowed")
            window = s[1]
        elif k == 'aggregate':
            if agg is not None:
                fail('bad_dsl', f"line {s[2][2]}: only one aggregate is allowed")
            agg = s[1]
        elif k == 'calc':
            (pre if s[4] == 'pre' else post).append(s)
        elif k == 'params':
            if params is not None:
                fail('bad_dsl', f"line {s[2][2]}: only one params block is allowed")
            params = s[1]
        else:
            rows.append(s)
    if agg is None:
        fail('bad_dsl', 'exactly one aggregate statement is required')
    seen = set()
    reserved = set(group or ())
    if window is not None:
        reserved.update(WINDOW_KEYS)
    for fn, col, alias in agg:
        if alias in seen:
            fail('bad_dsl', f"duplicate aggregate alias '{alias}'")
        if alias in reserved:
            fail('bad_dsl', f"aggregate alias '{alias}' collides with an output key")
        seen.add(alias)
    # calc names
    calc_names = set()
    applied = {s[2] for s in rows if s[0] == 'apply'}
    out_keys = set(group or ()) | set(WINDOW_KEYS) | seen
    for c in pre + post:
        if c[1] in calc_names:
            fail('bad_dsl', f"line {c[5][2]}: duplicate calc '{c[1]}'")
        calc_names.add(c[1])
        if c[4] == 'pre' and c[1] in applied:
            fail('bad_dsl', f"line {c[5][2]}: calc '{c[1]}' collides with an apply() column")
        if c[4] == 'post_agg' and c[1] in out_keys:
            fail('bad_dsl', f"line {c[5][2]}: calc '{c[1]}' collides with an output key")
    if params is not None:
        names = set()
        for name, typ, dflt, tok in params:
            if name in names:
                fail('bad_dsl', f"line {tok[2]}: duplicate parameter '{name}'")
            names.add(name)
        prog.params = params
    # parameter names referenced anywhere: param ( 'name' )
    refs = []
    for i in range(len(toks) - 2):
        a = toks[i]
        if a[0] == 'id' and a[1] == 'param' and toks[i + 1][1] == '(' and toks[i + 2][0] in ('str', 'dstr'):
            refs.append(toks[i + 2][1])
    prog.param_refs = refs
    prog.rows = rows
    prog.group = group or []
    prog.window = window
    prog.aggs = agg
    prog.pre = pre
    prog.post = post
    prog.idents = {t[1] for t in toks if t[0] == 'id'}
    prog.sources = sources
    prog.withs = []
    prog.joins = []
    if joins and sources is None:
        fail('bad_dsl', 'join requires a sources { ... } block')
    if withs and sources is None:
        fail('bad_dsl', 'with <alias> { ... } requires a sources { ... } block')
    if sources is not None:
        if not joins:
            fail('bad_dsl', 'sources { ... } is declared but no join combines the sources')
        check_multi(prog, sources, withs, joins)
    return prog


def check_multi(prog, sources, withs, joins):
    """Structural checks of sources/with/join (bad_dsl) -> prog.withs, prog.joins."""
    aliases = {}
    for name, alias, tok in sources:
        if alias in aliases:
            fail('bad_dsl', f"line {tok[2]}: duplicate source alias '{alias}'")
        if alias == '_':
            fail('bad_dsl', f"line {tok[2]}: '_' cannot be used as a source alias")
        aliases[alias] = name
    post_in_with = None
    for s in withs:
        alias, body, tok = s[1], s[2], s[3]
        if alias not in aliases:
            fail('bad_dsl', f"line {tok[2]}: with block refers to unknown source alias '{alias}'")
        for b in body:
            if b[0] == 'calc':
                if b[4] == 'post_agg' and post_in_with is None:
                    post_in_with = (f"line {b[5][2]}: post_agg calc '{b[1]}' is not allowed inside "
                                    f"with {alias} {{ ... }} (only pre-stage calcs and filters)")
            elif b[0] != 'filter':
                what = 'statement' if b[0] in ('with', 'join', 'sources') else f"'{b[0]}'"
                fail('bad_dsl', f"line {tok[2]}: {what} is not allowed inside with {alias} {{ ... }} "
                                f"(only pre-stage calcs and filters)")
        prog.withs.append((alias, body, tok))
    results = {}        # join alias -> join index
    used = set()        # consumed join indices
    used_aliases = set()
    sides = []          # per join: (left source/join alias names, right ...)
    for ji, s in enumerate(joins):
        _, left, right, on, within, jtype, proj, jalias, tok = s
        refs = []
        for r in (left, right):
            if r[0] == 'pair':
                a, b = r[1], r[2]
                hit = None
                for pj in range(ji - 1, -1, -1):
                    if {a, b} == {sides[pj][0], sides[pj][1]}:
                        hit = pj
                        break
                if hit is None:
                    fail('bad_dsl', f"line {tok[2]}: no earlier join combines '{a}' and '{b}'")
                refs.append(('join', hit, joins[hit][7] or ('_' if hit == ji - 1 else None)))
                continue
            name = r[1]
            if name == '_':
                if ji == 0:
                    fail('bad_dsl', f"line {tok[2]}: '_' refers to the previous join, but this is the first join")
                refs.append(('join', ji - 1, '_'))
            elif name in results:
                refs.append(('join', results[name], name))
            elif name in aliases:
                used_aliases.add(name)
                refs.append(('alias', name, name))
            else:
                fail('bad_dsl', f"line {tok[2]}: unknown source or join alias '{name}'")
        used.update(r[1] for r in refs if r[0] == 'join')
        lq, rq = refs[0][2], refs[1][2]
        if refs[0][:2] == refs[1][:2] or (lq is not None and lq == rq):
            fail('bad_dsl', f"line {tok[2]}: both sides of the join are '{lq}'; bind the source "
                            f"twice with different aliases to self-join")
        names = set()
        for e, name, t in proj:
            if name in names:
                fail('bad_dsl', f"line {t[2]}: duplicate column '{name}' in project")
            names.add(name)
        if jalias is not None:
            if jalias in aliases or jalias in results or jalias == '_':
                fail('bad_dsl', f"line {tok[2]}: join alias '{jalias}' is already defined")
            results[jalias] = ji
        sides.append((left[1] if left[0] == 'ref' else None, right[1] if right[0] == 'ref' else None))
        prog.joins.append({'left': refs[0][:2], 'right': refs[1][:2], 'lq': lq, 'rq': rq, 'on': on,
                           'within': within, 'type': jtype, 'proj': proj, 'tok': tok})
    for ji in range(len(joins) - 1):
        if ji not in used:
            fail('bad_dsl', f"line {joins[ji][8][2]}: the result of this join is never used")
    for alias in aliases:
        if alias not in used_aliases:
            fail('bad_dsl', f"source alias '{alias}' is not used by any join")
    if post_in_with is not None:
        fail('type_error', post_in_with)


# --------------------------------------------------------------------------
# Parameters and schemas
# --------------------------------------------------------------------------
def parse_param_value(name, raw, typ, ts_parse):
    v = raw.strip()
    try:
        if typ == 'str':
            return raw
        if typ == 'int':
            if not _is_int(v):
                raise ValueError
            return int(v)
        if typ == 'float':
            if not _is_float(v):
                raise ValueError
            f = float(v)
            if f - f != 0.0:
                raise ValueError
            return f
        if typ == 'bool':
            low = v.lower()
            if low not in ('true', 'false'):
                raise ValueError
            return low == 'true'
        return ts_parse(v)
    except (ValueError, OverflowError):
        fail('type_error', f"parameter '{name}': cannot parse {raw!r} as {DSL_TYPE[typ]}")


def resolve_params(prog, cli, tz, fmt):
    """-> {name: (type, value)} for declared and referenced parameters."""
    iso = make_ts_parser(None, tz)
    custom = make_ts_parser(fmt, tz) if fmt is not None else None

    def ts_parse(s):
        try:
            return iso(s)
        except (ValueError, OverflowError):
            if custom is None:
                raise
            return custom(s)

    declared = {d[0] for d in prog.params}
    for name, typ, dflt, tok in prog.params:
        if dflt is None and name not in cli:
            fail('bad_dsl', f"parameter '{name}' has no default and was not given with --param")
    for name in prog.param_refs:
        if name not in declared and name not in cli:
            fail('bad_dsl', f"parameter '{name}' is not declared and was not given with --param")
    out = {}
    for name, typ, dflt, tok in prog.params:
        if typ is None:
            typ = dflt[1] if dflt is not None else 'str'
        if name in cli:
            out[name] = (typ, parse_param_value(name, cli[name], typ, ts_parse))
            continue
        lt, val = dflt[1], dflt[2]
        if lt == typ:
            out[name] = (typ, val)
        elif typ == 'float' and lt == 'int':
            out[name] = (typ, float(val))
        elif typ == 'ts' and lt == 'str':
            out[name] = (typ, parse_param_value(name, val, 'ts', ts_parse))
        else:
            fail('type_error', f"parameter '{name}': default {val!r} is not a {DSL_TYPE[typ]}")
    for name in prog.param_refs:
        if name not in out:
            out[name] = ('str', cli[name])
    return out


def resolve_window(window, params):
    if not isinstance(window, tuple):
        return window
    typ, val = params[window[1]]
    import re
    m = re.fullmatch(r'\s*(\d+)([mhd])\s*', val) if typ == 'str' else None
    if m is None:
        fail('type_error', f"parameter '{window[1]}' is not a duration such as 10m, 1h or 7d")
    secs = int(m.group(1)) * DUR_UNITS[m.group(2)]
    if secs <= 0:
        fail('bad_dsl', 'window duration must be positive')
    return secs


def flatten_schemas(schemas):
    """Resolve inheritance -> {name: [(field, type, expr|None, tok)]}.
    Structural problems are bad_dsl; illegal overrides are type errors (raised
    after all structural checks)."""
    for name, (base, fields, tok) in schemas.items():
        seen = [name]
        cur = base
        while cur is not None:
            if cur not in schemas:
                fail('bad_dsl', f"line {tok[2]}: schema '{name}' extends unknown schema '{cur}'")
            if cur in seen:
                fail('bad_dsl', f"circular schema inheritance: {' -> '.join(seen + [cur])}")
            seen.append(cur)
            cur = schemas[cur][0]
    flat = {}
    bad_overrides = []

    def resolve(name):
        if name in flat:
            return flat[name]
        base, fields, tok = schemas[name]
        out = list(resolve(base)) if base is not None else []
        pos = {f[0]: i for i, f in enumerate(out)}
        for f in fields:
            i = pos.get(f[0])
            if i is None:
                pos[f[0]] = len(out)
                out.append(f)
            else:
                bt = out[i][1]
                if not (bt == f[1] or (bt == 'int' and f[1] == 'float')):
                    bad_overrides.append(
                        f"line {f[3][2]}: schema '{name}' cannot override field '{f[0]}' "
                        f"from {DSL_TYPE[bt]} to {DSL_TYPE[f[1]]}")
                out[i] = f
        flat[name] = out
        return out

    for name in schemas:
        resolve(name)
    # calculated fields may only reference earlier-declared fields
    for name, fields in flat.items():
        avail = set()
        for fname, typ, e, tok in fields:
            if e is not None:
                for r in node_refs(e, []):
                    if r not in avail:
                        what = 'later-declared' if any(f[0] == r for f in fields) else 'unknown'
                        fail('bad_dsl', f"line {tok[2]}: calculated field '{fname}' in schema "
                                        f"'{name}' references {what} field '{r}'")
            avail.add(fname)
    return flat, bad_overrides


def compile_schema(comp, fields):
    """Bind physical fields (every declared field is converted and validated for
    each row) and schema-level calcs.  Calcs remember the physical fields they
    depend on so that referencing them counts as referencing those fields."""
    comp.track = False
    deps = {}
    for fname, typ, e, tok in fields:
        if e is None:
            comp.col(fname)
            deps[fname] = frozenset((fname,))
        else:
            d = set()
            for r in node_refs(e, []):
                d |= deps.get(r, frozenset())
            comp.calc(fname, e, typ)
            deps[fname] = frozenset(d)
            comp.env[fname] = comp.env[fname] + (deps[fname],)
    comp.track = True


# --------------------------------------------------------------------------
# Runtime helpers (bound into the generated row loop)
# --------------------------------------------------------------------------
from datetime import datetime, timezone, timedelta

UTC = timezone.utc
EPOCH = datetime(1970, 1, 1, tzinfo=UTC)
_fromiso = datetime.fromisoformat


def iso_fallback(s):
    t = s.strip()
    if t and t[-1] == 'z':
        t = t[:-1] + 'Z'
    return _fromiso(t)


def make_ts_parser(fmt, tz):
    """Standalone parser (used for type inference and diagnostics)."""
    def parse(s):
        if fmt is None:
            try:
                d = _fromiso(s)
            except ValueError:
                d = iso_fallback(s)
        else:
            d = datetime.strptime(s, fmt)
        z = d.tzinfo
        if z is None:
            d = d.replace(tzinfo=tz)
            if tz is not UTC:
                d = d.astimezone(UTC)
        elif z is not UTC:
            d = d.astimezone(UTC)
        return d
    return parse


def round0(x):
    if x < 0.0:
        a = -x
        fr = a % 1.0
        r = a - fr
        if fr >= 0.5:
            r += 1.0
        return -r
    fr = x % 1.0
    r = x - fr
    if fr >= 0.5:
        r += 1.0
    return r


_QUANT = {}
_DCTX = None


_P10 = [10.0 ** i for i in range(16)]


def round_digits(x, d):
    global _DCTX
    if d == 0:
        return round0(x)
    if 0 < d < 16:
        # Fast path: away from a .5 tie the float computation is exact and
        # equals rounding the shortest decimal repr (m / p is correctly rounded).
        p = _P10[d]
        a = -x if x < 0.0 else x
        y = a * p
        if y < 1e9:
            fr = y % 1.0
            if fr < 0.499999 or fr > 0.500001:
                m = y - fr
                if fr > 0.5:
                    m += 1.0
                r = m / p
                return -r if x < 0.0 else r
    if x != x or x == float('inf') or x == float('-inf'):
        return x
    import decimal
    if _DCTX is None:
        _DCTX = decimal.Context(prec=400, rounding=decimal.ROUND_HALF_UP)
    q = _QUANT.get(d)
    if q is None:
        q = _QUANT[d] = decimal.Decimal(1).scaleb(-d)
    try:
        return float(decimal.Decimal(repr(x)).quantize(q, context=_DCTX))
    except decimal.InvalidOperation:
        return x


def round_int(x, d):
    if d >= 0:
        return x
    q = 10 ** (-d)
    if x < 0:
        return -((-x + q // 2) // q * q)
    return (x + q // 2) // q * q


def fmt_ts(d):
    # d is an aware UTC datetime: isoformat() ends with '+00:00'
    return d.isoformat()[:-6] + 'Z'


def make_cast(ts_parse):
    from math import floor
    one_sec = timedelta(seconds=1)

    def cast(v, frm, to):
        if v is None:
            return None
        try:
            if to == 'str':
                if frm == 'ts':
                    return fmt_ts(v)
                if frm == 'bool':
                    return 'true' if v else 'false'
                return repr(v) if frm == 'float' else str(v)
            if to == 'int':
                if frm == 'str':
                    if not _is_int(v):
                        raise ValueError
                    return int(v.strip())
                if frm == 'ts':
                    return (v - EPOCH) // one_sec
                if frm == 'float':
                    return int(v)
                return int(v)
            if to == 'float':
                if frm == 'str':
                    if not _is_float(v):
                        raise ValueError
                    return float(v.strip())
                if frm == 'ts':
                    return (v - EPOCH) / one_sec
                return float(v)
            if to == 'bool':
                if frm == 'str':
                    low = v.strip().lower()
                    if low not in ('true', 'false'):
                        raise ValueError
                    return low == 'true'
                return v != 0
            # timestamp
            if frm == 'str':
                return ts_parse(v.strip())
            if v - v != 0:
                raise ValueError
            return EPOCH + timedelta(seconds=v)
        except (ValueError, OverflowError, TypeError):
            raise CastError(f"cannot cast {v!r} from {DSL_TYPE[frm]} to {DSL_TYPE[to]}")
    return cast


class CastError(Exception):
    """A cast that fails for one row's value (a TYPE_ERROR bad record)."""


def shift(R, j, f):
    return f(j) if 0 <= j < len(R) else None


def helper_ns():
    """Runtime helpers referenced by generated row and post-aggregation code."""
    return {'_shift': shift, '_float': float, '_len': len, '_r0': round0, '_rd': round_digits,
            '_rdi': round_int}


# --------------------------------------------------------------------------
# Compiler: type check + generate null-aware row / post-aggregation code
# --------------------------------------------------------------------------
import re

NUMERIC = ('int', 'float')
TYPE_NAMES = {'int': 'number', 'float': 'number', 'str': 'string', 'ts': 'timestamp', 'bool': 'boolean'}
FOLD_CHUNK = 65536
FOLD_MIN = 4096
_SIMPLE = re.compile(r'[A-Za-z_]\w*\Z')


def tname(t):
    return TYPE_NAMES[t]


class Compiler:
    """Type checks expressions and emits Python source.  Any value may be null
    (None) and nulls propagate; `nonnull` holds the code strings known never to
    be null (literals, params and expressions built only from them) so their
    checks are skipped."""

    def __init__(self, fields, tz, fmt, post=False):
        self.fields = list(fields)      # physical fields [(name, type)] -> c<j>
        self.env = {name: ('raw', typ, j) for j, (name, typ) in enumerate(self.fields)}
        self.tz = tz
        self.fmt = fmt
        self.post = post                # post-aggregation mode: lag/lead, read from _R[_i]
        self.lines = []
        self.used = set()               # physical field indices read for every row
        self.refs = set()               # physical field names the pipeline references
        self.track = True
        self.consts = {}
        self.nonnull = set()
        self.nvar = 0
        self.ntmp = 0
        self.params = {}
        self.blocked = {}   # name -> message for names that exist but are out of scope

    def const(self, val):
        name = f'_k{len(self.consts)}'
        self.consts[name] = val
        return name

    def nn(self, code):
        self.nonnull.add(code)
        return code

    def bind(self, c):
        """-> (code for the first use, name for later uses), evaluating c once."""
        if c in self.nonnull or _SIMPLE.match(c):
            return c, c
        self.ntmp += 1
        t = f'_t{self.ntmp}'
        return f'({t} := {c})', t

    def guard(self, ops, make):
        """Null propagation: None if any operand is None, else make(*operands)."""
        conds = []
        names = []
        for c in ops:
            if c in self.nonnull:
                names.append(c)
                continue
            first, name = self.bind(c)
            conds.append(f'{first} is None')
            names.append(name)
        body = make(*names)
        if not conds:
            return self.nn(body)
        return f"(None if {' or '.join(conds)} else {body})"

    def col(self, name):
        info = self.env.get(name)
        if info is None:
            msg = self.blocked.get(name)
            if msg:
                fail('bad_dsl', msg)
            fail('type_error', f"unknown column '{name}'")
        kind = info[0]
        if kind == 'var':
            if self.track and len(info) > 3:
                self.refs.update(info[3])
            return info[2], info[1]
        if kind == 'post':
            return f'_R[_i][{name!r}]', info[1]
        self.used.add(info[2])
        if self.track:
            self.refs.add(name)
        return f'c{info[2]}', info[1]

    def param(self, name):
        p = self.params.get(name)
        if p is None:
            fail('bad_dsl', f"unknown parameter '{name}'")
        return p

    def str_left(self, n):
        """Left operand of 'in': a string literal or a string parameter."""
        if n[0] == 'lit' and n[1] == 'str':
            return self.nn(repr(n[2]))
        if n[0] == 'param':
            t, val = self.param(n[1])
            if t == 'str':
                return self.nn(repr(val))
        fail('type_error', "left operand of 'in' must be a string literal")

    def lag_offset(self, fn, kn):
        if kn[0] == 'lit':
            if kn[1] != 'int':
                fail('type_error', f"{fn}() offset must be an integer, got {tname(kn[1])}")
            return kn[2]
        t, val = self.param(kn[1])
        if t != 'int':
            fail('type_error', f"{fn}() offset parameter '{kn[1]}' must be an int, got {DSL_TYPE[t]}")
        if val <= 0:
            fail('runtime_error', f"{fn}() offset parameter '{kn[1]}' must be positive, got {val}")
        return val

    def gen(self, n):
        k = n[0]
        if k == 'lit':
            t, val = n[1], n[2]
            if t == 'str':
                return self.nn(repr(val)), 'str'
            if t == 'bool':
                return self.nn('True' if val else 'False'), 'bool'
            if t == 'int':
                return self.nn(repr(val)), 'int'
            if val - val == 0.0:
                return self.nn(repr(val)), 'float'
            return self.nn(self.const(val)), 'float'
        if k == 'col':
            return self.col(n[1])
        if k == 'param':
            t, val = self.param(n[1])
            if t in ('str', 'int', 'bool'):
                return self.nn(repr(val)), t
            return self.nn(self.const(val)), t
        if k == 'neg' or k == 'pos':
            c, t = self.gen(n[1])
            if t not in NUMERIC:
                fail('type_error', f"unary '{'-' if k == 'neg' else '+'}' requires a number, got {tname(t)}")
            if k == 'pos':
                return c, t
            return self.guard([c], lambda a: f'(-{a})'), t
        if k == 'arith':
            op = n[1]
            lc, lt = self.gen(n[2])
            rc, rt = self.gen(n[3])
            if lt not in NUMERIC or rt not in NUMERIC:
                fail('type_error', f"operator '{op}' requires numbers, got {tname(lt)} and {tname(rt)}")
            t = 'float' if (op == '/' or lt == 'float' or rt == 'float') else 'int'
            return self.guard([lc, rc], lambda a, b: f'({a} {op} {b})'), t
        if k == 'cmp':
            op = n[1]
            lc, lt = self.gen(n[2])
            rc, rt = self.gen(n[3])
            if lt in NUMERIC and rt in NUMERIC:
                pass
            elif lt == rt and lt in ('str', 'ts'):
                pass
            elif lt == rt == 'bool' and op in ('==', '!='):
                pass
            else:
                fail('type_error', f"cannot compare {tname(lt)} with {tname(rt)} using '{op}'")
            return self.guard([lc, rc], lambda a, b: f'({a} {op} {b})'), 'bool'
        if k == 'in':
            left, right = n[1], n[2]
            lc = self.str_left(left)
            if right[0] != 'col':
                fail('type_error', "right operand of 'in' must be a string column")
            rc, rt = self.col(right[1])
            if rt != 'str':
                fail('type_error', f"right operand of 'in' must be a string column, got {tname(rt)}")
            return self.guard([lc, rc], lambda a, b: f'({a} in {b})'), 'bool'
        if k == 'strop':
            op = n[1]
            lc, lt = self.gen(n[2])
            rc, rt = self.gen(n[3])
            if lt != 'str' or rt != 'str':
                fail('type_error', f"{op} requires strings, got {tname(lt)} and {tname(rt)}")
            if op == 'contains':
                return self.guard([lc, rc], lambda a, b: f'({b} in {a})'), 'bool'
            meth = op.replace('_', '')
            return self.guard([lc, rc], lambda a, b: f'{a}.{meth}({b})'), 'bool'
        if k == 'and' or k == 'or':
            lc, lt = self.gen(n[1])
            rc, rt = self.gen(n[2])
            if lt != 'bool' or rt != 'bool':
                fail('type_error', f"operator '{'&' if k == 'and' else '|'}' requires booleans, "
                                   f"got {tname(lt)} and {tname(rt)}")
            if lc in self.nonnull and rc in self.nonnull:
                return self.nn(f'({lc} {k} {rc})'), 'bool'
            # three-valued logic: a dominant operand (false for &, true for |)
            # decides; otherwise any null makes the result null
            dom, other = ('False', 'True') if k == 'and' else ('True', 'False')
            af, a = self.bind(lc)
            bf, b = self.bind(rc)
            return (f'({dom} if {af} is {dom} else ({dom} if {bf} is {dom} else '
                    f'(None if {a} is None or {b} is None else {other})))'), 'bool'
        if k == 'not':
            c, t = self.gen(n[1])
            if t != 'bool':
                fail('type_error', f"operator '!' requires a boolean, got {tname(t)}")
            return self.guard([c], lambda a: f'(not {a})'), 'bool'
        if k == 'coalesce':
            lc, lt = self.gen(n[1])
            rc, rt = self.gen(n[2])
            if lt == rt:
                t = lt
            elif lt in NUMERIC and rt in NUMERIC:
                t = 'float'
            else:
                fail('type_error', f"coalesce() arguments must have the same type, "
                                   f"got {DSL_TYPE[lt]} and {DSL_TYPE[rt]}")
            if lc in self.nonnull:
                c = lc
            else:
                af, a = self.bind(lc)
                cond = f'{af} is None' + (f' or {a} != {a}' if lt == 'float' else '')
                c = f'({rc} if {cond} else {a})'
                if rc in self.nonnull:
                    self.nn(c)
            if t != lt or t != rt:
                c = self.guard([c], lambda a: f'_float({a})')
            return c, t
        if k == 'cast':
            c, s = self.gen(n[1])
            to = n[2]
            if s == to:
                return c, to
            if {s, to} == {'bool', 'ts'}:
                fail('type_error', f"cannot cast {DSL_TYPE[s]} to {DSL_TYPE[to]}")
            return f'_cast({c}, {s!r}, {to!r})', to
        if k == 'lag' or k == 'lead':
            if not self.post:
                fail('bad_dsl', f"{k}() is only allowed in @stage(post_agg) calcs")
            off = self.lag_offset(k, n[2])
            c, t = self.gen(n[1])
            return f"_shift(_R, _i {'-' if k == 'lag' else '+'} {off}, lambda _i: {c})", t
        if k == 'call':
            fn, args = n[1], n[2]
            c, t = self.gen(args[0])
            if fn == 'len':
                if t != 'str':
                    fail('type_error', f"len() requires a string, got {tname(t)}")
                return self.guard([c], lambda a: f'_len({a})'), 'int'
            if fn in ('day', 'month', 'year'):
                if t != 'ts':
                    fail('type_error', f"{fn}() requires a timestamp, got {tname(t)}")
                return self.guard([c], lambda a: f'{a}.{fn}'), 'int'
            # round
            if t not in NUMERIC:
                fail('type_error', f"round() requires a number, got {tname(t)}")
            if len(args) == 1:
                if t == 'int':
                    return c, t
                return self.guard([c], lambda a: f'_r0({a})'), t
            dn = args[1]
            dc, dt = self.gen(dn)
            if dt != 'int':
                fail('type_error', f"round() digits must be an integer, got {tname(dt)}")
            lit = None
            if dn[0] == 'lit':
                lit = dn[2]
            elif dn[0] == 'neg' and dn[1][0] == 'lit':
                lit = -dn[1][2]
            if t == 'int':
                if lit is not None and lit >= 0:
                    return c, t
                return self.guard([c, dc], lambda a, d: f'_rdi({a}, {d})'), t
            if lit == 0:
                return self.guard([c], lambda a: f'_r0({a})'), t
            return self.guard([c, dc], lambda a, d: f'_rd({a}, {d})'), t
        raise AssertionError(k)

    def typed(self, name, e, typ):
        """Generate e and check it against the declared calc type."""
        c, t = self.gen(e)
        if t != typ and not (t == 'int' and typ == 'float'):
            fail('type_error', f"calc '{name}' is declared {DSL_TYPE[typ]} but its expression "
                               f"has type {DSL_TYPE[t]}")
        if t != typ:
            c = self.guard([c], lambda a: f'_float({a})')
        return c

    def assign(self, c):
        v = f'v{self.nvar}'
        self.nvar += 1
        self.lines.append(f'{v} = {c}')
        if c in self.nonnull:
            self.nonnull.add(v)
        return v

    def calc(self, name, e, typ):
        self.env[name] = ('var', typ, self.assign(self.typed(name, e, typ)))

    def cond(self, n):
        """Code whose truthiness is "n is true": in a filter null and false both
        drop the row, so &/| at the top need no three-valued bookkeeping."""
        k = n[0]
        if k != 'and' and k != 'or':
            return self.gen(n)
        lc, lt = self.cond(n[1])
        rc, rt = self.cond(n[2])
        if lt != 'bool' or rt != 'bool':
            fail('type_error', f"operator '{'&' if k == 'and' else '|'}' requires booleans, "
                               f"got {tname(lt)} and {tname(rt)}")
        return f'({lc} {k} {rc})', 'bool'

    def statement(self, s):
        c, t = (self.cond if s[0] == 'filter' else self.gen)(s[1])
        if s[0] == 'filter':
            if t != 'bool':
                fail('type_error', f"filter expression must be boolean, got {tname(t)}")
            # a null condition drops the row, like false
            self.lines.append(f'if not {c}: continue')
        else:
            self.env[s[2]] = ('var', t, self.assign(c))


# --------------------------------------------------------------------------
# Aggregation state folding / finalisation
# --------------------------------------------------------------------------
# Buffers hold only the non-null values of a column.  Float buffers are kept
# whole so sums are computed once with fsum (exact, hence independent of row
# and file order); large int buffers are folded into exact running state
# [sum, min, max, sum of squares, count].
def make_fold(F, specs):
    def fold(G):
        for key, st in G.items():
            for j, need_ss in specs:
                buf = st[j]
                if len(buf) < FOLD_MIN:
                    continue
                fk = (key, j)
                f = F.get(fk)
                s = sum(buf)
                mn = min(buf)
                mx = max(buf)
                ss = sum([x * x for x in buf]) if need_ss else 0
                if f is None:
                    F[fk] = [s, mn, mx, ss, len(buf)]
                else:
                    f[0] += s
                    f[3] += ss
                    f[4] += len(buf)
                    if mn < f[1]:
                        f[1] = mn
                    if mx > f[2]:
                        f[2] = mx
                del buf[:]
    return fold


def sqrt_frac(n, m):
    """Correctly rounded sqrt(n/m) for non-negative integers (as CPython's
    statistics module computes pstdev)."""
    if n == 0:
        return 0.0
    q = (n.bit_length() - m.bit_length() - 109) // 2
    if q >= 0:
        mm = m << 2 * q
        a = isqrt(n // mm)
        return float((a | (a * a * mm != n)) << q)
    nn = n << -2 * q
    a = isqrt(nn // m)
    return (a | (a * a * m != nn)) / (1 << -q)


STAT_INDEX = {'sum': 0, 'average': 1, 'min': 2, 'max': 3, 'var': 4, 'std': 5, 'median': 6}


def column_stats(buf, f, isf, need_mm, need_sum, need_var, need_med, n):
    """Return (sum, average, min, max, var, std, median) over the n > 0
    non-null values of one column of one bucket (buffered values plus folded
    state f); entries that were not requested are None."""
    s = avg = mn = mx = var = std = med = None
    if need_mm:
        if buf:
            mn = min(buf)
            mx = max(buf)
            if f is not None:
                if f[1] < mn:
                    mn = f[1]
                if f[2] > mx:
                    mx = f[2]
        else:
            mn = f[1]
            mx = f[2]
    if need_sum:
        if isf:
            s = fsum(buf)
            avg = s / n
            if need_var:
                if s - s != 0.0:
                    fail('runtime_error', 'aggregate produced a non-finite value')
                # exact: floats are dyadic rationals; scale to a common 2^-k
                S = Q = k = 0
                for x in buf:
                    num, den = x.as_integer_ratio()
                    e = den.bit_length() - 1
                    if e > k:
                        S <<= e - k
                        Q <<= 2 * (e - k)
                        k = e
                    X = num << (k - e)
                    S += X
                    Q += X * X
                vn = n * Q - S * S
                vd = (n * n) << (2 * k)
                var = vn / vd
                std = sqrt_frac(vn, vd)
        else:
            s = sum(buf)
            if f is not None:
                s += f[0]
            avg = s / n
            if need_var:
                ss = sum([x * x for x in buf])
                if f is not None:
                    ss += f[3]
                vn = n * ss - s * s
                var = vn / (n * n)
                std = sqrt_frac(vn, n * n)
    if need_med:
        srt = sorted(buf)
        h = n >> 1
        if n & 1:
            med = srt[h]
        else:
            med = (srt[h - 1] + srt[h]) / 2
    return (s, avg, mn, mx, var, std, med)


# --------------------------------------------------------------------------
# Inputs: discovery and format detection
# --------------------------------------------------------------------------
import os
import zlib

REQUIRED = {'timestamp': 'ts', 'location': 'str', 'item': 'str', 'price': 'float',
            'quantity': 'float', 'unit': 'str', 'category': 'str'}
DEFAULT_NULLS = ('', 'null', 'NULL', 'NaN')
FORMATS = ('auto', 'csv', 'tsv', 'parquet')
EXTENSIONS = (('.csv.gz', 'csv', True), ('.tsv.gz', 'tsv', True), ('.csv', 'csv', False),
              ('.tsv', 'tsv', False), ('.parquet', 'parquet', False))
DELIMS = {'csv': ',', 'tsv': '\t'}
READ_ERRORS = (OSError, EOFError, UnicodeDecodeError, zlib.error)


class Source:
    """One input file: display path, format ('csv'|'tsv'|'parquet'), gzip flag
    and, once read_header() ran, its column names -> position."""

    def __init__(self, path, kind, gz):
        self.path = path
        self.kind = kind
        self.gz = gz
        self.header = []
        self.hidx = {}
        self.ptypes = {}    # Parquet: column name -> arrow type

    def label(self):
        return self.kind + ('.gz' if self.gz else '')


def ext_format(path):
    low = os.path.basename(path).lower()
    for ext, kind, gz in EXTENSIONS:
        if low.endswith(ext):
            return kind, gz
    return None


def ambiguous(path):
    ext = os.path.splitext(os.path.basename(path))[1].lower()
    return ext == '' or ext == '.gz'


def sniff(path, forced):
    """Format of a file whose extension does not tell it."""
    try:
        with open(path, 'rb') as f:
            head = f.read(4)
    except OSError as e:
        fail('bad_io', f"cannot open '{path}': {e.strerror or e}")
    gz = head[:2] == b'\x1f\x8b'
    if forced != 'auto':
        return Source(path, forced, gz and forced != 'parquet')
    if head == b'PAR1':
        return Source(path, 'parquet', False)
    first = ''
    try:
        if gz:
            import gzip
            fh = gzip.open(path, 'rt', encoding='utf-8-sig', newline='')
        else:
            fh = open(path, 'r', encoding='utf-8-sig', newline='')
        with fh:
            first = fh.readline()
    except READ_ERRORS:
        pass
    return Source(path, 'tsv' if '\t' in first and ',' not in first else 'csv', gz)


def resolve_inputs(specs, recursive, forced):
    """Union of the files named by every --input (file, directory or glob),
    de-duplicated and sorted by path so processing order never depends on the
    order of the arguments."""
    found, nomatch = collect_inputs(specs, recursive, forced)
    if nomatch:
        fail('bad_io', f"no files match input '{nomatch[0]}'")
    if not found:
        fail('bad_io', 'no input files found')
    return sorted(found.values(), key=lambda s: s.path)


def collect_inputs(specs, recursive, forced, base=None):
    """-> ({realpath: Source}, [globs matching nothing]).  A relative spec that
    matches nothing from the working directory is retried relative to base."""
    import glob
    found = {}
    nomatch = []

    def add(path, explicit):
        fmt = ext_format(path)
        if fmt is not None:
            src = Source(path, *fmt)
        elif explicit or (forced != 'auto' and ambiguous(path)):
            src = sniff(path, forced)
        else:
            return
        key = os.path.realpath(path)
        cur = found.get(key)
        if cur is None or path < cur.path:
            found[key] = src

    def walk(d):
        if recursive:
            for root, dirs, files in os.walk(d):
                dirs[:] = sorted(x for x in dirs if not x.startswith('.'))
                for name in sorted(files):
                    if not name.startswith('.'):
                        add(os.path.join(root, name), False)
            return
        try:
            names = sorted(os.listdir(d))
        except OSError as e:
            fail('bad_io', f"cannot list directory '{d}': {e.strerror or e}")
        for name in names:
            p = os.path.join(d, name)
            if not name.startswith('.') and os.path.isfile(p):
                add(p, False)

    for spec in specs:
        cands = [spec]
        if base is not None and not os.path.isabs(spec):
            cands.append(os.path.join(base, spec))
        for cand in cands:
            if os.path.isdir(cand):
                walk(cand)
                break
            if os.path.isfile(cand):
                add(cand, True)
                break
            if glob.has_magic(cand):
                matches = sorted(glob.glob(cand, recursive=True))
                for m in matches:
                    if os.path.isdir(m):
                        walk(m)
                    elif os.path.isfile(m):
                        add(m, False)
                if matches:
                    break
        else:
            if not glob.has_magic(spec):
                fail('bad_io', f"input '{spec}' does not exist")
            nomatch.append(spec)
    return found, nomatch


# --------------------------------------------------------------------------
# Textual (CSV/TSV, optionally gzipped) inputs
# --------------------------------------------------------------------------
SMALL_INPUT = 4 << 20

_FLOAT_CHARS = frozenset('0123456789+-.eE')


def _is_int(v):
    t = v.strip()
    if t[:1] in ('+', '-'):
        t = t[1:]
    return t.isascii() and t.isdigit()


def _is_float(v):
    t = v.strip()
    if not t or not _FLOAT_CHARS.issuperset(t):
        return False
    try:
        float(t)
    except ValueError:
        return False
    return True


def open_text(src):
    try:
        if src.gz:
            import gzip
            fh = gzip.open(src.path, 'rt', encoding='utf-8-sig', newline='')
        else:
            fh = open(src.path, 'r', encoding='utf-8-sig', newline='', buffering=1 << 20)
    except OSError as e:
        fail('bad_io', f"cannot open '{src.path}': {e.strerror or e}")
    return fh, _csv.reader(fh, delimiter=DELIMS[src.kind])


def _pq():
    try:
        import pyarrow
        import pyarrow.parquet
    except ImportError:
        fail('bad_io', 'reading Parquet requires the pyarrow package')
    return pyarrow, pyarrow.parquet


def read_header(src):
    if src.kind == 'parquet':
        pa, pq = _pq()
        try:
            schema = pq.read_schema(src.path)
        except Exception as e:
            fail('bad_io', f"cannot read Parquet '{src.path}': {e}")
        src.header = list(schema.names)
        for i, name in enumerate(src.header):
            if name not in src.hidx:
                src.hidx[name] = i
                src.ptypes[name] = schema.field(i).type
        return
    fh, rd = open_text(src)
    try:
        with fh:
            header = next(rd)
    except StopIteration:
        fail('bad_io', f"input '{src.path}' is empty (header row required)")
    except _csv.Error as e:
        fail('bad_io', f"malformed header in '{src.path}': {e}")
    except READ_ERRORS as e:
        fail('bad_io', f"cannot read '{src.path}': {e}")
    src.header = [h.strip() for h in header]
    for i, h in enumerate(src.header):
        if h not in src.hidx:
            src.hidx[h] = i


def _arrow_tags(t):
    """DSL types an arrow column type can be read as."""
    pa, _ = _pq()
    P = pa.types
    if P.is_dictionary(t):
        t = t.value_type
    if P.is_integer(t):
        return {'int', 'float'}
    if P.is_floating(t) or P.is_decimal(t):
        return {'float'}
    if P.is_boolean(t):
        return {'bool'}
    if P.is_timestamp(t):
        return {'ts'}
    return set()


def infer_types(sources, names, nulls, ts_parse):
    """Infer the type of undeclared columns from every input (schema-less
    DSL).  Null markers carry no type information."""
    allowed = {name: {'int', 'float', 'bool', 'ts'} for name in names}
    seen = dict.fromkeys(names, False)
    rows = 0
    NL = frozenset(nulls)
    for src in sources:
        if src.kind == 'parquet':
            rows += 1
            for name in names:
                t = src.ptypes.get(name)
                if t is not None:
                    seen[name] = True
                    allowed[name] &= _arrow_tags(t)
            continue
        cols = [(name, src.hidx[name]) for name in names if name in src.hidx]
        if not cols:
            continue
        fh, rd = open_text(src)
        try:
            with fh:
                next(rd, None)
                for row in rd:
                    if not row:
                        continue
                    rows += 1
                    for name, i in cols:
                        if i >= len(row):
                            continue
                        v = row[i]
                        if v in NL or v.strip() in NL or v.strip().lower() == 'nan':
                            continue
                        seen[name] = True
                        a = allowed[name]
                        if not a:
                            continue
                        if 'int' in a and not _is_int(v):
                            a.discard('int')
                        if 'float' in a and not _is_float(v):
                            a.discard('float')
                        if 'bool' in a and v.strip().lower() not in ('true', 'false'):
                            a.discard('bool')
                        if 'ts' in a:
                            try:
                                ts_parse(v)
                            except (ValueError, OverflowError):
                                a.discard('ts')
        except (UnicodeDecodeError, OSError, EOFError, zlib.error) as e:
            fail('bad_io', f"cannot read '{src.path}': {e}")
        except _csv.Error as e:
            fail('bad_io', f"malformed input '{src.path}' at line {rd.line_num}: {e}")
    types = {}
    for name in names:
        a = allowed[name]
        if not seen[name]:
            types[name] = 'float' if rows == 0 else 'str'
        else:
            types[name] = next((t for t in ('int', 'float', 'bool', 'ts') if t in a), 'str')
    return types


def ts_normalize(v, tz, indent):
    """Lines converting the parsed datetime in v to aware UTC."""
    p = ' ' * indent
    out = [f'{p}_z = {v}.tzinfo']
    if tz is UTC:
        out.append(f'{p}if _z is None: {v} = {v}.replace(tzinfo=_UTC)')
    else:
        out.append(f'{p}if _z is None: {v} = {v}.replace(tzinfo=_TZ).astimezone(_UTC)')
    out.append(f'{p}elif _z is not _UTC: {v} = {v}.astimezone(_UTC)')
    return out


def text_prologue(fields, used, hidx, tz, fmt):
    """Per-row conversion of the used physical fields from text.  Null markers
    become None; a field missing from the file is None for every row."""
    L = []
    for j in used:
        name, typ = fields[j]
        v = f'c{j}'
        i = hidx.get(name)
        if i is None:
            L.append(f'{v} = None')
            continue
        L.append(f'_s = row[{i}]')
        if typ == 'str':
            L.append(f'{v} = None if _s in _NL else _s')
            continue
        L.append('if _s in _NL:')
        L.append(f'    {v} = None')
        L.append('else:')
        if typ == 'float':
            L += ['    try:', f'        {v} = _float(_s)', '    except ValueError:',
                  f'        {v} = _nullor(_s)', '    else:',
                  f'        if {v} - {v} != 0.0: {v} = _nonfin({v})']
        elif typ == 'int':
            L += ['    try:', f'        {v} = _int(_s)', '    except ValueError:',
                  f'        {v} = _nullor(_s)']
        elif typ == 'bool':
            L += ['    _b = _s.strip().lower()', "    if _b == 'true':", f'        {v} = True',
                  "    elif _b == 'false':", f'        {v} = False', '    else:',
                  f'        {v} = _nullor(_s)']
        else:
            parse = '_fiso(_s)' if fmt is None else '_strp(_s, _FMT)'
            L += ['    try:', f'        {v} = {parse}', '    except ValueError:',
                  f'        {v} = _tsslow(_s)', '    else:']
            L += ts_normalize(v, tz, 8)
    return L


def text_helpers(nulls, ts_parse):
    """Slow-path helpers shared by generated conversions and diagnostics."""
    NL = frozenset(nulls)

    def nullor(s):
        if s.strip() in NL:
            return None
        raise ValueError(f'invalid value {s!r}')

    def nonfin(x):
        if x != x:
            return None     # textual NaN in a numeric field is null
        raise ValueError('non-finite number')

    def tsslow(s):
        if s.strip() in NL:
            return None
        return ts_parse(s)

    def convert(s, typ):
        """Reference conversion of one text field (mirrors text_prologue)."""
        if s in NL:
            return None
        if typ == 'str':
            return s
        if typ == 'float':
            try:
                x = float(s)
            except ValueError:
                return nullor(s)
            return nonfin(x) if x - x != 0.0 else x
        if typ == 'int':
            try:
                return int(s)
            except ValueError:
                return nullor(s)
        if typ == 'bool':
            b = s.strip().lower()
            if b in ('true', 'false'):
                return b == 'true'
            return nullor(s)
        return tsslow(s)

    return {'_NL': NL, '_nullor': nullor, '_nonfin': nonfin, '_tsslow': tsslow}, convert


# --------------------------------------------------------------------------
# Parquet inputs
# --------------------------------------------------------------------------
class BadValue(Exception):
    """A value that cannot be read as its schema type; stored in place of the
    value and raised when the row is converted."""

    def __init__(self, cls, field, value, msg):
        Exception.__init__(self, msg)
        self.cls = cls
        self.field = field
        self.value = value
        self.msg = msg


_TS_SCALE = {'s': (1000000, 1), 'ms': (1000, 1), 'us': (1, 1), 'ns': (1, 1000)}


def _pylist(col):
    try:
        return col.to_pylist()
    except Exception:
        return [str(x) if x.is_valid else None for x in col]


def parquet_values(col, name, typ, tz):
    """-> (python values for one column, whether any value is bad).  Values use
    the file's logical type; nulls stay None, NaN floats become None."""
    pa, _ = _pq()
    P = pa.types
    t = col.type
    if P.is_dictionary(t):
        col = col.cast(t.value_type)
        t = col.type
    is_view = getattr(P, 'is_string_view', None)
    if typ == 'str' and (P.is_string(t) or P.is_large_string(t) or (is_view is not None and is_view(t))):
        return col.to_pylist(), False
    if typ == 'int' and P.is_integer(t):
        return col.to_pylist(), False
    if typ == 'bool' and P.is_boolean(t):
        return col.to_pylist(), False
    if typ == 'float' and (P.is_floating(t) or P.is_integer(t) or P.is_decimal(t)):
        out = []
        bad = False
        for v in col.to_pylist():
            if v is None:
                out.append(None)
                continue
            x = float(v)
            if x - x != 0.0:
                if x != x:
                    x = None
                else:
                    x = BadValue('PARQUET_TYPE_MISMATCH', name, repr(x),
                                 f"column '{name}' holds a non-finite number")
                    bad = True
            out.append(x)
        return out, bad
    if typ == 'ts' and P.is_timestamp(t):
        mul, div = _TS_SCALE[t.unit]
        aware = t.tz is not None
        base = EPOCH if aware else datetime(1970, 1, 1)
        out = []
        bad = False
        for v in col.cast(pa.int64()).to_pylist():
            if v is None:
                out.append(None)
                continue
            try:
                d = base + timedelta(microseconds=v * mul // div)
                if not aware:
                    # naive timestamps are wall-clock time in --tz
                    d = d.replace(tzinfo=tz)
                    if tz is not UTC:
                        d = d.astimezone(UTC)
            except OverflowError:
                d = BadValue('PARQUET_TYPE_MISMATCH', name, v,
                             f"column '{name}' holds an out-of-range timestamp")
                bad = True
            out.append(d)
        return out, bad
    msg = f"column '{name}' has Parquet type {t}, which cannot be read as {DSL_TYPE[typ]}"
    out = [None if v is None else BadValue('PARQUET_TYPE_MISMATCH', name, v, msg)
           for v in _pylist(col)]
    return out, any(v is not None for v in out)


def load_parquet(src, fields, used, tz):
    """-> (rows, {field index: tuple position}, {field index: has bad values}).
    Each row tuple ends with the row's 0-based index in the file."""
    pa, pq = _pq()
    present = [j for j in used if fields[j][0] in src.hidx]
    try:
        pf = pq.ParquetFile(src.path)
        table = pf.read(columns=[fields[j][0] for j in present])
        n = table.num_rows
        cols = []
        pos = {}
        bad = {}
        for j in present:
            name, typ = fields[j]
            vals, has_bad = parquet_values(table.column(name), name, typ, tz)
            pos[j] = len(cols)
            bad[j] = has_bad
            cols.append(vals)
    except MTLError:
        raise
    except Exception as e:
        fail('bad_io', f"cannot read Parquet '{src.path}': {e}")
    cols.append(range(n))
    return list(zip(*cols)), pos, bad


def parquet_prologue(used, pos, bad):
    L = []
    for j in used:
        v = f'c{j}'
        k = pos.get(j)
        if k is None:
            L.append(f'{v} = None')
            continue
        L.append(f'{v} = row[{k}]')
        if bad[j]:
            L.append(f'if {v}.__class__ is _PB: raise {v}')
    return L


# --------------------------------------------------------------------------
# Bad records
# --------------------------------------------------------------------------
class NullTimestamp(Exception):
    """A row without a timestamp cannot be assigned to a window."""


BAD_KIND = {'PARSE_TYPE_MISMATCH': 'type_error', 'TIMESTAMP_PARSE_ERROR': 'type_error',
            'TYPE_ERROR': 'type_error', 'MISSING_REQUIRED_FIELD': 'type_error',
            'PARQUET_TYPE_MISMATCH': 'type_error', 'RUNTIME_ERROR': 'runtime_error'}
_WHAT = {'float': 'number', 'int': 'integer', 'ts': 'timestamp', 'bool': 'boolean'}


def _jsonable(v):
    if isinstance(v, BadValue):
        v = v.value
        if v is None or isinstance(v, (str, int, float)):
            return v
    if isinstance(v, datetime):
        return fmt_ts(v) if v.tzinfo is UTC else v.isoformat()
    if isinstance(v, bytes):
        return v.decode('utf-8', 'replace')
    return str(v)


def _line_breaks(row):
    n = 0
    for f in row:
        if '\n' in f or '\r' in f:
            n += f.count('\n') + f.count('\r') - f.count('\r\n')
    return n


class BadRecords:
    """Collects rejected rows.  Non-strict: skipped (and logged when
    --bad-records-out is given).  Strict: the first one aborts the run.
    Rows arrive in (file, line) order because files are processed sorted."""

    def __init__(self, out, strict, legacy):
        self.out = out
        self.strict = strict
        self.legacy = legacy
        self.records = []
        self.count = 0

    def handler(self, src, fields, used, rd=None, pos=None, convert=None):
        textual = rd is not None

        def bad(phase, e, row):
            if isinstance(e, (MTLError, MemoryError, RecursionError)):
                raise e
            self.count += 1
            if self.out is None and not self.strict:
                return
            cls = field = value = typ = None
            short = False
            if isinstance(e, BadValue):
                cls, field, value, msg = e.cls, e.field, e.value, e.msg
            elif phase == 0:
                for j in used:
                    name, t = fields[j]
                    i = src.hidx.get(name)
                    if i is None or not textual:
                        continue
                    if i >= len(row):
                        cls, field, typ, short = 'MISSING_REQUIRED_FIELD', name, t, True
                        msg = (f"row has {len(row)} field(s) but column '{name}' is field {i + 1} "
                               f"of {len(src.header)}")
                        break
                    try:
                        convert(row[i], t)
                    except (ValueError, OverflowError):
                        cls = 'TIMESTAMP_PARSE_ERROR' if t == 'ts' else 'PARSE_TYPE_MISMATCH'
                        field, value, typ = name, row[i], t
                        msg = f"column '{name}' has invalid {_WHAT[t]} value {row[i]!r}"
                        break
                else:
                    cls, msg = 'PARSE_TYPE_MISMATCH', f'{type(e).__name__}: {e}'
            elif isinstance(e, NullTimestamp):
                cls, field, typ = 'MISSING_REQUIRED_FIELD', 'timestamp', 'ts'
                msg = "timestamp is null; the row cannot be assigned to a window"
            elif isinstance(e, CastError):
                cls, msg = 'TYPE_ERROR', str(e)
            elif isinstance(e, ZeroDivisionError):
                cls, msg = 'RUNTIME_ERROR', 'division by zero'
            elif isinstance(e, OverflowError):
                cls, msg = 'RUNTIME_ERROR', f'numeric overflow ({e})'
            else:
                cls, msg = 'RUNTIME_ERROR', f'{type(e).__name__}: {e}'
            if field is not None and typ is None:
                typ = next((t for n, t in fields if n == field), None)
            ctx = {'format': src.label(), 'expected_type': DSL_TYPE[typ] if typ else None,
                   'stage': 'parse' if phase == 0 else 'evaluate'}
            if textual:
                line = rd.line_num - _line_breaks(row)
                idx = None
                ctx['raw'] = {h: row[i] for i, h in reversed(list(enumerate(src.header)))
                              if i < len(row)}
                if len(row) != len(src.header):
                    ctx['field_count'] = len(row)
                    ctx['expected_field_count'] = len(src.header)
            else:
                line = None
                idx = row[-1]
                ctx['raw'] = {fields[j][0]: row[k] for j, k in sorted(pos.items())}
            rec = {'file': src.path, 'line': line, 'error': cls, 'error_type': cls, 'code': cls,
                   'message': msg, 'field': field, 'value': value, 'context': ctx}
            if idx is not None:
                rec['row_index'] = idx
            self.records.append(rec)
            if self.strict:
                self.flush()
                where = f"line {line}" if line is not None else f"row {idx}"
                kind = BAD_KIND[cls]
                if self.legacy:
                    if short:
                        fail('bad_io', f"malformed CSV row at line {line}: too few fields")
                    if cls == 'TYPE_ERROR':
                        kind = 'runtime_error'
                fail(kind, f"{cls}: {src.path} {where}: {msg}")
        return bad

    def add(self, cls, msg, path, line=None, idx=None, field=None, value=None, typ=None,
            stage='parse', fmt=None, raw=None, source=None):
        """Record one bad row found outside the generated row loop (ingest
        mapping/validation, alias pre-stages, join projection)."""
        self.count += 1
        if self.out is None and not self.strict:
            return
        ctx = {'format': fmt, 'expected_type': DSL_TYPE[typ] if typ else None, 'stage': stage}
        if source is not None:
            ctx['source'] = source
        if raw is not None:
            ctx['raw'] = raw
        rec = {'file': path, 'line': line, 'error': cls, 'error_type': cls, 'code': cls,
               'message': msg, 'field': field, 'value': value, 'context': ctx}
        if idx is not None:
            rec['row_index'] = idx
        self.records.append(rec)
        if self.strict:
            self.flush()
            where = f" line {line}" if line is not None else (f" row {idx}" if idx is not None else '')
            fail(BAD_KIND[cls], f"{cls}: {path}{where}: {msg}")

    def flush(self):
        if self.out is None or not self.records:
            return
        import json
        try:
            d = os.path.dirname(self.out)
            if d:
                os.makedirs(d, exist_ok=True)
            with open(self.out, 'w', encoding='utf-8') as f:
                for r in self.records:
                    f.write(json.dumps(r, sort_keys=True, default=_jsonable) + '\n')
        except OSError as e:
            fail('bad_io', f"cannot write bad records '{self.out}': {e.strerror or e}")


# --------------------------------------------------------------------------
# Ingest config: named sources, file assignment, mapping and validation
# --------------------------------------------------------------------------
MAPPING_KEYS = ('drop', 'rename', 'cast', 'defaults')


class IngestSource:
    """One named source of the ingest config (attributes set by
    parse_ingest_config, bind_source_schema and assign_files)."""

    def __init__(self, name, base):
        self.name = name
        self.base = base        # directory of the config file (relative patterns)
        self.files = []


def config_error(msg):
    fail('config_error', msg)


def load_ingest_config(path, opts):
    try:
        with open(path, 'rb') as f:
            data = f.read()
    except OSError as e:
        fail('bad_io', f"cannot read ingest config '{path}': {e.strerror or e}")
    try:
        text = data.decode('utf-8-sig')
    except UnicodeDecodeError as e:
        config_error(f"ingest config '{path}' is not valid UTF-8: {e}")
    yaml = None
    if not path.lower().endswith('.json'):
        try:
            import yaml
        except ImportError:
            yaml = None
    if yaml is None:
        import json
        try:
            cfg = json.loads(text)
        except ValueError as e:
            config_error(f"malformed ingest config '{path}': {e}")
    else:
        try:
            cfg = yaml.safe_load(text)
        except Exception as e:
            config_error(f"malformed ingest config '{path}': {e}")
    return parse_ingest_config(cfg, opts, os.path.dirname(os.path.abspath(path)))


def _str_list(v, what):
    if isinstance(v, str):
        v = [v]
    if not isinstance(v, list) or not all(isinstance(x, str) and x for x in v):
        config_error(f"{what} must be a list of names")
    return list(v)


def _str_map(v, what):
    if not isinstance(v, dict) or not all(isinstance(k, str) and k for k in v):
        config_error(f"{what} must be a mapping of column names")
    return v


def _null_markers(v, what):
    if isinstance(v, str):
        v = v.split(',')
    if not isinstance(v, list):
        config_error(f"{what} must be a list of null markers")
    out = ['']
    for m in v:
        if m is None:       # an unquoted YAML null marker such as NULL or ~
            out += ['null', 'NULL', 'Null', '~']
        elif isinstance(m, bool):
            out.append('true' if m else 'false')
        elif isinstance(m, (str, int, float)):
            out.append(str(m).strip() if isinstance(m, str) else str(m))
        else:
            config_error(f"{what} must be a list of null markers")
    return tuple(dict.fromkeys(out))


def parse_ingest_config(cfg, opts, base):
    """Structural validation -> [IngestSource]."""
    if not isinstance(cfg, dict) or 'sources' not in cfg:
        config_error("ingest config must be a mapping with a 'sources' list")
    srcs = cfg['sources']
    if isinstance(srcs, dict):
        srcs = [dict(v, name=v.get('name', k)) if isinstance(v, dict) else v for k, v in srcs.items()]
    if not isinstance(srcs, list) or not srcs:
        config_error("'sources' must be a non-empty list")
    out = []
    names = set()
    for n, s in enumerate(srcs):
        if not isinstance(s, dict):
            config_error(f"sources[{n}] must be a mapping")
        name = s.get('name')
        if not isinstance(name, str) or not _SIMPLE.match(name):
            config_error(f"sources[{n}]: 'name' must be an identifier")
        if name in names:
            config_error(f"duplicate source name '{name}'")
        names.add(name)
        where = f"source '{name}'"
        src = IngestSource(name, base)
        inputs = s.get('inputs', s.get('input'))
        if isinstance(inputs, str):
            inputs = [inputs]
        if not isinstance(inputs, list) or not inputs or not all(isinstance(x, str) and x for x in inputs):
            config_error(f"{where}: 'inputs' must be a non-empty list of file patterns")
        src.inputs = inputs
        src.recursive = s.get('recursive', opts.recursive)
        if not isinstance(src.recursive, bool):
            config_error(f"{where}: 'recursive' must be true or false")
        fmt = s.get('format', opts.format)
        if not isinstance(fmt, str) or fmt.strip().lower() not in FORMATS:
            config_error(f"{where}: 'format' must be one of {', '.join(FORMATS)}")
        src.format = fmt.strip().lower()
        schema = s.get('schema')
        if schema is not None and (not isinstance(schema, str) or not _SIMPLE.match(schema)):
            config_error(f"{where}: 'schema' must be a schema name")
        src.schema = schema
        prec = s.get('precedence', 0)
        if isinstance(prec, bool) or not isinstance(prec, int):
            config_error(f"{where}: 'precedence' must be an integer")
        src.precedence = prec
        src.tz = None
        if s.get('tz') is not None:
            if not isinstance(s['tz'], str):
                config_error(f"{where}: 'tz' must be an IANA timezone name")
            try:
                src.tz = load_tz(s['tz'].strip())
            except MTLError:
                config_error(f"{where}: unknown timezone '{s['tz']}'")
        nulls = s.get('nulls')
        src.nulls = opts.nulls if nulls is None else _null_markers(nulls, f"{where}: 'nulls'")
        mapping = s.get('mapping')
        if mapping is None:
            mapping = {}
        if not isinstance(mapping, dict):
            config_error(f"{where}: 'mapping' must be a mapping")
        for k in mapping:
            if k not in MAPPING_KEYS:
                config_error(f"{where}: unknown mapping directive '{k}' "
                             f"(expected {', '.join(MAPPING_KEYS)})")
        src.drop = _str_list(mapping.get('drop') or [], f"{where}: mapping.drop")
        rename = _str_map(mapping.get('rename') or {}, f"{where}: mapping.rename")
        targets = set()
        for old, new in rename.items():
            if not isinstance(new, str) or not new:
                config_error(f"{where}: mapping.rename of '{old}' must name a column")
            if new in targets:
                config_error(f"{where}: mapping.rename maps several columns to '{new}'")
            targets.add(new)
        src.rename = dict(rename)
        cast = _str_map(mapping.get('cast') or {}, f"{where}: mapping.cast")
        src.cast = {}
        for col, typ in cast.items():
            t = TYPE_KW.get(typ.strip().lower()) if isinstance(typ, str) else None
            if t is None:
                config_error(f"{where}: cannot cast '{col}' to unknown type {typ!r} "
                             f"(expected string, int, float, bool or timestamp)")
            src.cast[col] = t
        src.defaults = dict(_str_map(mapping.get('defaults') or {}, f"{where}: mapping.defaults"))
        for col, v in src.defaults.items():
            if v is not None and not isinstance(v, (str, int, float, bool, datetime)):
                import datetime as _dt
                if not isinstance(v, _dt.date):
                    config_error(f"{where}: default for '{col}' must be a scalar value")
        req = s.get('required')
        src.required = list(dict.fromkeys(_str_list(req, f"{where}: 'required'"))) if req is not None else []
        out.append(src)
    return out


def default_value(s, col, v, typ, tz, fmt):
    """Convert a configured default to the field's DSL type (config error if it
    cannot be)."""
    if v is None or typ is None:
        return v
    import datetime as _dt
    bad = False
    try:
        if typ == 'str':
            if isinstance(v, bool):
                return 'true' if v else 'false'
            if isinstance(v, datetime):
                return fmt_ts(v) if v.tzinfo is not None else v.isoformat()
            return str(v)
        if typ == 'int':
            if isinstance(v, int) and not isinstance(v, bool):
                return v
            if isinstance(v, str) and _is_int(v):
                return int(v.strip())
            bad = True
        elif typ == 'float':
            if isinstance(v, (int, float)) and not isinstance(v, bool):
                x = float(v)
            elif isinstance(v, str) and _is_float(v):
                x = float(v.strip())
            else:
                x = None
            if x is not None and x - x == 0.0:
                return x
            bad = True
        elif typ == 'bool':
            if isinstance(v, bool):
                return v
            if isinstance(v, str) and v.strip().lower() in ('true', 'false'):
                return v.strip().lower() == 'true'
            bad = True
        else:
            if isinstance(v, _dt.date) and not isinstance(v, datetime):
                v = datetime(v.year, v.month, v.day)
            if isinstance(v, datetime):
                if v.tzinfo is None:
                    v = v.replace(tzinfo=tz)
                return v.astimezone(UTC)
            if isinstance(v, str):
                return make_ts_parser(fmt, tz)(v.strip())
            bad = True
    except (ValueError, OverflowError):
        bad = True
    if bad:
        config_error(f"source '{s.name}': default for '{col}' ({v!r}) is not a valid {DSL_TYPE[typ]}")


def bind_source_schema(s, fields, tz, fmt):
    """Check the mapping against the source's DSL schema."""
    s.fields = fields
    s.phys = [(f[0], f[1]) for f in fields if f[2] is None]
    types = dict(s.phys)
    for col, c in s.cast.items():
        t = types.get(col)
        if t is not None and not (c == t or (c == 'int' and t == 'float')):
            config_error(f"source '{s.name}': cast of '{col}' to {DSL_TYPE[c]} conflicts with "
                         f"its schema type {DSL_TYPE[t]} in '{s.schema}'")
    s.tzinfo = s.tz or tz
    s.dflt = {col: default_value(s, col, v, types.get(col) or s.cast.get(col), s.tzinfo, fmt)
              for col, v in s.defaults.items()}


def assign_files(cfg):
    """Each file goes to the matching source with the lowest precedence number;
    a tie between sources is a config error.  Per-source lists are sorted by
    absolute path."""
    claims = {}
    for s in cfg:
        found, _ = collect_inputs(s.inputs, s.recursive, s.format, base=s.base)
        for key, src in found.items():
            claims.setdefault(key, []).append((s, src))
    for key in sorted(claims):
        lst = claims[key]
        best = min(s.precedence for s, src in lst)
        win = [(s, src) for s, src in lst if s.precedence == best]
        if len(win) > 1:
            config_error(f"file '{win[0][1].path}' matches sources "
                         f"{', '.join(repr(s.name) for s, src in win)} with equal precedence {best}")
        win[0][0].files.append(win[0][1])
    for s in cfg:
        s.files.sort(key=lambda src: os.path.abspath(src.path))


def mapped_columns(header, s):
    """Column name -> header index after the drop and rename directives."""
    cols = {}
    for i, h in enumerate(header):
        if h not in cols:
            cols[h] = i
    for d in s.drop:
        cols.pop(d, None)
    out = {}
    renamed = {}
    for name, i in cols.items():
        if name in s.rename:
            renamed[s.rename[name]] = i
        else:
            out[name] = i
    out.update(renamed)     # an explicitly renamed column wins over a same-named one
    return out


def _natural_type(t):
    """DSL type of an arrow column type, or None."""
    pa, _ = _pq()
    P = pa.types
    if P.is_dictionary(t):
        t = t.value_type
    if P.is_boolean(t):
        return 'bool'
    if P.is_integer(t):
        return 'int'
    if P.is_floating(t) or P.is_decimal(t):
        return 'float'
    if P.is_timestamp(t):
        return 'ts'
    is_view = getattr(P, 'is_string_view', None)
    if P.is_string(t) or P.is_large_string(t) or (is_view is not None and is_view(t)):
        return 'str'
    return None


def load_source(s, fmt, bad):
    """Read every file of a source, apply its mapping (drop, rename, cast,
    defaults), validate against its schema and the required fields -> (rows of
    physical schema values, per-row (file, line, row index, format))."""
    tz = s.tzinfo
    ts_parse = make_ts_parser(fmt, tz)
    _, convert = text_helpers(s.nulls, ts_parse)
    cast = make_cast(ts_parse)
    types = dict(s.phys)
    names = [n for n, t in s.phys]
    names += [n for n in list(s.cast) + s.required if n not in types and n not in names]
    nphys = len(s.phys)
    req = [(names.index(n), n) for n in s.required]
    rows = []
    metas = []
    for src in s.files:
        read_header(src)
        cols = mapped_columns(src.header, s)
        ents = [(n, cols.get(n), types.get(n), s.cast.get(n), s.dflt.get(n)) for n in names]
        label = src.label()

        def reject(cls, msg, line, idx, field=None, value=None, typ=None, raw=None):
            bad.add(cls, msg, src.path, line, idx, field, value, typ, 'parse', label, raw, s.name)

        def required_ok(vals, line, idx, raw=None):
            for k, n in req:
                if vals[k] is None:
                    reject('MISSING_REQUIRED_FIELD', f"required field '{n}' is null", line, idx,
                           n, None, types.get(n), raw)
                    return False
            return True

        if src.kind == 'parquet':
            pa, pq = _pq()
            needed = list(dict.fromkeys(src.header[i] for n, i, t, c, d in ents if i is not None))
            try:
                table = pq.ParquetFile(src.path).read(columns=needed)
                colvals = []
                for n, i, t, c, d in ents:
                    if i is None:
                        colvals.append(None)
                        continue
                    cname = src.header[i]
                    col = table.column(needed.index(cname))
                    if c is None:
                        vals, _ = parquet_values(col, cname, t or _natural_type(col.type) or 'str', tz)
                    else:
                        nat = _natural_type(col.type)
                        vals, _ = parquet_values(col, cname, nat or 'str', tz)
                        if nat is not None and nat != c:
                            conv = []
                            for v in vals:
                                if v is not None and v.__class__ is not BadValue:
                                    try:
                                        v = cast(v, nat, c)
                                    except CastError as e:
                                        cls = 'TIMESTAMP_PARSE_ERROR' if c == 'ts' and nat == 'str' else 'TYPE_ERROR'
                                        v = BadValue(cls, n, v, f"column '{n}': {e}")
                                conv.append(v)
                            vals = conv
                        if c == 'int' and t == 'float':
                            vals = [float(v) if v.__class__ is int else v for v in vals]
                    colvals.append(vals)
                nrows = table.num_rows
            except MTLError:
                raise
            except Exception as e:
                fail('bad_io', f"cannot read Parquet '{src.path}': {e}")
            for r in range(nrows):
                vals = []
                for k, (n, i, t, c, d) in enumerate(ents):
                    cv = colvals[k]
                    v = None if cv is None else cv[r]
                    if v.__class__ is BadValue:
                        reject(v.cls, v.msg, None, r, n, _jsonable(v), t or c)
                        break
                    vals.append(d if v is None else v)
                else:
                    if required_ok(vals, None, r):
                        rows.append(tuple(vals[:nphys]))
                        metas.append((src.path, None, r, label))
            continue

        fh, rd = open_text(src)
        header = src.header
        try:
            with fh:
                next(rd, None)
                for row in rd:
                    if not row:
                        continue
                    vals = []
                    err = None
                    for n, i, t, c, d in ents:
                        if i is None:
                            v = None
                        elif i >= len(row):
                            err = ('MISSING_REQUIRED_FIELD', n, None, t or c,
                                   f"row has {len(row)} field(s) but column '{header[i]}' is field "
                                   f"{i + 1} of {len(header)}")
                            break
                        else:
                            ct = c or t or 'str'
                            try:
                                v = convert(row[i], ct)
                            except (ValueError, OverflowError):
                                err = ('TIMESTAMP_PARSE_ERROR' if ct == 'ts' else 'PARSE_TYPE_MISMATCH',
                                       n, row[i], ct, f"column '{n}' has invalid {_WHAT[ct]} value {row[i]!r}")
                                break
                            if v is not None and c == 'int' and t == 'float':
                                v = float(v)
                        vals.append(d if v is None else v)
                    line = rd.line_num - _line_breaks(row)
                    if err is not None:
                        raw = {h: row[k] for k, h in reversed(list(enumerate(header))) if k < len(row)}
                        reject(err[0], err[4], line, None, err[1], err[2], err[3], raw)
                        continue
                    if req and not required_ok(vals, line, None):
                        continue
                    rows.append(tuple(vals[:nphys]))
                    metas.append((src.path, line, None, label))
        except MTLError:
            raise
        except _csv.Error as e:
            fail('bad_io', f"malformed input '{src.path}' at line {rd.line_num}: {e}")
        except READ_ERRORS as e:
            fail('bad_io', f"cannot read '{src.path}': {e}")
    return rows, metas


def classify_eval(e):
    """Bad-record class and message of an exception raised while evaluating a row."""
    if isinstance(e, (MTLError, MemoryError, RecursionError)):
        raise e
    if isinstance(e, CastError):
        return 'TYPE_ERROR', str(e)
    if isinstance(e, ZeroDivisionError):
        return 'RUNTIME_ERROR', 'division by zero'
    if isinstance(e, OverflowError):
        return 'RUNTIME_ERROR', f'numeric overflow ({e})'
    return 'RUNTIME_ERROR', f'{type(e).__name__}: {e}'


def _unpack(prefix, n, var):
    if n == 0:
        return 'pass'
    return ', '.join(f'{prefix}{i}' for i in range(n)) + f', = {var}'


def _exec_fns(lines, comp, ts_parse):
    ns = helper_ns()
    ns['_cast'] = make_cast(ts_parse)
    ns.update(comp.consts)
    exec(compile('\n'.join(lines) + '\n', '<mtl-join>', 'exec'), ns)
    return ns


# --------------------------------------------------------------------------
# Alias pre-stages and joins
# --------------------------------------------------------------------------
def compile_alias(alias, s, bodies, params, fmt):
    """Schema calcs, then the alias's with-block calcs, then its filters ->
    (columns [(name, type)], run(rows, metas, bad) -> rows)."""
    ts_parse = make_ts_parser(fmt, s.tzinfo)
    comp = Compiler(s.phys, s.tzinfo, fmt)
    comp.params = params
    compile_schema(comp, s.fields)
    names = [f[0] for f in s.fields]
    calcs = [b for body in bodies for b in body if b[0] == 'calc']
    filters = [b for body in bodies for b in body if b[0] == 'filter']
    seen = set(names)
    for c in calcs:
        if c[1] in seen:
            what = 'schema field' if c[1] in names else 'calc'
            fail('bad_dsl', f"line {c[5][2]}: calc '{c[1]}' in with {alias} collides with {what} '{c[1]}'")
        seen.add(c[1])
    for n in names:
        comp.env[f'{alias}.{n}'] = comp.env[n]
    later = {c[1] for c in calcs}
    for c in calcs:
        for n in later:
            msg = f"calc references '{n}' before it is defined"
            comp.blocked.setdefault(n, msg)
            comp.blocked.setdefault(f'{alias}.{n}', msg)
        later.discard(c[1])
        comp.calc(c[1], c[2], c[3])
        comp.env[f'{alias}.{c[1]}'] = comp.env[c[1]]
    comp.blocked = {}
    for f in filters:
        comp.statement(f)
    out = names + [c[1] for c in calcs]
    cols = [(n, comp.env[n][1]) for n in out]
    codes = [comp.col(n)[0] for n in out]
    src = ['def _run(rows, _out, _bad):',
           '    for _n, row in enumerate(rows):',
           '        ' + _unpack('c', len(s.phys), 'row'),
           '        try:']
    src += ['            ' + ln for ln in (comp.lines or ['pass'])]
    src += ['        except Exception as _e:',
            '            _bad(_e, _n)',
            '            continue',
            '        _out((' + ''.join(c + ', ' for c in codes) + '))']
    fn = _exec_fns(src, comp, ts_parse)['_run']

    def run(rows, metas, bad):
        out = []

        def on_bad(e, n):
            cls, msg = classify_eval(e)
            path, line, idx, label = metas[n]
            bad.add(cls, msg, path, line, idx, stage='evaluate', fmt=label, source=s.name)

        fn(rows, out.append, on_bad)
        return out

    return cols, run


def _conjuncts(n, out):
    if n[0] == 'and':
        _conjuncts(n[1], out)
        _conjuncts(n[2], out)
    else:
        out.append(n)
    return out


class JoinPlan:
    """A type-checked join: on/key/projection functions and output columns."""


def compile_join(j, lcols, rcols, final, params, tz, fmt):
    lq, rq, line = j['lq'], j['rq'], j['tok'][2]
    ts_parse = make_ts_parser(fmt, tz)
    comp = Compiler([], tz, fmt)
    comp.params = params
    li = {n: i for i, (n, t) in enumerate(lcols)}
    ri = {n: i for i, (n, t) in enumerate(rcols)}
    for i, (n, t) in enumerate(lcols):
        if lq is not None:
            comp.env[f'{lq}.{n}'] = ('var', t, f'l{i}')
    for i, (n, t) in enumerate(rcols):
        if rq is not None:
            comp.env[f'{rq}.{n}'] = ('var', t, f'r{i}')
    for n in list(li) + [n for n in ri if n not in li]:
        if n in li and n in ri:
            comp.blocked[n] = (f"line {line}: column '{n}' exists on both sides of the join; "
                               f"qualify it as {lq or '<left>'}.{n} or {rq or '<right>'}.{n}")
        elif n in li:
            comp.env[n] = ('var', lcols[li[n]][1], f'l{li[n]}')
        else:
            comp.env[n] = ('var', rcols[ri[n]][1], f'r{ri[n]}')
    plan = JoinPlan()
    plan.type = j['type']
    plan.within = None
    if j['within'] is not None:
        a, b = li.get('timestamp'), ri.get('timestamp')
        if a is None or b is None or lcols[a][1] != 'ts' or rcols[b][1] != 'ts':
            fail('bad_dsl', f"line {line}: within requires a timestamp column on both sides of the join")
        plan.within = timedelta(seconds=j['within'])
        plan.lt, plan.rt = a, b
    oc, ot = comp.cond(j['on'])
    if ot != 'bool':
        fail('type_error', f"line {line}: join condition must be boolean, got {tname(ot)}")

    def side(e):
        out = set()
        for r in node_refs(e, []):
            q, dot, n = r.partition('.')
            if dot:
                out.add('l' if q == lq and n in li else 'r' if q == rq and n in ri else '?')
            else:
                out.add('l' if r in li and r not in ri else 'r' if r in ri and r not in li else '?')
        return out

    keys = []
    for c in _conjuncts(j['on'], []):
        if c[0] == 'cmp' and c[1] == '==':
            sa, sb = side(c[2]), side(c[3])
            if sa == {'l'} and sb == {'r'}:
                keys.append((c[2], c[3]))
            elif sa == {'r'} and sb == {'l'}:
                keys.append((c[3], c[2]))
    pcols = []
    pcodes = []
    for e, name, t in j['proj']:
        c, ty = comp.gen(e)
        pcols.append((name, ty))
        pcodes.append(c)
    names = {n for n, t in pcols}
    if 'timestamp' not in names:
        lt = 'timestamp' in li and lcols[li['timestamp']][1] == 'ts'
        rt = 'timestamp' in ri and rcols[ri['timestamp']][1] == 'ts'
        if lt and rt and final:
            fail('type_error', f"line {line}: ambiguous timestamp: both sides of the join have a "
                               f"timestamp; project one of them as timestamp")
        if lt:
            pcols.append(('timestamp', 'ts'))
            pcodes.append(f"l{li['timestamp']}")
        elif rt:
            pcols.append(('timestamp', 'ts'))
            pcodes.append(f"r{ri['timestamp']}")
        elif final:
            fail('type_error', f"line {line}: no timestamp after project; project a timestamp "
                               f"column as timestamp")
    elif final:
        ty = dict(pcols)['timestamp']
        if ty != 'ts':
            fail('type_error', f"line {line}: projected timestamp must be a timestamp, got {tname(ty)}")
    nl, nr = len(lcols), len(rcols)
    lnone = (' = '.join(f'l{i}' for i in range(nl)) + ' = None') if nl else 'pass'
    rnone = (' = '.join(f'r{i}' for i in range(nr)) + ' = None') if nr else 'pass'
    src = ['def _on(L, R):', '    ' + _unpack('l', nl, 'L'), '    ' + _unpack('r', nr, 'R'),
           f'    return {oc}',
           'def _proj(L, R):',
           '    if L is None:', '        ' + lnone, '    else:', '        ' + _unpack('l', nl, 'L'),
           '    if R is None:', '        ' + rnone, '    else:', '        ' + _unpack('r', nr, 'R'),
           '    return (' + ''.join(c + ', ' for c in pcodes) + ')']
    if keys:
        lk = [comp.gen(a)[0] for a, b in keys]
        rk = [comp.gen(b)[0] for a, b in keys]
        src += ['def _lk(L):', '    ' + _unpack('l', nl, 'L'),
                '    return (' + ''.join(c + ', ' for c in lk) + ')',
                'def _rk(R):', '    ' + _unpack('r', nr, 'R'),
                '    return (' + ''.join(c + ', ' for c in rk) + ')']
    ns = _exec_fns(src, comp, ts_parse)
    plan.on, plan.proj = ns['_on'], ns['_proj']
    plan.lk, plan.rk = (ns['_lk'], ns['_rk']) if keys else (None, None)
    plan.cols = pcols
    return plan


def _join_key(fn, row):
    try:
        k = fn(row)
    except Exception:
        return None
    for v in k:
        if v is None:
            return None
    return k


def run_join(plan, L, R, bad):
    """Rows of L join R (pairs where `on` is true and, with within, the
    timestamps are close enough); outer joins pad the other side with nulls."""
    keep_l = plan.type in ('left', 'full')
    keep_r = plan.type in ('right', 'full')
    hit_r = bytearray(len(R))
    on, proj, within = plan.on, plan.proj, plan.within
    out = []

    def emit(l, r):
        try:
            out.append(proj(l, r))
        except Exception as e:
            cls, msg = classify_eval(e)
            bad.add(cls, msg, '<join>', stage='join')

    index = None
    if plan.lk is not None:
        index = {}
        for j, r in enumerate(R):
            k = _join_key(plan.rk, r)
            if k is not None:
                index.setdefault(k, []).append(j)
    every = range(len(R))
    for l in L:
        if index is not None:
            k = _join_key(plan.lk, l)
            cands = () if k is None else index.get(k, ())
        else:
            cands = every
        matched = False
        for j in cands:
            r = R[j]
            if within is not None:
                a, b = l[plan.lt], r[plan.rt]
                if a is None or b is None or abs(a - b) > within:
                    continue
            try:
                ok = on(l, r)
            except Exception:
                ok = None   # a failing cast in the condition is a non-match
            if ok:
                matched = True
                hit_r[j] = 1
                emit(l, r)
        if keep_l and not matched:
            emit(l, None)
    if keep_r:
        for j, r in enumerate(R):
            if not hit_r[j]:
                emit(None, r)
    return out


def execute_ingest(prog, cfg, flat, params, window, opts, tz, bad):
    """Multi-source run: config checks, static compilation of alias stages,
    joins and the pipeline, then ingestion, joins and aggregation."""
    fmt = opts.timestamp_format
    by_name = {s.name: s for s in cfg}
    for s in cfg:
        if s.schema is None:
            if prog.using is None:
                config_error(f"source '{s.name}' does not name a schema")
            s.schema = prog.using
        if s.schema not in flat:
            config_error(f"source '{s.name}' uses schema '{s.schema}', which is not defined in the DSL")
        bind_source_schema(s, flat[s.schema], tz, fmt)
    if prog.sources is not None:
        for name, alias, tok in prog.sources:
            if name not in by_name:
                config_error(f"line {tok[2]}: unknown source '{name}' (not declared in the ingest config)")
        bound = [(alias, by_name[name]) for name, alias, tok in prog.sources]
    elif len(cfg) == 1:
        bound = [(cfg[0].name, cfg[0])]
    else:
        fail('bad_dsl', f"the ingest config declares {len(cfg)} sources; bind them with "
                        f"sources {{ ... }} and combine them with join")
    assign_files(cfg)

    # static: alias stages, joins, pipeline
    bodies = {}
    for alias, body, tok in prog.withs:
        bodies.setdefault(alias, []).append(body)
    stages = {alias: compile_alias(alias, s, bodies.get(alias, []), params, fmt) for alias, s in bound}
    plans = []

    def cols_of(ref):
        return stages[ref[1]][0] if ref[0] == 'alias' else plans[ref[1]].cols

    for ji, j in enumerate(prog.joins):
        plans.append(compile_join(j, cols_of(j['left']), cols_of(j['right']),
                                  ji == len(prog.joins) - 1, params, tz, fmt))
    final_cols = plans[-1].cols if plans else stages[bound[0][0]][0]
    names = {n for n, t in final_cols}
    for c in prog.pre:
        if c[1] in names:
            fail('bad_dsl', f"line {c[5][2]}: calc '{c[1]}' collides with column '{c[1]}'")
    comp = Compiler(final_cols, tz, fmt)
    comp.params = params
    ts_parse = make_ts_parser(fmt, tz)
    pipe = compile_pipeline(prog, comp, params, window, tz, fmt, ts_parse, opts.nulls, bad, 0)

    # data
    loaded = {}
    rels = {}
    for alias, s in bound:
        if s.name not in loaded:
            loaded[s.name] = load_source(s, fmt, bad)
        rows, metas = loaded[s.name]
        rels[alias] = stages[alias][1](rows, metas, bad)
    results = []

    def rel_of(ref):
        return rels[ref[1]] if ref[0] == 'alias' else results[ref[1]]

    for ji, j in enumerate(prog.joins):
        results.append(run_join(plans[ji], rel_of(j['left']), rel_of(j['right']), bad))
    final = results[-1] if results else rels[bound[0][0]]
    label = '<join>' if results else f'<{bound[0][1].name}>'
    pipe.feed_rows([r + (i,) for i, r in enumerate(final)], Source(label, 'join' if results else 'source', False))
    return pipe.finish()


# --------------------------------------------------------------------------
# Main execution
# --------------------------------------------------------------------------
_RUN_ARGS = ['_float', '_int', '_len', '_A', '_fiso', '_strp', '_FMT', '_UTC', '_TZ', '_r0',
             '_rd', '_rdi', '_NL', '_nullor', '_nonfin', '_tsslow', '_PB', '_NoTs', '_cast',
             '_shift']


def execute(dsl_src, opts, tz):
    fmt = opts.timestamp_format
    legacy = opts.legacy
    strict = opts.strict or legacy
    prog = parse_dsl(dsl_src)
    if opts.ingest_config is None:
        if prog.sources is not None:
            fail('config_error', '--ingest-config is required: the pipeline declares sources { ... }')
        if not opts.inputs:
            fail('bad_io', 'invalid arguments: --input (or --ingest-config) is required')
        cfg = None
    else:
        cfg = load_ingest_config(opts.ingest_config, opts)

    fields = None
    flat = {}
    if prog.schemas is not None:
        flat, bad_overrides = flatten_schemas(prog.schemas)
        if prog.using is not None:
            if prog.using not in flat:
                fail('bad_dsl', f"pipeline uses unknown schema '{prog.using}'")
        if prog.using is not None and cfg is None:
            fields = flat[prog.using]
            names = {f[0] for f in fields}
            for c in prog.pre:
                if c[1] in names:
                    fail('bad_dsl', f"line {c[5][2]}: calc '{c[1]}' collides with schema field '{c[1]}'")
    params = resolve_params(prog, opts.params, tz, fmt)
    window = resolve_window(prog.window, params)
    if prog.schemas is not None:
        if bad_overrides:
            fail('type_error', bad_overrides[0])
        for sfields in flat.values():
            chk = Compiler([(f[0], f[1]) for f in sfields if f[2] is None], tz, fmt)
            chk.params = params
            compile_schema(chk, sfields)

    bad = BadRecords(opts.bad_records_out, strict, legacy)
    if cfg is not None:
        return execute_ingest(prog, cfg, flat, params, window, opts, tz, bad)

    sources = resolve_inputs(opts.inputs, opts.recursive, opts.format)
    for src in sources:
        read_header(src)
    ts_parse = make_ts_parser(fmt, tz)

    def legacy_missing(required):
        for src in sources:
            missing = [c for c in required if c not in src.hidx]
            if missing:
                fail('bad_io', f"CSV is missing required column(s): {', '.join(missing)}")

    if fields is not None:
        phys = [(f[0], f[1]) for f in fields if f[2] is None]
        if legacy:
            legacy_missing(list(REQUIRED) + [n for n, t in phys if n not in REQUIRED])
        comp = Compiler(phys, tz, fmt)
        comp.params = params
        compile_schema(comp, fields)
    else:
        if legacy:
            legacy_missing(list(REQUIRED))
        union = set(REQUIRED)
        for src in sources:
            union.update(src.hidx)
        for c in prog.pre:
            if c[1] in union:
                fail('bad_dsl', f"line {c[5][2]}: calc '{c[1]}' collides with CSV column '{c[1]}'")
        extra = sorted(h for h in union if h not in REQUIRED and h in prog.idents)
        types = dict(REQUIRED)
        if extra:
            types.update(infer_types(sources, extra, opts.nulls, ts_parse))
        comp = Compiler([(n, types[n]) for n in list(REQUIRED) + extra], tz, fmt)
        comp.params = params

    total = 0
    for src in sources:
        try:
            total += os.path.getsize(src.path)
        except OSError:
            pass
    pipe = compile_pipeline(prog, comp, params, window, tz, fmt, ts_parse, opts.nulls, bad, total)

    # strict: fields the pipeline references must exist in every input
    if strict and not legacy:
        for src in sources:
            for name, t in comp.fields:
                if name in comp.refs and name not in src.hidx:
                    fail('type_error', f"input '{src.path}' has no column '{name}'")

    for src in sources:
        pipe.feed(src)
    return pipe.finish()


def compile_pipeline(prog, comp, params, window, tz, fmt, ts_parse, nulls, bad, total):
    """Compile pre calcs, row statements, grouping and aggregation over the
    physical fields bound in comp -> object with feed(src), feed_rows(rows, src)
    and finish() -> JSON text."""
    rows_stmts, group, aggs = prog.rows, prog.group, prog.aggs
    # pre-stage calcs run before every filter/apply statement
    aliases = {a[2] for a in aggs}
    later = {c[1] for c in prog.pre}
    for c in prog.post:
        comp.blocked[c[1]] = f"pre-stage calc cannot reference post_agg calc '{c[1]}'"
    for a in aliases:
        comp.blocked[a] = f"pre-stage calc cannot reference aggregate alias '{a}'"
    for c in prog.pre:
        for n in later:
            comp.blocked.setdefault(n, f"calc references '{n}' before it is defined")
        later.discard(c[1])
        comp.calc(c[1], c[2], c[3])
    comp.blocked = {}
    for s in rows_stmts:
        comp.statement(s)

    # grouping key
    key_parts = []
    if window is not None:
        tv, tt = comp.col('timestamp')
        if tt != 'ts':
            fail('type_error', f"window requires 'timestamp' to be a timestamp, got {tname(tt)}")
        if tv not in comp.nonnull:
            comp.lines.append(f'if {tv} is None: raise _NoTs')
        key_parts.append(f'{tv}.timestamp() // {window}')
    gtypes = []
    for g in group:
        gv, gt = comp.col(g)
        key_parts.append(gv)
        gtypes.append(gt)

    # aggregates -> per-column slots: 'buf' (non-null values) or 'cnt' (count only)
    cols = {}       # var -> [type, fns]
    agg_refs = []   # (alias, fn, var|None)
    atypes = {}     # alias -> result type (for post_agg calcs)
    for fn, col, alias in aggs:
        if col == '*':
            if fn != 'count':
                fail('type_error', f"{fn}(*) is not allowed; only count(*) accepts '*'")
            agg_refs.append((alias, fn, None))
            atypes[alias] = 'int'
            continue
        v, t = comp.col(col)
        if fn != 'count' and t not in NUMERIC:
            fail('type_error', f"{fn}({col}) requires a numeric column, got {tname(t)}")
        atypes[alias] = 'int' if fn == 'count' else (t if fn in ('sum', 'min', 'max') else 'float')
        cols.setdefault(v, [t, set()])[1].add(fn)
        agg_refs.append((alias, fn, v))
    slots = []      # (j, var, kind, isf, fns)
    slot_of = {}
    for v, (t, fns) in cols.items():
        j = len(slots) + 1
        slot_of[v] = j
        slots.append((j, v, 'cnt' if fns == {'count'} else 'buf', t == 'float', fns))
    items = []      # (alias, fn, j, kind)
    for alias, fn, v in agg_refs:
        if v is None:
            items.append((alias, fn, None, 'rows'))
        else:
            j = slot_of[v]
            if fn == 'count':
                items.append((alias, fn, j, 'cnt' if slots[j - 1][2] == 'cnt' else 'bufn'))
            else:
                items.append((alias, fn, j, 'stat'))
    fold_specs = [(j, bool(fns & {'std', 'var'})) for j, v, kind, isf, fns in slots
                  if kind == 'buf' and not isf and 'median' not in fns]

    post = compile_post(prog, params, tz, fmt, ts_parse, window, group, gtypes,
                        atypes) if prog.post else ()

    # ---- generate the row loop (one compiled variant per input layout) ----
    use_array = total >= SMALL_INPUT and any(s[2] == 'buf' and s[3] for s in slots)
    if use_array:
        from array import array
    else:
        array = None
    grouped = bool(key_parts)
    new_bucket = '[0' + ''.join(
        ', 0' if kind == 'cnt' else (", _A('d')" if isf and use_array else ', []')
        for j, v, kind, isf, fns in slots) + ']'
    body = list(comp.lines)
    tail = []
    if grouped:
        body.append('k = ' + (key_parts[0] if len(key_parts) == 1
                              else '(' + ', '.join(key_parts) + ',)'))
        tail += ['st = _gg(k)', 'if st is None:', f'    st = G[k] = {new_bucket}', 'st[0] += 1']
        for j, v, kind, isf, fns in slots:
            op = f'st[{j}] += 1' if kind == 'cnt' else f'st[{j}].append({v})'
            tail.append(op if v in comp.nonnull else f'if {v} is not None: {op}')
    else:
        tail.append('_c += 1')
        for j, v, kind, isf, fns in slots:
            op = f'st[{j}] += 1' if kind == 'cnt' else f'_ap{j}({v})'
            tail.append(op if v in comp.nonnull else f'if {v} is not None: {op}')
    used = sorted(comp.used)
    helpers, convert = text_helpers(nulls, ts_parse)
    ns = {
        '_float': float, '_int': int, '_len': len, '_A': array, '_fiso': _fromiso,
        '_strp': datetime.strptime, '_FMT': fmt, '_UTC': UTC, '_TZ': tz, '_PB': BadValue,
        '_NoTs': NullTimestamp, '_cast': make_cast(ts_parse),
    }
    ns.update(helper_ns())
    ns.update(helpers)
    ns.update(comp.consts)
    runners = {}

    def runner(prologue, textual):
        cache_key = (tuple(prologue), textual)
        fn = runners.get(cache_key)
        if fn is not None:
            return fn
        src = ['def _run(rows, G, _bad, ' + ', '.join(f'{n}={n}' for n in
               _RUN_ARGS + list(comp.consts)) + '):']
        src.append('    _c = 0')
        if grouped:
            src.append('    _gg = G.get')
        else:
            src.append('    st = G.get(None)')
            src.append(f'    if st is None: st = G[None] = {new_bucket}')
            for j, v, kind, isf, fns in slots:
                if kind == 'buf':
                    src.append(f'    _ap{j} = st[{j}].append')
        src.append('    for row in rows:')
        if textual:
            src.append('        if not row: continue')
        src.append('        try:')
        src.extend('            ' + ln for ln in (prologue or ['pass']))
        src.append('        except Exception as _e:')
        src.append('            _bad(0, _e, row)')
        src.append('            continue')
        src.append('        try:')
        src.extend('            ' + ln for ln in (body or ['pass']))
        src.append('        except Exception as _e:')
        src.append('            _bad(1, _e, row)')
        src.append('            continue')
        src.extend('        ' + ln for ln in tail)
        if not grouped:
            src.append('    st[0] += _c')
        g = dict(ns)
        exec(compile('\n'.join(src) + '\n', '<mtl-pipeline>', 'exec'), g)
        fn = runners[cache_key] = g['_run']
        return fn

    from itertools import islice
    G = {}
    F = {}
    fold = make_fold(F, fold_specs) if fold_specs else None
    if not grouped:
        runner([], False)([], G, None)     # the global bucket exists even with no rows

    def feed_rows(rows, src):
        """In-memory rows: tuples of every physical field ending with the row index."""
        pos = {j: j for j in used}
        run = runner(parquet_prologue(used, pos, dict.fromkeys(used, False)), False)
        hand = bad.handler(src, comp.fields, used, pos=pos)
        try:
            if fold is None:
                run(rows, G, hand)
            else:
                for off in range(0, len(rows), FOLD_CHUNK):
                    run(rows[off:off + FOLD_CHUNK], G, hand)
                    fold(G)
        except MTLError:
            raise
        except Exception as e:
            fail('runtime_error', f"{src.path}: {type(e).__name__}: {e}")

    def feed(src):
        if src.kind == 'parquet':
            rows, pos, badcols = load_parquet(src, comp.fields, used, tz)
            run = runner(parquet_prologue(used, pos, badcols), False)
            hand = bad.handler(src, comp.fields, used, pos=pos)
            try:
                if fold is None:
                    run(rows, G, hand)
                else:
                    for off in range(0, len(rows), FOLD_CHUNK):
                        run(rows[off:off + FOLD_CHUNK], G, hand)
                        fold(G)
            except MTLError:
                raise
            except Exception as e:
                fail('runtime_error', f"{src.path}: {type(e).__name__}: {e}")
            return
        run = runner(text_prologue(comp.fields, used, src.hidx, tz, fmt), True)
        fh, rd = open_text(src)
        hand = bad.handler(src, comp.fields, used, rd=rd, convert=convert)
        try:
            with fh:
                next(rd, None)
                if fold is None:
                    run(rd, G, hand)
                else:
                    chunk = FOLD_CHUNK
                    while True:
                        ln = rd.line_num
                        run(islice(rd, chunk), G, hand)
                        if rd.line_num == ln:
                            break
                        fold(G)
                        if 4 * len(G) > chunk:
                            chunk = 4 * len(G)
        except MTLError:
            raise
        except _csv.Error as e:
            fail('bad_io', f"malformed input '{src.path}' at line {rd.line_num}: {e}")
        except READ_ERRORS as e:
            fail('bad_io', f"cannot read '{src.path}': {e}")
        except Exception as e:
            fail('runtime_error', f"{src.path}: line {rd.line_num}: {type(e).__name__}: {e}")

    def finish():
        bad.flush()
        try:
            return build_output(G, F, items, slots, window, group, gtypes, post)
        except (ValueError, OverflowError, ZeroDivisionError) as e:
            fail('runtime_error', f"aggregate produced a non-finite value ({e})")

    from types import SimpleNamespace
    return SimpleNamespace(feed=feed, feed_rows=feed_rows, finish=finish, refs=comp.refs)


def compile_post(prog, params, tz, fmt, ts_parse, window, group, gtypes, atypes):
    """Type check post_agg calcs -> [(name, type, fn(R, i))]."""
    pc = Compiler([], tz, fmt, post=True)
    pc.params = params
    if window is not None:
        for k in WINDOW_KEYS:
            pc.env[k] = ('post', 'ts', k)
    for g, t in zip(group, gtypes):
        pc.env[g] = ('post', t, g)
    for a, t in atypes.items():
        pc.env[a] = ('post', t, a)
    pending = {c[1] for c in prog.post}
    codes = []
    for c in prog.post:
        name, e, typ = c[1], c[2], c[3]
        pc.blocked = {n: f"calc '{name}' references post_agg calc '{n}' before it is defined"
                      for n in pending}
        codes.append((name, typ, pc.typed(name, e, typ)))
        pending.discard(name)
        pc.env[name] = ('post', typ, name)
    ns = helper_ns()
    ns['_cast'] = make_cast(ts_parse)
    ns.update(pc.consts)
    return [(name, typ, eval('lambda _R, _i: ' + code, ns)) for name, typ, code in codes]


def _json_value(v, _str=json_str, _frepr=float.__repr__):
    t = type(v)
    if t is float:
        if v - v != 0.0:
            fail('runtime_error', 'result contains a non-finite number')
        return _frepr(v)
    if t is str:
        return _str(v)
    if v is None:
        return 'null'
    if v is True:
        return 'true'
    if v is False:
        return 'false'
    return repr(v)


def _null_key(kt):
    # nulls sort after every value of a group column
    return tuple((v is None, v) for v in kt)


def build_output(G, F, items, slots, window, group, gtypes, post=()):
    """Materialise sorted result rows, evaluate post_agg calcs in order and
    serialise to a JSON string (same layout as json.dumps)."""
    order = sorted(range(len(items)), key=lambda i: items[i][0])
    names = [items[i][0] for i in order]
    picks = [(items[i][3], items[i][2], STAT_INDEX.get(items[i][1])) for i in order]
    needed = {}
    for alias, fn, j, kind in items:
        if kind == 'stat':
            needed.setdefault(j, set()).add(fn)
    cols = []   # (j, isf, need_mm, need_sum, need_var, need_med)
    for j, v, kind, isf, fns in slots:
        if kind == 'buf':
            fns = needed.get(j, set())
            cols.append((j, isf, bool(fns & {'min', 'max'}),
                         bool(fns & {'sum', 'average', 'std', 'var'}),
                         bool(fns & {'std', 'var'}), 'median' in fns))
    Fget = F.get

    def agg_values(key, st):
        stats = {}
        for j, isf, mm, sm, vr, md in cols:
            buf = st[j]
            f = Fget((key, j))
            n = len(buf) + (f[4] if f is not None else 0)
            stats[j] = (n, column_stats(buf, f, isf, mm, sm, vr, md, n) if n else None)
        out = []
        for kind, j, si in picks:
            if kind == 'rows':
                out.append(st[0])
            elif kind == 'cnt':
                out.append(st[j])
            else:
                n, s = stats[j]
                out.append(n if kind == 'bufn' else (s[si] if n else None))
        return out

    single = len(group) + (window is not None) == 1
    R = []
    if window is None and not group:
        R.append(dict(zip(names, agg_values(None, G[None]))))
    else:
        for key in sorted(G, key=(lambda k: _null_key((k,))) if single else _null_key):
            st = G.pop(key)
            kt = (key,) if single else key
            r = {}
            if window is not None:
                start = EPOCH + timedelta(seconds=int(kt[0]) * window)
                r['window_start'] = start
                r['window_end'] = start + timedelta(seconds=window)
                kt = kt[1:]
            r.update(zip(group, kt))
            r.update(zip(names, agg_values(key, st)))
            R.append(r)
    name = None
    try:
        for name, typ, fn in post:
            to_float = typ == 'float'
            for i in range(len(R)):
                v = fn(R, i)
                if to_float and v is not None:
                    v = float(v)
                R[i][name] = v
    except ZeroDivisionError:
        fail('runtime_error', f"division by zero in post_agg calc '{name}'")
    except OverflowError as e:
        fail('runtime_error', f"numeric overflow in post_agg calc '{name}' ({e})")
    except (CastError, ValueError, TypeError) as e:
        fail('runtime_error', f"post_agg calc '{name}': {e}")
    keys = list(WINDOW_KEYS) if window is not None else []
    tskeys = set(keys)
    keys += group
    tskeys.update(g for g, t in zip(group, gtypes) if t == 'ts')
    keys += names
    keys += sorted(p[0] for p in post)
    tskeys.update(p[0] for p in post if p[1] == 'ts')
    pre = [(json_str(k) + ': ', k, k in tskeys) for k in keys]
    jv = _json_value
    out = []
    for r in R:
        parts = []
        for p, k, is_ts in pre:
            v = r[k]
            parts.append(p + ('"' + fmt_ts(v) + '"' if is_ts and v is not None else jv(v)))
        out.append('{' + ', '.join(parts) + '}')
    if window is None and not group:
        return out[0]
    return '[' + ', '.join(out) + ']'


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------
USAGE = ('usage: mtl.py (--input <path-or-glob> [--input <path-or-glob> ...] | --ingest-config <path>) '
         '--dsl <path-or-> [--out <path-or-stdout>] [--tz <IANA>] [--timestamp-format <str>] [--strict] '
         '[--param key=value ...] [--recursive] [--format <csv|tsv|parquet|auto>] '
         '[--nulls "<comma-separated-markers>"] [--bad-records-out <path>]')
OPTIONS = {'--input': 'input', '--csv': 'csv', '--dsl': 'dsl', '--out': 'out', '--tz': 'tz',
           '--timestamp-format': 'timestamp_format', '--param': 'param', '--format': 'format',
           '--nulls': 'nulls', '--bad-records-out': 'bad_records_out',
           '--ingest-config': 'ingest_config'}
MULTI = ('input', 'param')     # accept several values after one flag (shell-expanded globs)


class Args:
    dsl = out = timestamp_format = bad_records_out = ingest_config = None
    tz = 'UTC'
    format = 'auto'
    strict = recursive = legacy = False
    nulls = DEFAULT_NULLS


def parse_args(argv):
    args = Args()
    args.params = {}
    args.inputs = []
    i = 0
    n = len(argv)
    while i < n:
        a = argv[i]
        if a in ('-h', '--help'):
            sys.stdout.write(USAGE + '\n')
            sys.exit(0)
        if a == '--strict' or a == '--recursive':
            setattr(args, a[2:], True)
            i += 1
            continue
        name, eq, val = a.partition('=')
        dest = OPTIONS.get(name)
        if dest is None:
            fail('bad_io', f"invalid arguments: unrecognized argument {a!r}")
        if not eq:
            i += 1
            if i >= n:
                fail('bad_io', f"invalid arguments: {name} expects a value")
            val = argv[i]
        vals = [val]
        if dest in MULTI:
            while i + 1 < n and not argv[i + 1].startswith('--'):
                i += 1
                vals.append(argv[i])
        for val in vals:
            if dest == 'param':
                key, eq, pval = val.partition('=')
                key = key.strip()
                if not eq or not key:
                    fail('bad_io', f"invalid arguments: --param expects key=value, got {val!r}")
                args.params[key] = pval
            elif dest == 'input' or dest == 'csv':
                if dest == 'csv':
                    args.legacy = True      # Part 1-2 interface: fail-fast semantics
                args.inputs.append(val)
            elif dest == 'format':
                low = val.strip().lower()
                if low not in FORMATS:
                    fail('bad_io', f"invalid arguments: --format must be one of "
                                   f"{', '.join(FORMATS)}, got {val!r}")
                args.format = low
            elif dest == 'nulls':
                args.nulls = tuple(dict.fromkeys([''] + [m.strip() for m in val.split(',')]))
            else:
                setattr(args, dest, val)
        i += 1
    if args.dsl is None:
        fail('bad_io', 'invalid arguments: --dsl is required')
    return args


def load_tz(name):
    if name in ('UTC', 'utc', 'Z', 'Etc/UTC', 'Etc/Universal', 'Universal', 'Zulu', 'Etc/Zulu'):
        return UTC
    try:
        from zoneinfo import ZoneInfo
        return ZoneInfo(name)
    except Exception:
        fail('bad_io', f"unknown timezone '{name}'")


def read_dsl(path):
    try:
        if path == '-':
            data = sys.stdin.buffer.read()
        else:
            with open(path, 'rb') as f:
                data = f.read()
        return data.decode('utf-8-sig')
    except OSError as e:
        fail('bad_io', f"cannot read DSL '{path}': {e.strerror or e}")
    except UnicodeDecodeError as e:
        fail('bad_io', f"cannot decode DSL '{path}': {e}")


def main(argv=None):
    try:
        args = parse_args(sys.argv[1:] if argv is None else argv)
        tz = load_tz(args.tz)
        src = read_dsl(args.dsl)
        result = execute(src, args, tz)
        data = result + '\n'
        out = args.out
        try:
            if out is None or out == '-':
                sys.stdout.buffer.write(data.encode('utf-8'))
                sys.stdout.flush()
            else:
                with open(out, 'w', encoding='utf-8') as f:
                    f.write(data)
        except OSError as e:
            fail('bad_io', f"cannot write output '{out}': {e.strerror or e}")
    except MTLError as e:
        msg = ' '.join(str(e.msg).split())
        sys.stderr.write(f"ERROR:{e.kind}:{msg}\n")
        return EXIT_CODES[e.kind]
    except RecursionError:
        sys.stderr.write("ERROR:bad_dsl:expression nested too deeply\n")
        return 1
    except MemoryError:
        sys.stderr.write("ERROR:runtime_error:out of memory\n")
        return 4
    except Exception as e:
        msg = ' '.join(f"{type(e).__name__}: {e}".split())
        sys.stderr.write(f"ERROR:runtime_error:{msg}\n")
        return 4
    return 0


if __name__ == '__main__':
    sys.exit(main())
