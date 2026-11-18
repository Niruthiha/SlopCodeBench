#!/usr/bin/env python3
"""mtl.py - run a small pipeline DSL (MTL) over a CSV of sales events and emit
deterministic JSON.  See DESIGN.md for the architecture."""
import sys

EXIT_CODES = {'bad_dsl': 1, 'type_error': 2, 'bad_io': 3, 'runtime_error': 4}


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
_OPS1 = frozenset('<>()[],*+-/&|!')
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
            fail('bad_dsl', f"line {line}: string literals must use single quotes")
        else:
            fail('bad_dsl', f"line {line}: unexpected character {ch!r}")
    append(('nl', '\n', line))
    append(('eof', '', line))
    return toks


# --------------------------------------------------------------------------
# Parser
# --------------------------------------------------------------------------
AGG_FUNCS = frozenset(('average', 'median', 'sum', 'count', 'std', 'var', 'min', 'max'))
SCALAR_FUNCS = {'len': (1, 1), 'day': (1, 1), 'month': (1, 1), 'year': (1, 1), 'round': (1, 2)}
CMP_OPS = frozenset(('<', '<=', '>', '>=', '==', '!='))
DUR_UNITS = {'m': 60, 'h': 3600, 'd': 86400}


def _desc(tok):
    if tok[0] == 'eof':
        return 'end of input'
    if tok[0] == 'nl':
        return 'end of line'
    if tok[0] == 'str':
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

    # -- statements --------------------------------------------------------
    def program(self):
        stmts = []
        while True:
            self.skip_nl()
            t = self.peek()
            if t[0] == 'eof':
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
                if d[0] != 'dur':
                    self.err('expected a duration literal such as 10m, 1h or 7d')
                self.i += 1
                secs = int(d[1][:-1]) * DUR_UNITS[d[1][-1]]
                if secs <= 0:
                    self.err('window duration must be positive', d)
                self.expect_op(')')
                stmts.append(('window', secs, t))
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
            else:
                self.err(f"unknown statement '{kw}'", t)
            if self.peek()[0] not in ('nl', 'eof'):
                self.err('expected end of statement')
        return stmts

    def id_list(self):
        cols = [self.expect_id('a column name')]
        while self.is_op(','):
            self.i += 1
            cols.append(self.expect_id('a column name'))
        return cols

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
        return (t[0] == 'op' and t[1] in CMP_OPS) or (t[0] == 'id' and t[1] == 'in')

    def cmp_expr(self):
        left = self.add_expr()
        t = self.peek()
        if t[0] == 'op' and t[1] in CMP_OPS:
            self.i += 1
            node = ('cmp', t[1], left, self.add_expr())
        elif t[0] == 'id' and t[1] == 'in':
            self.i += 1
            node = ('in', left, self.add_expr())
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
        if k == 'id':
            name = t[1]
            if name == 'true' or name == 'false':
                self.i += 1
                return ('lit', 'bool', name == 'true')
            if name == 'in':
                self.err("unexpected keyword 'in'")
            self.i += 1
            if self.is_op('('):
                if name not in SCALAR_FUNCS:
                    self.err(f"unknown function '{name}'", t)
                self.i += 1
                args = []
                if not self.is_op(')'):
                    args.append(self.expr())
                    while self.is_op(','):
                        self.i += 1
                        args.append(self.expr())
                self.expect_op(')')
                lo, hi = SCALAR_FUNCS[name]
                if not lo <= len(args) <= hi:
                    self.err(f"wrong number of arguments for '{name}'", t)
                return ('call', name, args)
            return ('col', name)
        if k == 'op' and t[1] == '(':
            self.i += 1
            e = self.expr()
            self.expect_op(')')
            return e
        if k == 'dur':
            self.err('duration literals are only allowed in window()')
        self.err('expected an expression')


def parse_dsl(src):
    toks = tokenize(src)
    stmts = Parser(toks).program()
    rows = []
    group = window = agg = None
    for s in stmts:
        k = s[0]
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
        else:
            rows.append(s)
    if agg is None:
        fail('bad_dsl', 'exactly one aggregate statement is required')
    seen = set()
    reserved = set(group or ())
    if window is not None:
        reserved.update(('window_start', 'window_end'))
    for fn, col, alias in agg:
        if alias in seen:
            fail('bad_dsl', f"duplicate aggregate alias '{alias}'")
        if alias in reserved:
            fail('bad_dsl', f"aggregate alias '{alias}' collides with an output key")
        seen.add(alias)
    idents = {t[1] for t in toks if t[0] == 'id'}
    return rows, group or [], window, agg, idents


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


# --------------------------------------------------------------------------
# Compiler: type check + generate a specialised row loop
# --------------------------------------------------------------------------
NUMERIC = ('int', 'float')
TYPE_NAMES = {'int': 'number', 'float': 'number', 'str': 'string', 'ts': 'timestamp', 'bool': 'boolean'}
FOLD_CHUNK = 65536
FOLD_MIN = 4096


def tname(t):
    return TYPE_NAMES[t]


class Compiler:
    def __init__(self, header, types, tz, fmt):
        self.env = {name: ('raw', types.get(name, 'str'), idx) for name, idx in header.items()}
        self.tz = tz
        self.fmt = fmt
        self.lines = []
        self.done = set()
        self.raw_used = []
        self.consts = {}
        self.nvar = 0

    def const(self, val):
        name = f'_k{len(self.consts)}'
        self.consts[name] = val
        return name

    def col(self, name):
        info = self.env.get(name)
        if info is None:
            fail('type_error', f"unknown column '{name}'")
        if info[0] == 'var':
            return info[2], info[1]
        _, typ, idx = info
        v = f'c{idx}'
        if idx not in self.done:
            self.done.add(idx)
            self.raw_used.append((name, idx, typ))
            self.emit_conv(v, typ, idx)
        return v, typ

    def emit_conv(self, v, typ, i):
        L = self.lines
        if typ == 'str':
            L.append(f'{v} = row[{i}]')
        elif typ == 'float':
            L.append(f'{v} = _float(row[{i}])')
        elif typ == 'int':
            L.append(f'{v} = _int(row[{i}])')
        elif typ == 'bool':
            L.append(f"{v} = row[{i}].strip().lower() == 'true'")
        else:
            if self.fmt is None:
                L.append(f'try: {v} = _fiso(row[{i}])')
                L.append(f'except ValueError: {v} = _fisofb(row[{i}])')
            else:
                L.append(f'{v} = _strp(row[{i}], _FMT)')
            L.append(f'_z = {v}.tzinfo')
            if self.tz is UTC:
                L.append(f'if _z is None: {v} = {v}.replace(tzinfo=_UTC)')
            else:
                L.append(f'if _z is None: {v} = {v}.replace(tzinfo=_TZ).astimezone(_UTC)')
            L.append(f'elif _z is not _UTC: {v} = {v}.astimezone(_UTC)')

    def gen(self, n):
        k = n[0]
        if k == 'lit':
            t, val = n[1], n[2]
            if t == 'str':
                return repr(val), 'str'
            if t == 'bool':
                return ('True' if val else 'False'), 'bool'
            if t == 'int':
                return repr(val), 'int'
            if val - val == 0.0:
                return repr(val), 'float'
            return self.const(val), 'float'
        if k == 'col':
            return self.col(n[1])
        if k == 'neg' or k == 'pos':
            c, t = self.gen(n[1])
            if t not in NUMERIC:
                fail('type_error', f"unary '{'-' if k == 'neg' else '+'}' requires a number, got {tname(t)}")
            return (f'(-{c})' if k == 'neg' else c), t
        if k == 'arith':
            op = n[1]
            lc, lt = self.gen(n[2])
            rc, rt = self.gen(n[3])
            if lt not in NUMERIC or rt not in NUMERIC:
                fail('type_error', f"operator '{op}' requires numbers, got {tname(lt)} and {tname(rt)}")
            t = 'float' if (op == '/' or lt == 'float' or rt == 'float') else 'int'
            return f'({lc} {op} {rc})', t
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
            return f'({lc} {op} {rc})', 'bool'
        if k == 'in':
            left, right = n[1], n[2]
            if not (left[0] == 'lit' and left[1] == 'str'):
                fail('type_error', "left operand of 'in' must be a string literal")
            if right[0] != 'col':
                fail('type_error', "right operand of 'in' must be a string column")
            rc, rt = self.col(right[1])
            if rt != 'str':
                fail('type_error', f"right operand of 'in' must be a string column, got {tname(rt)}")
            return f'({left[2]!r} in {rc})', 'bool'
        if k == 'and' or k == 'or':
            lc, lt = self.gen(n[1])
            rc, rt = self.gen(n[2])
            if lt != 'bool' or rt != 'bool':
                fail('type_error', f"operator '{'&' if k == 'and' else '|'}' requires booleans, "
                                   f"got {tname(lt)} and {tname(rt)}")
            return f'({lc} {k} {rc})', 'bool'
        if k == 'not':
            c, t = self.gen(n[1])
            if t != 'bool':
                fail('type_error', f"operator '!' requires a boolean, got {tname(t)}")
            return f'(not {c})', 'bool'
        if k == 'call':
            fn, args = n[1], n[2]
            c, t = self.gen(args[0])
            if fn == 'len':
                if t != 'str':
                    fail('type_error', f"len() requires a string, got {tname(t)}")
                return f'_len({c})', 'int'
            if fn in ('day', 'month', 'year'):
                if t != 'ts':
                    fail('type_error', f"{fn}() requires a timestamp, got {tname(t)}")
                return f'{c}.{fn}', 'int'
            # round
            if t not in NUMERIC:
                fail('type_error', f"round() requires a number, got {tname(t)}")
            if len(args) == 1:
                return (f'_r0({c})' if t == 'float' else c), t
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
                return f'_rdi({c}, {dc})', t
            if lit == 0:
                return f'_r0({c})', t
            return f'_rd({c}, {dc})', t
        raise AssertionError(k)

    def statement(self, s):
        if s[0] == 'filter':
            c, t = self.gen(s[1])
            if t != 'bool':
                fail('type_error', f"filter expression must be boolean, got {tname(t)}")
            self.lines.append(f'if not {c}: continue')
        else:
            c, t = self.gen(s[1])
            v = f'v{self.nvar}'
            self.nvar += 1
            self.lines.append(f'{v} = {c}')
            self.env[s[2]] = ('var', t, v)


# --------------------------------------------------------------------------
# Aggregation state folding / finalisation
# --------------------------------------------------------------------------
def make_fold(F, specs):
    def fold(G):
        for key, st in G.items():
            for j, isf, need_ss in specs:
                buf = st[j]
                if len(buf) < FOLD_MIN:
                    continue
                fk = (key, j)
                f = F.get(fk)
                mn = min(buf)
                mx = max(buf)
                if isf:
                    s = fsum(buf)
                    if f is None:
                        F[fk] = [[s], mn, mx]
                    else:
                        f[0].append(s)
                        if mn < f[1]:
                            f[1] = mn
                        if mx > f[2]:
                            f[2] = mx
                else:
                    s = sum(buf)
                    ss = sum([x * x for x in buf]) if need_ss else 0
                    if f is None:
                        F[fk] = [s, mn, mx, ss]
                    else:
                        f[0] += s
                        f[3] += ss
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
    """Return (sum, average, min, max, var, std, median) for one buffered
    column of one bucket; entries that were not requested are None."""
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
            if f is not None:
                f[0].extend(buf)
                s = fsum(f[0])
            else:
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
# CSV handling
# --------------------------------------------------------------------------
REQUIRED = {'timestamp': 'ts', 'location': 'str', 'item': 'str', 'price': 'float',
            'quantity': 'float', 'unit': 'str', 'category': 'str'}

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


SMALL_CSV = 4 << 20


def _file_size(path):
    import os
    try:
        return os.path.getsize(path)
    except OSError:
        return 0


def open_csv(path):
    try:
        fh = open(path, 'r', encoding='utf-8-sig', newline='', buffering=1 << 20)
    except OSError as e:
        fail('bad_io', f"cannot open CSV '{path}': {e.strerror or e}")
    return fh, _csv.reader(fh)


def infer_types(path, cols, ts_parse):
    """Infer the type of extra columns (name -> idx) with one pass over the CSV."""
    fh, rd = open_csv(path)
    # flags: [int, float, bool, ts]
    state = {name: [idx, True, True, True, True] for name, idx in cols.items()}
    nrows = 0
    try:
        with fh:
            next(rd, None)
            pending = list(state.values())
            for row in rd:
                if not row:
                    continue
                nrows += 1
                drop = False
                for st in pending:
                    v = row[st[0]]
                    if st[1] and not _is_int(v):
                        st[1] = False
                    if st[2] and not _is_float(v):
                        st[2] = False
                    if st[3] and v.strip().lower() not in ('true', 'false'):
                        st[3] = False
                    if st[4]:
                        try:
                            ts_parse(v)
                        except (ValueError, OverflowError):
                            st[4] = False
                    if not (st[1] or st[2] or st[3] or st[4]):
                        drop = True
                if drop:
                    pending = [st for st in pending if st[1] or st[2] or st[3] or st[4]]
                    if not pending:
                        break
    except IndexError:
        fail('bad_io', f"malformed CSV row at line {rd.line_num}: too few fields")
    except (UnicodeDecodeError, OSError) as e:
        fail('bad_io', f"cannot read CSV '{path}': {e}")
    except _csv.Error as e:
        fail('bad_io', f"malformed CSV at line {rd.line_num}: {e}")
    types = {}
    for name, st in state.items():
        if nrows == 0:
            types[name] = 'float'
        elif st[1]:
            types[name] = 'int'
        elif st[2]:
            types[name] = 'float'
        elif st[3]:
            types[name] = 'bool'
        elif st[4]:
            types[name] = 'ts'
        else:
            types[name] = 'str'
    return types


# --------------------------------------------------------------------------
# Main execution
# --------------------------------------------------------------------------
def execute(dsl_src, csv_path, tz, fmt):
    rows_stmts, group, window, aggs, idents = parse_dsl(dsl_src)

    fh, rd = open_csv(csv_path)
    try:
        header = next(rd)
    except StopIteration:
        fh.close()
        fail('bad_io', f"CSV '{csv_path}' is empty (header row required)")
    except (UnicodeDecodeError, OSError) as e:
        fh.close()
        fail('bad_io', f"cannot read CSV '{csv_path}': {e}")
    except Exception as e:
        fh.close()
        fail('bad_io', f"malformed CSV header: {e}")
    hidx = {}
    for i, h in enumerate(header):
        h = h.strip()
        if h not in hidx:
            hidx[h] = i
    missing = [c for c in REQUIRED if c not in hidx]
    if missing:
        fh.close()
        fail('bad_io', f"CSV is missing required column(s): {', '.join(missing)}")

    ts_parse = make_ts_parser(fmt, tz)
    types = dict(REQUIRED)
    extra = {h: i for h, i in hidx.items() if h not in REQUIRED and h in idents}
    if extra:
        types.update(infer_types(csv_path, extra, ts_parse))

    comp = Compiler(hidx, types, tz, fmt)
    for s in rows_stmts:
        comp.statement(s)

    # grouping key
    key_parts = []
    if window is not None:
        tv, tt = comp.col('timestamp')
        if tt != 'ts':
            fail('type_error', f"window requires 'timestamp' to be a timestamp, got {tname(tt)}")
        key_parts.append(f'{tv}.timestamp() // {window}')
    gtypes = []
    for g in group:
        gv, gt = comp.col(g)
        key_parts.append(gv)
        gtypes.append(gt)

    # aggregates -> buffers
    bufs = {}       # var -> [j, type, fns]
    items = []      # (alias, fn, j)
    for fn, col, alias in aggs:
        if col == '*':
            if fn != 'count':
                fail('type_error', f"{fn}(*) is not allowed; only count(*) accepts '*'")
            items.append((alias, 'count', None))
            continue
        v, t = comp.col(col)
        if t not in NUMERIC:
            fail('type_error', f"{fn}({col}) requires a numeric column, got {tname(t)}")
        if fn == 'count':
            items.append((alias, 'count', None))
            continue
        b = bufs.get(v)
        if b is None:
            b = bufs[v] = [len(bufs) + 1, t, set()]
        b[2].add(fn)
        items.append((alias, fn, b[0]))

    bufspecs = []   # (j, var, isf, keep, fns, need_ss)
    for v, (j, t, fns) in bufs.items():
        isf = t == 'float'
        keep = 'median' in fns or (isf and bool(fns & {'std', 'var'}))
        need_ss = (not isf) and bool(fns & {'std', 'var'})
        bufspecs.append((j, v, isf, keep, fns, need_ss))
    fold_specs = [(j, isf, ss) for j, v, isf, keep, fns, ss in bufspecs if not keep]

    # ---- generate the row loop ----
    # Compact array('d') float buffers only pay off on large inputs; importing
    # `array` costs more start-up time than it saves on small files.
    use_array = any(b[2] for b in bufspecs) and _file_size(csv_path) >= SMALL_CSV
    if use_array:
        from array import array
    else:
        array = None
    grouped = bool(key_parts)
    new_bucket = '[0' + ''.join(", _A('d')" if b[2] and use_array else ', []'
                                for b in bufspecs) + ']'
    tail = []
    if grouped:
        k = key_parts[0] if len(key_parts) == 1 else '(' + ', '.join(key_parts) + ',)'
        tail.append(f'k = {k}')
        tail.append('st = _gg(k)')
        tail.append('if st is None:')
        tail.append(f'    st = G[k] = {new_bucket}')
        tail.append('st[0] += 1')
        for j, v, *_ in bufspecs:
            tail.append(f'st[{j}].append({v})')
    else:
        tail.append('_c += 1')
        for j, v, *_ in bufspecs:
            tail.append(f'_ap{j}({v})')

    body = ['if not row: continue'] + comp.lines + tail
    src = ['def _run(rd, G, ' + ', '.join(f'{n}={n}' for n in
           ['_float', '_int', '_len', '_A', '_isl', '_fiso', '_fisofb', '_strp', '_FMT',
            '_UTC', '_TZ', '_r0', '_rd', '_rdi', '_fold'] + list(comp.consts)) + '):']
    src.append('    _c = 0')
    if grouped:
        src.append('    _gg = G.get')
    else:
        src.append(f'    st = G[None] = {new_bucket}')
        for j, *_ in bufspecs:
            src.append(f'    _ap{j} = st[{j}].append')
    if fold_specs:
        src.append(f'    _CH = {FOLD_CHUNK}')
        src.append('    while True:')
        src.append('        _ln = rd.line_num')
        src.append('        for row in _isl(rd, _CH):')
        src.extend('            ' + ln for ln in body)
        src.append('        if rd.line_num == _ln: break')
        if not grouped:
            src.append('        st[0] = _c')
        src.append('        _fold(G)')
        src.append('        if 4 * len(G) > _CH: _CH = 4 * len(G)')
    else:
        src.append('    for row in rd:')
        src.extend('        ' + ln for ln in body)
    if not grouped:
        src.append('    st[0] = _c')
    src.append('    return G')
    code = '\n'.join(src) + '\n'

    from itertools import islice
    F = {}
    ns = {
        '_float': float, '_int': int, '_len': len, '_A': array, '_isl': islice,
        '_fiso': _fromiso, '_fisofb': iso_fallback, '_strp': datetime.strptime, '_FMT': fmt,
        '_UTC': UTC, '_TZ': tz, '_r0': round0, '_rd': round_digits, '_rdi': round_int,
        '_fold': make_fold(F, fold_specs),
    }
    ns.update(comp.consts)
    exec(compile(code, '<mtl-pipeline>', 'exec'), ns)
    run = ns['_run']

    G = {}
    try:
        with fh:
            run(rd, G)
    except MTLError:
        raise
    except ValueError as e:
        row = _failing_row(e)
        diagnose_row(row, rd.line_num, comp.raw_used, ts_parse, types)
        fail('runtime_error', f"line {rd.line_num}: {e}")
    except IndexError:
        fail('bad_io', f"malformed CSV row at line {rd.line_num}: too few fields")
    except ZeroDivisionError:
        fail('runtime_error', f"line {rd.line_num}: division by zero")
    except OverflowError as e:
        fail('runtime_error', f"line {rd.line_num}: numeric overflow ({e})")
    except (UnicodeDecodeError, OSError) as e:
        fail('bad_io', f"cannot read CSV '{csv_path}': {e}")
    except _csv.Error as e:
        fail('bad_io', f"malformed CSV at line {rd.line_num}: {e}")
    except Exception as e:
        fail('runtime_error', f"line {rd.line_num}: {type(e).__name__}: {e}")

    try:
        return build_output(G, F, items, bufspecs, window, group, gtypes)
    except (ValueError, OverflowError, ZeroDivisionError) as e:
        fail('runtime_error', f"aggregate produced a non-finite value ({e})")


def _failing_row(exc):
    tb = exc.__traceback__
    row = None
    while tb is not None:
        if tb.tb_frame.f_code.co_name == '_run':
            row = tb.tb_frame.f_locals.get('row')
        tb = tb.tb_next
    return row


def diagnose_row(row, line, raw_used, ts_parse, types):
    if row is None:
        return
    for name, idx, typ in raw_used:
        if idx >= len(row):
            fail('bad_io', f"malformed CSV row at line {line}: too few fields")
        v = row[idx]
        try:
            if typ == 'float':
                float(v)
            elif typ == 'int':
                int(v)
            elif typ == 'ts':
                ts_parse(v)
            else:
                continue
        except (ValueError, OverflowError):
            what = {'float': 'number', 'int': 'integer', 'ts': 'timestamp'}[typ]
            fail('type_error', f"line {line}: column '{name}' has invalid {what} value {v!r}")


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


def build_output(G, F, items, bufspecs, window, group, gtypes):
    """Serialise the result to a JSON string (same layout as json.dumps)."""
    order = sorted(range(len(items)), key=lambda i: items[i][0])
    aliases = [items[i] for i in order]
    pre_alias = [json_str(a[0]) + ': ' for a in aliases]
    needed = {}
    for alias, fn, j in items:
        if j is not None:
            needed.setdefault(j, set()).add(fn)
    cols = []   # (j, isf, need_mm, need_sum, need_var, need_med)
    for j, v, isf, keep, fns, need_ss in bufspecs:
        if j in needed:
            cols.append((j, isf, bool(fns & {'min', 'max'}),
                         bool(fns & {'sum', 'average', 'std', 'var'}),
                         bool(fns & {'std', 'var'}), 'median' in fns))
    picks = [(fn == 'count', j, STAT_INDEX.get(fn)) for alias, fn, j in aliases]
    jv = _json_value
    Fget = F.get

    def agg_parts(key, st):
        n = st[0]
        stats = {}
        if n:
            for j, isf, mm, sm, vr, md in cols:
                stats[j] = column_stats(st[j], Fget((key, j)), isf, mm, sm, vr, md, n)
            return [p + (repr(n) if is_count else jv(stats[j][si]))
                    for p, (is_count, j, si) in zip(pre_alias, picks)]
        return [p + ('0' if is_count else 'null')
                for p, (is_count, j, si) in zip(pre_alias, picks)]

    if window is None and not group:
        st = G.get(None) or [0]
        return '{' + ', '.join(agg_parts(None, st)) + '}'

    single = len(group) + (window is not None) == 1
    pre_group = [json_str(g) + ': ' for g in group]
    gts = [t == 'ts' for t in gtypes]
    out = []
    wcache = {}
    for key in sorted(G):
        st = G.pop(key)
        kt = (key,) if single else key
        if window is None:
            parts = []
            gvals = kt
        else:
            w = kt[0]
            parts = wcache.get(w)
            if parts is None:
                start = EPOCH + timedelta(seconds=int(w) * window)
                parts = wcache[w] = [
                    '"window_start": "' + fmt_ts(start) + '"',
                    '"window_end": "' + fmt_ts(start + timedelta(seconds=window)) + '"']
            parts = parts[:]
            gvals = kt[1:]
        for p, is_ts, v in zip(pre_group, gts, gvals):
            parts.append(p + ('"' + fmt_ts(v) + '"' if is_ts else jv(v)))
        parts += agg_parts(key, st)
        out.append('{' + ', '.join(parts) + '}')
    return '[' + ', '.join(out) + ']'


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------
USAGE = ('usage: mtl.py --csv <path> --dsl <path-or-> [--out <path-or-stdout>] '
         '[--tz <IANA>] [--timestamp-format <str>]')
OPTIONS = {'--csv': 'csv', '--dsl': 'dsl', '--out': 'out', '--tz': 'tz',
           '--timestamp-format': 'timestamp_format'}


class Args:
    csv = dsl = out = timestamp_format = None
    tz = 'UTC'


def parse_args(argv):
    args = Args()
    i = 0
    n = len(argv)
    while i < n:
        a = argv[i]
        if a in ('-h', '--help'):
            sys.stdout.write(USAGE + '\n')
            sys.exit(0)
        name, eq, val = a.partition('=')
        dest = OPTIONS.get(name)
        if dest is None:
            fail('bad_io', f"invalid arguments: unrecognized argument {a!r}")
        if not eq:
            i += 1
            if i >= n:
                fail('bad_io', f"invalid arguments: {name} expects a value")
            val = argv[i]
        setattr(args, dest, val)
        i += 1
    for req in ('--csv', '--dsl'):
        if getattr(args, OPTIONS[req]) is None:
            fail('bad_io', f"invalid arguments: {req} is required")
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
        result = execute(src, args.csv, tz, args.timestamp_format)
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
