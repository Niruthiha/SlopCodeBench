#!/usr/bin/env python3
"""sith - a small static Python code intelligence tool.

Usage:
    python sith.py complete <file> <line> <col> [--fuzzy]
    python sith.py infer <file> <line> <col>
    python sith.py goto <file> <line> <col>
"""
import ast
import builtins
import contextlib
import importlib
import inspect
import io
import json
import keyword
import os
import re
import sys
import types
import warnings

MARK = '_SiThCuRsOr_'
KEYWORDS = list(keyword.kwlist)
KEYWORD_SET = set(KEYWORDS)
MAX_DEPTH = 40


class SithError(Exception):
    pass


# ---------------------------------------------------------------------------
# Error tolerant parsing
# ---------------------------------------------------------------------------

_OPENER_RE = re.compile(r"after .* on line (\d+)")
_BRACKETS = {'(': ')', '[': ']', '{': '}'}


def _indent_of(s):
    return s[:len(s) - len(s.lstrip(' \t\f'))]


def _code_part(s):
    """Return the line without a trailing comment (rough string awareness)."""
    quote = None
    i = 0
    while i < len(s):
        c = s[i]
        if quote:
            if c == '\\':
                i += 2
                continue
            if s.startswith(quote, i):
                i += len(quote)
                quote = None
                continue
        elif c == '#':
            return s[:i]
        elif c in '"\'':
            quote = c * 3 if s.startswith(c * 3, i) else c
            i += len(quote)
            continue
        i += 1
    return s


def _closers(s):
    stack = []
    s = _code_part(s)
    quote = None
    i = 0
    while i < len(s):
        c = s[i]
        if quote:
            if c == '\\':
                i += 2
                continue
            if s.startswith(quote, i):
                i += len(quote)
                quote = None
                continue
        elif c in '"\'':
            quote = c * 3 if s.startswith(c * 3, i) else c
            i += len(quote)
            continue
        elif c in _BRACKETS:
            stack.append(_BRACKETS[c])
        elif c in ')]}':
            if stack and stack[-1] == c:
                stack.pop()
        i += 1
    return ''.join(reversed(stack))


def _next_indent_deeper(work, ln):
    cur = len(_indent_of(work[ln - 1]).expandtabs(8))
    for k in range(ln, len(work)):
        t = work[k]
        if t.strip() == '' or t.strip().startswith('#'):
            continue
        return len(_indent_of(t).expandtabs(8)) > cur
    return False


def _try_parse(src):
    try:
        return ast.parse(src), None
    except SyntaxError as e:
        return None, e
    except (ValueError, RecursionError, MemoryError, OverflowError):
        return None, SyntaxError('invalid')


def _repair_parse(work, protected):
    """Parse ``work`` (list of lines), repairing broken lines in place.

    Returns the tree, or None if the error could only be fixed by touching
    the protected line.
    """
    max_iter = 2 * len(work) + 20
    for _ in range(max_iter):
        tree, e = _try_parse('\n'.join(work))
        if tree is not None:
            return tree
        msg = getattr(e, 'msg', '') or ''
        ln = getattr(e, 'lineno', None) or len(work)
        ln = max(1, min(ln, len(work)))
        if 'indented block' in msg:
            m = _OPENER_RE.search(msg)
            if m:
                k = int(m.group(1))
                if 1 <= k <= len(work):
                    code = _code_part(work[k - 1]).rstrip()
                    if not code.endswith(' pass'):
                        work[k - 1] = code + ' pass'
                        continue
        if work[ln - 1].strip() == '':
            k = ln - 1
            while k >= 1 and work[k - 1].strip() == '':
                k -= 1
            if k < 1:
                return None
            ln = k
        if ln == protected:
            return None
        line = work[ln - 1]
        if isinstance(e, IndentationError) and 'unexpected indent' in msg:
            # blank the whole over-indented block in one go
            width = len(_indent_of(line).expandtabs(8))
            k = ln
            while k <= len(work):
                t = work[k - 1]
                if t.strip() and len(_indent_of(t).expandtabs(8)) < width:
                    break
                if k == protected and k != ln:
                    break
                work[k - 1] = ''
                k += 1
            continue
        if isinstance(e, IndentationError) and 'unindent' in msg:
            work[ln - 1] = ''
            continue
        ind = _indent_of(line)
        code = _code_part(line).strip()
        if code.endswith(':') or _next_indent_deeper(work, ln):
            repl = ind + 'if True:'
        else:
            repl = ind + 'pass'
        if line == repl or line.strip() in ('pass', 'if True:'):
            work[ln - 1] = ''
        else:
            work[ln - 1] = repl
    return None


def _close_dangling(work, protected):
    """Close brackets left open on lines not followed by a continuation."""
    out = list(work)
    changed = False
    for i, line in enumerate(work):
        if i + 1 == protected or not line.strip() or line.strip().startswith('#'):
            continue
        cl = _closers(line)
        if not cl:
            continue
        j = i + 1
        while j < len(work) and (not work[j].strip() or work[j].strip().startswith('#')):
            j += 1
        if j < len(work):
            nxt = work[j]
            if nxt.strip()[0] in ')]}':
                continue
            if len(_indent_of(nxt).expandtabs(8)) > len(_indent_of(line).expandtabs(8)):
                continue
        out[i] = _code_part(line).rstrip() + cl
        changed = True
    return out if changed else None


def _tree_size(tree):
    return sum(1 for _ in ast.walk(tree))


def _repair_best(work, protected):
    """Repair ``work`` in place, trying a bracket-closing variant as well."""
    tree, e = _try_parse('\n'.join(work))
    if tree is not None:
        return tree
    alt = _close_dangling(work, protected)
    base = list(work)
    tree = _repair_parse(work, protected)
    if alt is not None:
        tree2 = _repair_parse(alt, protected)
        if tree2 is not None and (tree is None or _tree_size(tree2) > _tree_size(tree)):
            work[:] = alt
            return tree2
    if tree is None:
        work[:] = base
    return tree


def parse_source(text, cursor=None, with_text=False):
    """Parse ``text`` tolerantly; optionally also return the repaired source."""
    tree, work = _parse_source(text, cursor)
    if with_text:
        return tree, '\n'.join(work)
    return tree


def _parse_source(text, cursor):
    text = text.replace('\0', ' ')
    lines = text.split('\n')
    if cursor is not None:
        L, col = cursor
        cl = lines[L - 1]
        before, after = cl[:col], cl[col:]
        variants = [before + MARK + after, before + MARK + _closers(before)]
        if before.strip() == '':
            seen_ind = set()
            for k in range(L - 2, -1, -1):
                t = lines[k]
                if t.strip() == '' or t.strip().startswith('#'):
                    continue
                ind = _indent_of(t)
                if ind not in seen_ind:
                    seen_ind.add(ind)
                    variants.append(ind + MARK)
                if ind == '':
                    break
            variants.append(MARK)
            variants.append(before + 'pass')
        else:
            variants.append(_indent_of(cl) + 'pass')
        variants.append('')
        tried = set()
        for v in variants:
            if v in tried:
                continue
            tried.add(v)
            work = list(lines)
            work[L - 1] = v
            tree = _repair_best(work, L)
            if tree is not None:
                return tree, work
    work = list(lines)
    tree = _repair_best(work, None)
    if tree is None:
        tree = ast.parse('')
    return tree, work



# ---------------------------------------------------------------------------
# Scopes
# ---------------------------------------------------------------------------

def _char_col(lines, line, bcol):
    """Convert a utf-8 byte column into a character column."""
    if 1 <= line <= len(lines):
        t = lines[line - 1]
        return len(t.encode('utf-8')[:bcol].decode('utf-8', errors='ignore'))
    return bcol


def _line_text(lines, line):
    return lines[line - 1] if 1 <= line <= len(lines) else ''


_DEF_RE = re.compile(r'(?:async\s+)?(?:def|class)\s+')
_AS_RE = re.compile(r'\s+as\s+')


def _def_name_pos(lines, node):
    line = node.lineno
    t = _line_text(lines, line)
    c = _char_col(lines, line, node.col_offset)
    m = _DEF_RE.match(t, c)
    if m and t.startswith(node.name, m.end()):
        return (line, m.end())
    i = t.find(node.name, c)
    return (line, i if i >= 0 else c)


def _find_name_after(lines, line, ccol, name):
    t = _line_text(lines, line)
    m = re.compile(r'(?<![\w])' + re.escape(name) + r'(?![\w])').search(t, ccol)
    if m:
        return (line, m.start())
    return (line, ccol)


def _alias_parts(lines, a):
    """Return ([(part, pos)], aspos) for an import alias node."""
    line = getattr(a, 'lineno', None)
    if line is None:
        return [], None
    t = _line_text(lines, line)
    c = _char_col(lines, line, a.col_offset)
    parts = []
    i = c
    for p in a.name.split('.'):
        j = t.find(p, i)
        if j < 0:
            break
        parts.append((p, (line, j)))
        i = j + len(p)
    asp = None
    if a.asname:
        m = _AS_RE.search(t, i)
        if m:
            j = t.find(a.asname, m.end())
            if j >= 0:
                asp = (line, j)
        if asp is None:
            asp = (line, c)
    return parts, asp


class Binding:
    __slots__ = ('name', 'line', 'kind', 'node', 'extra', 'scope', 'stmt', 'pos', 'attr')

    def __init__(self, name, line, kind, node=None, extra=None, pos=None):
        self.name = name
        self.line = line
        self.kind = kind
        self.node = node
        self.extra = extra
        self.scope = None
        self.stmt = None
        self.pos = pos if pos is not None else (line, 0)
        self.attr = False


class Scope:
    def __init__(self, kind, node, parent, module):
        self.kind = kind  # module, function, class, lambda, comp
        self.node = node
        self.parent = parent
        self.module = module
        self.bindings = {}
        self.stars = []
        self.children = []
        self._value = None
        self._self_attrs = None
        self._self_aug = None
        self._bases = None
        self.globals = set()
        if parent is not None:
            parent.children.append(self)

    def add(self, b):
        b.scope = self
        self.bindings.setdefault(b.name, []).append(b)


class ModuleInfo:
    def __init__(self, path, tree, name, text=''):
        self.path = path
        self.dir = os.path.dirname(os.path.abspath(path))
        self.name = name
        self.tree = tree
        self.text = text
        self.lines = text.split('\n')
        self.is_package = os.path.basename(path) == '__init__.py'
        self.cursor_scope = None
        self.node_scopes = {}
        self.scope = Scope('module', tree, None, self)
        Builder(self).stmts(tree.body, self.scope)


def _all_args(args):
    out = list(getattr(args, 'posonlyargs', [])) + list(args.args)
    if args.vararg:
        out.append(args.vararg)
    out += list(args.kwonlyargs)
    if args.kwarg:
        out.append(args.kwarg)
    return out


class Builder:
    def __init__(self, module):
        self.m = module
        self.cur = None

    def mark(self, ident, sc):
        if ident and MARK in ident:
            self.m.cursor_scope = sc

    def pos(self, node):
        return (node.lineno, _char_col(self.m.lines, node.lineno, node.col_offset))

    def add(self, sc, b, stmt=False):
        b.stmt = self.cur if stmt is False else stmt
        if sc.kind == 'function' and b.name in sc.globals and b.kind != 'param':
            sc = self.m.scope
        sc.add(b)
        return b

    def stmts(self, body, sc):
        for s in body:
            prev = self.cur
            self.cur = s
            try:
                self.stmt(s, sc)
            except RecursionError:
                pass
            finally:
                self.cur = prev

    def stmt(self, s, sc):
        t = type(s)
        lines = self.m.lines
        if t in (ast.FunctionDef, ast.AsyncFunctionDef):
            self.mark(s.name, sc)
            for d in s.decorator_list:
                self.expr(d, sc)
            self.args_outer(s.args, sc)
            if s.returns is not None:
                self.expr(s.returns, sc)
            fs = Scope('function', s, sc, self.m)
            for g in _iter_stmts(s.body):
                if isinstance(g, ast.Global):
                    fs.globals.update(g.names)
            self.add(sc, Binding(s.name, s.lineno, 'def', s, fs, _def_name_pos(lines, s)))
            self.params(s.args, fs, s)
            self.stmts(s.body, fs)
        elif t is ast.ClassDef:
            self.mark(s.name, sc)
            for d in s.decorator_list:
                self.expr(d, sc)
            for b in s.bases:
                self.expr(b, sc)
            for k in s.keywords:
                self.expr(k.value, sc)
            cs = Scope('class', s, sc, self.m)
            self.add(sc, Binding(s.name, s.lineno, 'class', s, cs, _def_name_pos(lines, s)))
            self.stmts(s.body, cs)
        elif t is ast.Import:
            for a in s.names:
                self.mark(a.name, sc)
                self.mark(a.asname, sc)
                name = a.asname or a.name.split('.')[0]
                parts, asp = _alias_parts(lines, a)
                p = asp if a.asname else (parts[0][1] if parts else self.pos(s))
                b = self.add(sc, Binding(name, s.lineno, 'import', s, (a.name, a.asname), p))
                b.node = s
        elif t is ast.ImportFrom:
            self.mark(s.module, sc)
            for a in s.names:
                self.mark(a.name, sc)
                self.mark(a.asname, sc)
                if a.name == '*':
                    sc.stars.append((s.lineno, s.module or '', s.level or 0))
                else:
                    name = a.asname or a.name
                    parts, asp = _alias_parts(lines, a)
                    p = asp if a.asname else (parts[0][1] if parts else self.pos(s))
                    self.add(sc, Binding(name, s.lineno, 'from', s,
                                         (s.module or '', s.level or 0, a.name), p))
        elif t is ast.Assign:
            self.expr(s.value, sc)
            for tgt in s.targets:
                self.target(tgt, sc, ('assign', s.value))
        elif t is ast.AnnAssign:
            self.expr(s.annotation, sc)
            if s.value is not None:
                self.expr(s.value, sc)
            if isinstance(s.target, ast.Name):
                self.mark(s.target.id, sc)
                self.m.node_scopes[id(s.target)] = sc
                self.add(sc, Binding(s.target.id, s.target.lineno, 'ann', s,
                                     (s.annotation, s.value), self.pos(s.target)))
            else:
                self.expr(s.target, sc)
        elif t is ast.AugAssign:
            self.expr(s.target, sc)
            self.expr(s.value, sc)
        elif t in (ast.For, ast.AsyncFor):
            self.expr(s.iter, sc)
            self.target(s.target, sc, ('for', s.iter, sc))
            self.stmts(s.body, sc)
            self.stmts(s.orelse, sc)
        elif t in (ast.While, ast.If):
            self.expr(s.test, sc)
            self.stmts(s.body, sc)
            self.stmts(s.orelse, sc)
        elif t in (ast.With, ast.AsyncWith):
            for item in s.items:
                self.expr(item.context_expr, sc)
                if item.optional_vars is not None:
                    self.target(item.optional_vars, sc, ('with', item.context_expr, sc))
            self.stmts(s.body, sc)
        elif t is ast.Try or t.__name__ == 'TryStar':
            self.stmts(s.body, sc)
            for h in s.handlers:
                if h.type is not None:
                    self.expr(h.type, sc)
                if h.name:
                    self.mark(h.name, sc)
                    if h.type is not None:
                        ln = h.type.end_lineno
                        cc = _char_col(lines, ln, h.type.end_col_offset)
                    else:
                        ln, cc = self.pos(h)
                    p = _find_name_after(lines, ln, cc, h.name)
                    self.add(sc, Binding(h.name, h.lineno, 'except', h, h.type, p), stmt=h)
                prev = self.cur
                self.cur = h
                try:
                    self.stmts(h.body, sc)
                finally:
                    self.cur = prev
            self.stmts(s.orelse, sc)
            self.stmts(s.finalbody, sc)
        elif t.__name__ == 'Match':
            self.expr(s.subject, sc)
            for case in s.cases:
                prev = self.cur
                self.cur = case
                try:
                    self.pattern(case.pattern, sc)
                    if case.guard is not None:
                        self.expr(case.guard, sc)
                finally:
                    self.cur = prev
                self.stmts(case.body, sc)
        elif t.__name__ == 'TypeAlias':
            if isinstance(s.name, ast.Name):
                self.add(sc, Binding(s.name.id, s.lineno, 'stmt', s, None, self.pos(s.name)))
        else:
            for c in ast.iter_child_nodes(s):
                if isinstance(c, ast.expr):
                    self.expr(c, sc)

    def pattern(self, p, sc):
        lines = self.m.lines
        for n in ast.walk(p):
            name = None
            tn = type(n).__name__
            if tn in ('MatchAs', 'MatchStar'):
                name = n.name
            elif tn == 'MatchMapping':
                name = n.rest
            elif tn == 'MatchValue':
                self.expr(n.value, sc)
            elif tn == 'MatchClass':
                self.expr(n.cls, sc)
            if name:
                self.mark(name, sc)
                if tn == 'MatchAs' and n.pattern is not None:
                    ln = n.pattern.end_lineno
                    cc = _char_col(lines, ln, n.pattern.end_col_offset)
                else:
                    ln, cc = self.pos(n)
                p2 = _find_name_after(lines, ln, cc, name)
                self.add(sc, Binding(name, n.lineno, 'stmt', n, None, p2))

    def target(self, t, sc, how, path=()):
        if isinstance(t, ast.Name):
            self.mark(t.id, sc)
            self.m.node_scopes[id(t)] = sc
            p = self.pos(t)
            k = how[0]
            if k == 'assign':
                if path:
                    b = Binding(t.id, t.lineno, 'unpack', t, (how[1], path), p)
                else:
                    b = Binding(t.id, t.lineno, 'assign', t, how[1], p)
            elif k in ('for', 'with'):
                b = Binding(t.id, t.lineno, k, t, (how[1], path, how[2]), p)
            else:
                b = Binding(t.id, t.lineno, 'stmt', t, None, p)
            self.add(sc, b)
        elif isinstance(t, (ast.Tuple, ast.List)):
            for i, e in enumerate(t.elts):
                if isinstance(e, ast.Starred):
                    self.target(e.value, sc, ('stmt',))
                else:
                    self.target(e, sc, how, path + (i,))
        elif isinstance(t, ast.Starred):
            self.target(t.value, sc, ('stmt',))
        else:
            self.expr(t, sc)

    def args_outer(self, args, sc):
        for d in list(args.defaults) + [d for d in args.kw_defaults if d is not None]:
            self.expr(d, sc)
        for a in _all_args(args):
            if a.annotation is not None:
                self.expr(a.annotation, sc)

    def params(self, args, fs, fnode):
        positional = list(getattr(args, 'posonlyargs', [])) + list(args.args)
        defaults = list(args.defaults)
        defmap = {}
        for a, d in zip(positional[len(positional) - len(defaults):], defaults):
            defmap[id(a)] = d
        for a, d in zip(args.kwonlyargs, args.kw_defaults):
            if d is not None:
                defmap[id(a)] = d
        for a in _all_args(args):
            self.mark(a.arg, fs)
            idx = positional.index(a) if a in positional else None
            self.add(fs, Binding(a.arg, fnode.lineno, 'param', a, (fnode, idx, defmap.get(id(a))),
                                 self.pos(a)), stmt=None)

    def nearest_non_comp(self, sc):
        while sc.kind == 'comp' and sc.parent is not None:
            sc = sc.parent
        return sc

    def expr(self, e, sc):
        if e is None:
            return
        t = type(e)
        if t is ast.Name:
            self.mark(e.id, sc)
            self.m.node_scopes[id(e)] = sc
            return
        if t is ast.Attribute:
            self.mark(e.attr, sc)
            self.m.node_scopes[id(e)] = sc
            self.expr(e.value, sc)
            return
        if t is ast.NamedExpr:
            self.expr(e.value, sc)
            if isinstance(e.target, ast.Name):
                self.mark(e.target.id, sc)
                self.m.node_scopes[id(e.target)] = sc
                self.add(self.nearest_non_comp(sc),
                         Binding(e.target.id, e.target.lineno, 'assign', e.target, e.value,
                                 self.pos(e.target)))
            return
        if t is ast.Lambda:
            self.args_outer(e.args, sc)
            ls = Scope('lambda', e, sc, self.m)
            self.params(e.args, ls, e)
            self.expr(e.body, ls)
            return
        if t in (ast.ListComp, ast.SetComp, ast.GeneratorExp, ast.DictComp):
            gens = e.generators
            if gens:
                self.expr(gens[0].iter, sc)
            cs = Scope('comp', e, sc, self.m)
            for i, g in enumerate(gens):
                if i:
                    self.expr(g.iter, cs)
                self.target(g.target, cs, ('for', g.iter, sc if i == 0 else cs))
                for c in g.ifs:
                    self.expr(c, cs)
            if t is ast.DictComp:
                self.expr(e.key, cs)
                self.expr(e.value, cs)
            else:
                self.expr(e.elt, cs)
            return
        if t is ast.Call:
            self.m.node_scopes[id(e)] = sc
        for c in ast.iter_child_nodes(e):
            if isinstance(c, ast.expr):
                self.expr(c, sc)
            elif isinstance(c, ast.keyword):
                self.expr(c.value, sc)


def _iter_stmts(body):
    """Yield statements recursively, without entering new scopes."""
    for s in body:
        yield s
        if isinstance(s, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            continue
        for field in ('body', 'orelse', 'finalbody'):
            sub = getattr(s, field, None)
            if isinstance(sub, list):
                yield from _iter_stmts(sub)
        for h in getattr(s, 'handlers', []) or []:
            yield from _iter_stmts(h.body)
        for case in getattr(s, 'cases', []) or []:
            yield from _iter_stmts(case.body)


def _has_yield(fnode):
    stack = list(fnode.body)
    while stack:
        n = stack.pop()
        if isinstance(n, (ast.Yield, ast.YieldFrom)):
            return True
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)):
            continue
        stack.extend(ast.iter_child_nodes(n))
    return False


def _decorator_names(node):
    out = set()
    for d in getattr(node, 'decorator_list', ()):
        if isinstance(d, ast.Call):
            d = d.func
        if isinstance(d, ast.Name):
            out.add(d.id)
        elif isinstance(d, ast.Attribute):
            out.add(d.attr)
    return out


def _unparse(node):
    try:
        return ast.unparse(node)
    except Exception:
        return '...'


def _param_str(a, d):
    s = a.arg
    if a.annotation is not None:
        s += ': ' + _unparse(a.annotation)
    if d is not None:
        s += (' = ' if a.annotation is not None else '=') + _unparse(d)
    return s


def _params_text(args):
    out = []
    posonly = list(getattr(args, 'posonlyargs', []))
    positional = posonly + list(args.args)
    defaults = [None] * (len(positional) - len(args.defaults)) + list(args.defaults)
    for i, a in enumerate(positional):
        out.append(_param_str(a, defaults[i]))
        if posonly and i == len(posonly) - 1:
            out.append('/')
    if args.vararg:
        out.append('*' + _param_str(args.vararg, None))
    elif args.kwonlyargs:
        out.append('*')
    for a, d in zip(args.kwonlyargs, args.kw_defaults):
        out.append(_param_str(a, d))
    if args.kwarg:
        out.append('**' + _param_str(args.kwarg, None))
    return ', '.join(out)


def _ws(s):
    return re.sub(r'\s+', ' ', s or '').strip()


# ---------------------------------------------------------------------------
# Values
# ---------------------------------------------------------------------------

class RtV:
    """An actual runtime object."""
    __slots__ = ('obj',)

    def __init__(self, obj):
        self.obj = obj


class RtInst:
    """Instance of a runtime class, without an actual object."""
    __slots__ = ('cls',)

    def __init__(self, cls):
        self.cls = cls


class StMod:
    def __init__(self, info=None, pkgdir=None, name=''):
        self.info = info
        self.pkgdir = pkgdir
        self.name = name


class UnMod:
    def __init__(self, name):
        self.name = name


class StClass:
    def __init__(self, scope):
        self.scope = scope
        self.name = scope.node.name


class StInst:
    def __init__(self, cls, args=None):
        self.cls = cls
        self.args = args


class SuperInst:
    def __init__(self, cls):
        self.cls = cls


class StFunc:
    def __init__(self, node, scope, bound=None, skip=False):
        self.node = node
        self.scope = scope
        self.bound = bound
        self.skip = skip


def _sample_function():
    pass


def _sample_generator():
    yield


_SAMPLES = {
    int: lambda: 0, float: lambda: 0.0, complex: lambda: 0j, str: lambda: '',
    bytes: lambda: b'', bytearray: bytearray, list: list, dict: dict, set: set,
    frozenset: frozenset, tuple: tuple, bool: lambda: False, type(None): lambda: None,
    object: object,
}
_ROUTINE_TYPES = (staticmethod, classmethod)

_BUILTIN_RETURNS = {
    'len': int, 'repr': str, 'ascii': str, 'chr': str, 'ord': int, 'hex': str, 'oct': str,
    'bin': str, 'format': str, 'input': str, 'hash': int, 'id': int, 'isinstance': bool,
    'issubclass': bool, 'callable': bool, 'hasattr': bool, 'all': bool, 'any': bool,
    'sorted': list, 'round': int, 'divmod': tuple, 'vars': dict, 'dir': list,
    'globals': dict, 'locals': dict, 'print': type(None), 'setattr': type(None),
    'delattr': type(None), 'sum': int,
}

_STR_METHODS = {
    'str': ('capitalize casefold center expandtabs format format_map join ljust lower lstrip '
            'removeprefix removesuffix replace rjust rstrip strip swapcase title translate '
            'upper zfill'),
    'list': 'split rsplit splitlines',
    'int': 'count find index rfind rindex',
    'bool': ('endswith startswith isalnum isalpha isascii isdecimal isdigit isidentifier '
             'islower isnumeric isprintable isspace istitle isupper'),
    'bytes': 'encode',
    'tuple': 'partition rpartition',
}
_STR_RETURNS = {m: getattr(builtins, t) for t, ms in _STR_METHODS.items() for m in ms.split()}


def rt_instance(cls):
    f = _SAMPLES.get(cls)
    if f is not None:
        try:
            return RtV(f())
        except Exception:
            pass
    return RtInst(cls)


def class_value(scope):
    if scope._value is None:
        scope._value = StClass(scope)
    return scope._value


def kind_of(v):
    if isinstance(v, (StMod, UnMod)):
        return 'module'
    if isinstance(v, StClass):
        return 'class'
    if isinstance(v, (StInst, SuperInst, RtInst)):
        return 'instance'
    if isinstance(v, StFunc):
        return 'function'
    if isinstance(v, RtV):
        o = v.obj
        if inspect.ismodule(o):
            return 'module'
        if inspect.isclass(o):
            return 'class'
        if inspect.isroutine(o) or isinstance(o, _ROUTINE_TYPES):
            return 'function'
        return 'instance'
    return None


def type_name(v):
    if isinstance(v, StInst):
        return v.cls.name
    if isinstance(v, SuperInst):
        return 'super'
    if isinstance(v, RtInst):
        return getattr(v.cls, '__name__', 'object')
    if isinstance(v, RtV):
        return type(v.obj).__name__
    return 'object'


def instantiate(v, args=None):
    if isinstance(v, StClass):
        return StInst(v, args)
    if isinstance(v, RtV) and inspect.isclass(v.obj):
        return rt_instance(v.obj)
    return None


def describe_value(name, v):
    k = kind_of(v)
    if k == 'module':
        return 'module', 'module ' + name
    if k == 'class':
        return 'class', 'class ' + name
    if k == 'function':
        return 'function', 'def %s(...)' % name
    if k == 'instance':
        return 'instance', 'instance of ' + type_name(v)
    return 'statement', 'statement'


def _vkey(v):
    if isinstance(v, RtV):
        if kind_of(v) == 'instance':
            return ('rti', type(v.obj))
        return ('rt', id(v.obj))
    if isinstance(v, RtInst):
        return ('rti', v.cls)
    if isinstance(v, StInst):
        return ('si', id(v.cls))
    if isinstance(v, StClass):
        return ('sc', id(v.scope))
    if isinstance(v, StFunc):
        return ('sf', id(v.node))
    if isinstance(v, StMod):
        return ('sm', id(v.info), v.pkgdir)
    if isinstance(v, UnMod):
        return ('um', v.name)
    if isinstance(v, SuperInst):
        return ('su', id(v.cls))
    return ('o', id(v))


def uniq(vals):
    out = []
    seen = set()
    for v in vals:
        if v is None:
            continue
        k = _vkey(v)
        if k in seen:
            continue
        seen.add(k)
        out.append(v)
    return out


# ---------------------------------------------------------------------------
# Flow analysis (reaching definitions with type narrowing)
# ---------------------------------------------------------------------------

_EMPTY = ()


class _Found(Exception):
    def __init__(self, state):
        Exception.__init__(self)
        self.state = state


def _start(n):
    return (n.lineno, n.col_offset)


def _end(n):
    return (getattr(n, 'end_lineno', n.lineno) or n.lineno, getattr(n, 'end_col_offset', 0) or 0)


def _st_union(states):
    states = [s for s in states if s is not None]
    if not states:
        return None
    if len(states) == 1:
        return states[0]
    ents = []
    seen = set()
    for s in states:
        for e in s:
            k = (id(e[1]),) + tuple(id(op) for op in e[2])
            if k not in seen:
                seen.add(k)
                ents.append(e)
    return tuple(ents)


class Flow:
    def __init__(self, engine, sc, name, pos):
        self.e = engine
        self.sc = sc
        self.name = name
        self.pos = pos
        self.by_stmt = {}
        for b in sc.bindings.get(name, ()):
            self.by_stmt.setdefault(id(b.stmt), []).append(('b', b, ()))
        self.loops = []

    def run(self):
        init = tuple(self.by_stmt.get(id(None), ()))
        try:
            return self.block(self.sc.node.body, init)
        except _Found as f:
            return f.state

    # -- helpers --

    def hdr(self, node, st):
        if st is None:
            return None
        ents = self.by_stmt.get(id(node))
        if ents:
            return tuple(ents)
        if isinstance(node, ast.ImportFrom) and any(a.name == '*' for a in node.names):
            ent = self.e.star_entry(self.sc, node, self.name)
            if ent is not None:
                return ((ent[0], ent[1], ()),)
        return st

    def inn(self, node):
        return _start(node) <= self.pos <= _end(node)

    def quiet(self, stmts, st):
        saved = self.pos
        self.pos = None
        try:
            return self.block(stmts, st)
        finally:
            self.pos = saved

    def narrow(self, st, test, positive):
        if st is None:
            return None
        ops = self.cond(test, positive)
        if not ops:
            return st
        ops = tuple(ops)
        return tuple((e[0], e[1], e[2] + ops) for e in st)

    def cond(self, test, positive):
        name = self.name
        if isinstance(test, ast.UnaryOp) and isinstance(test.op, ast.Not):
            return self.cond(test.operand, not positive)
        if isinstance(test, ast.BoolOp):
            if isinstance(test.op, ast.And) and positive:
                return [o for v in test.values for o in self.cond(v, True)]
            if isinstance(test.op, ast.Or) and not positive:
                return [o for v in test.values for o in self.cond(v, False)]
            return []
        if isinstance(test, ast.Call) and isinstance(test.func, ast.Name) \
                and test.func.id == 'isinstance' and len(test.args) == 2 \
                and isinstance(test.args[0], ast.Name) and test.args[0].id == name:
            return [('isinstance', test.args[1], positive, self.sc)]
        if isinstance(test, ast.Compare) and len(test.ops) == 1:
            left, right = test.left, test.comparators[0]
            op = test.ops[0]
            if isinstance(right, ast.Name) and right.id == name:
                left, right = right, left
            if isinstance(left, ast.Name) and left.id == name and \
                    isinstance(right, ast.Constant) and right.value is None:
                if isinstance(op, (ast.Is, ast.Eq)):
                    return [('none', positive)]
                if isinstance(op, (ast.IsNot, ast.NotEq)):
                    return [('none', not positive)]
        return []

    def const(self, test):
        if isinstance(test, ast.Constant):
            try:
                return bool(test.value)
            except Exception:
                return None
        if isinstance(test, ast.UnaryOp) and isinstance(test.op, ast.Not):
            c = self.const(test.operand)
            return None if c is None else not c
        return None

    def loop(self, s, st, test=None):
        """Return (entry_state, normal_exit_state, breaks) for a loop."""
        is_for = isinstance(s, (ast.For, ast.AsyncFor))
        first = self.hdr(s, st)
        if test is not None:
            first = self.narrow(first, test, True)
        self.loops.append(([], []))
        try:
            end = self.quiet(s.body, first)
        finally:
            brk, cont = self.loops.pop()
        again = _st_union([end] + cont)
        if is_for:
            entry = _st_union([first, self.hdr(s, again)])
            exit_ = _st_union([st, again])
        else:
            entry = _st_union([first, again])
            if test is not None and self.const(test) is True:
                exit_ = None
            else:
                exit_ = self.narrow(_st_union([st, again]), test, False) if test is not None \
                    else _st_union([st, again])
        return entry, exit_, brk

    # -- walking --

    def block(self, stmts, st):
        for s in stmts:
            if self.pos is not None:
                if self.pos < _start(s):
                    raise _Found(st if st is not None else _EMPTY)
                if self.pos <= _end(s):
                    self.inside(s, st if st is not None else _EMPTY)
            st = self.apply(s, st)
        return st

    def _sub(self, stmts, st):
        r = self.block(stmts, st)
        raise _Found(r if r is not None else _EMPTY)

    def inside(self, s, st):
        t = type(s)
        p = self.pos
        if t is ast.If:
            st = self.hdr(s, st)
            if self.inn(s.test):
                raise _Found(st)
            if s.orelse and p >= _start(s.orelse[0]):
                self._sub(s.orelse, self.narrow(st, s.test, False))
            self._sub(s.body, self.narrow(st, s.test, True))
        if t is ast.While:
            if self.inn(s.test):
                raise _Found(_st_union([st, self.loop(s, st, s.test)[0]]))
            entry, exit_, brk = self.loop(s, st, s.test)
            if s.orelse and p >= _start(s.orelse[0]):
                self._sub(s.orelse, exit_)
            self.loops.append(([], []))
            self._sub(s.body, entry)
        if t in (ast.For, ast.AsyncFor):
            if self.inn(s.iter):
                raise _Found(st)
            entry, exit_, brk = self.loop(s, st)
            if self.inn(s.target):
                raise _Found(entry)
            if s.orelse and p >= _start(s.orelse[0]):
                self._sub(s.orelse, exit_)
            self.loops.append(([], []))
            self._sub(s.body, entry)
        if t in (ast.With, ast.AsyncWith):
            for item in s.items:
                if self.inn(item.context_expr):
                    raise _Found(st)
            self._sub(s.body, self.hdr(s, st))
        if t is ast.Try or t.__name__ == 'TryStar':
            for h in s.handlers:
                if _start(h) <= p <= _end(h):
                    b = self.quiet(s.body, st)
                    self._sub(h.body, self.hdr(h, _st_union([st, b])))
            if s.finalbody and p >= _start(s.finalbody[0]):
                self._sub(s.finalbody, _st_union([st, self.quiet([s], st)]))
            if s.orelse and p >= _start(s.orelse[0]):
                self._sub(s.orelse, self.quiet(s.body, st))
            self._sub(s.body, st)
        if t.__name__ == 'Match':
            for case in reversed(s.cases):
                if p >= _start(case.pattern):
                    self._sub(case.body, self.hdr(case, st))
            raise _Found(st)
        raise _Found(st)

    def apply(self, s, st):
        if st is None:
            return None
        t = type(s)
        if t in (ast.Return, ast.Raise):
            return None
        if t is ast.Break:
            if self.loops:
                self.loops[-1][0].append(st)
            return None
        if t is ast.Continue:
            if self.loops:
                self.loops[-1][1].append(st)
            return None
        if t is ast.If:
            st = self.hdr(s, st)
            c = self.const(s.test)
            b = self.block(s.body, self.narrow(st, s.test, True)) if c is not False else None
            o = self.block(s.orelse, self.narrow(st, s.test, False)) if c is not True else None
            return _st_union([b, o])
        if t is ast.While:
            entry, exit_, brk = self.loop(s, st, s.test)
            o = self.block(s.orelse, exit_) if s.orelse else exit_
            return _st_union([o] + brk)
        if t in (ast.For, ast.AsyncFor):
            entry, exit_, brk = self.loop(s, st)
            o = self.block(s.orelse, exit_) if s.orelse else exit_
            return _st_union([o] + brk)
        if t in (ast.With, ast.AsyncWith):
            return self.block(s.body, self.hdr(s, st))
        if t is ast.Try or t.__name__ == 'TryStar':
            b = self.block(s.body, st)
            hs = [self.block(h.body, self.hdr(h, _st_union([st, b]))) for h in s.handlers]
            o = self.block(s.orelse, b) if s.orelse else b
            res = _st_union([o] + hs)
            if s.finalbody:
                f = self.block(s.finalbody, res if res is not None else st)
                return f if res is not None else None
            return res
        if t.__name__ == 'Match':
            outs = [self.block(c.body, self.hdr(c, st)) for c in s.cases]
            return _st_union(outs + [st])
        return self.hdr(s, st)


# ---------------------------------------------------------------------------
# Inference engine
# ---------------------------------------------------------------------------

class Engine:
    def __init__(self, root=None):
        self.static_cache = {}
        self.rt_cache = {}
        self.inferring = set()
        self.calling = set()
        self.frames = {}
        self.reach_cache = {}
        self.root = root
        self.steps = 0
        self.max_steps = 400000

    # ----- modules -----

    def load_static(self, path, name):
        path = os.path.realpath(path)
        if path in self.static_cache:
            return self.static_cache[path]
        try:
            with open(path, 'rb') as f:
                text = f.read().decode('utf-8', errors='replace')
        except OSError:
            self.static_cache[path] = None
            return None
        if text.startswith('\ufeff'):
            text = text[1:]
        text = text.replace('\r\n', '\n').replace('\r', '\n')
        self.static_cache[path] = None
        try:
            tree, text = parse_source(text, with_text=True)
            info = ModuleInfo(path, tree, name, text)
        except RecursionError:
            info = None
        self.static_cache[path] = info
        return info

    def find_local(self, dotted, base_dir):
        parts = [p for p in dotted.split('.') if p]
        if not parts:
            return None
        d = base_dir
        for i, p in enumerate(parts):
            if i < len(parts) - 1:
                nd = os.path.join(d, p)
                if os.path.isdir(nd):
                    d = nd
                    continue
                return None
            f = os.path.join(d, p + '.py')
            if os.path.isfile(f):
                return ('file', f)
            f = os.path.join(d, p, '__init__.py')
            if os.path.isfile(f):
                return ('file', f)
            nd = os.path.join(d, p)
            if os.path.isdir(nd):
                return ('dir', nd)
        return None

    def static_module(self, found, name):
        kind, p = found
        if kind == 'file':
            info = self.load_static(p, name)
            pkgdir = os.path.dirname(p) if os.path.basename(p) == '__init__.py' else None
            return StMod(info, pkgdir, name)
        return StMod(None, p, name)

    def rt_import(self, name):
        if name in self.rt_cache:
            return self.rt_cache[name]
        mod = None
        try:
            with contextlib.redirect_stdout(io.StringIO()), \
                    contextlib.redirect_stderr(io.StringIO()), warnings.catch_warnings():
                warnings.simplefilter('ignore')
                mod = importlib.import_module(name)
        except BaseException:
            mod = None
        self.rt_cache[name] = mod
        return mod

    def resolve_module(self, dotted, base_dir, level=0):
        if level > 0:
            d = base_dir
            for _ in range(level - 1):
                d = os.path.dirname(d)
            if not dotted:
                init = os.path.join(d, '__init__.py')
                if os.path.isfile(init):
                    return StMod(self.load_static(init, ''), d, '')
                return StMod(None, d, '')
            found = self.find_local(dotted, d)
            if found:
                return self.static_module(found, dotted)
            return UnMod(dotted)
        found = self.find_local(dotted, base_dir)
        if found:
            return self.static_module(found, dotted)
        if self.root and os.path.realpath(self.root) != os.path.realpath(base_dir):
            found = self.find_local(dotted, self.root)
            if found:
                return self.static_module(found, dotted)
        mod = self.rt_import(dotted)
        if mod is not None:
            return RtV(mod)
        return UnMod(dotted)

    def star_names(self, mv, seen=None):
        """Return dict name -> thunk for names exported by a star import."""
        out = {}
        if isinstance(mv, RtV) and inspect.ismodule(mv.obj):
            o = mv.obj
            try:
                names = dir(o)
            except Exception:
                names = []
            for n in names:
                if not n.startswith('_'):
                    out[n] = self._rt_attr_entry(o, n)
        elif isinstance(mv, StMod) and mv.info is not None:
            if seen is None:
                seen = set()
            if id(mv.info) in seen:
                return out
            seen.add(id(mv.info))
            out.update(self.module_entries(mv.info, seen))
        return out

    def star_entry(self, sc, node, name):
        mv = self.resolve_module(node.module or '', sc.module.dir, node.level or 0)
        return self.star_names(mv).get(name)

    def star_has(self, sc, name):
        for (sl, mod, lvl) in sc.stars:
            mv = self.resolve_module(mod, sc.module.dir, lvl)
            if name in self.star_names(mv):
                return True
        return False

    def module_entries(self, info, seen=None):
        sc = info.scope
        out = {}
        items = []
        for n, lst in sc.bindings.items():
            b = max(lst, key=lambda x: x.line)
            items.append((b.line, n, ('b', b)))
        for (sl, mod, lvl) in sc.stars:
            mv = self.resolve_module(mod, info.dir, lvl)
            for n, ent in self.star_names(mv, seen if seen is not None else {id(info)}).items():
                items.append((sl, n, ent))
        items.sort(key=lambda x: x[0])
        for _, n, ent in items:
            if not n.startswith('_') and MARK not in n:
                out[n] = ent
        return out

    def _rt_attr_entry(self, o, n):
        def thunk():
            try:
                with warnings.catch_warnings():
                    warnings.simplefilter('ignore')
                    return RtV(getattr(o, n))
            except BaseException:
                return None
        return ('v', thunk)

    # ----- lookup (completion style, line based) -----

    def chain(self, sc):
        res = []
        local = True
        i = 0
        s = sc
        while s is not None:
            if s.kind == 'module':
                res.append((s, True))
                break
            if s.kind == 'class' and i > 0:
                s = s.parent
                i += 1
                local = False
                continue
            if s.kind in ('comp', 'lambda'):
                res.append((s, False))
            else:
                res.append((s, local))
                local = False
            s = s.parent
            i += 1
        return res

    def scope_candidates(self, s, name, line, filt):
        """Ordered (latest first) list of definitions for name in scope s."""
        cands = []
        for b in s.bindings.get(name, ()):
            cands.append((b.line, ('b', b)))
        for (sl, mod, lvl) in s.stars:
            if filt and sl > line:
                continue
            mv = self.resolve_module(mod, s.module.dir, lvl)
            ent = self.star_names(mv).get(name)
            if ent is not None:
                cands.append((sl, ent))
        before = [c for c in cands if c[0] <= line]
        if before:
            before.sort(key=lambda c: c[0])
            return [c[1] for c in reversed(before)]
        if filt or not cands:
            return []
        return [c[1] for c in reversed(cands)]

    def visible(self, sc, line):
        out = {}
        for s, filt in self.chain(sc):
            names = set(s.bindings)
            for (sl, mod, lvl) in s.stars:
                if filt and sl > line:
                    continue
                mv = self.resolve_module(mod, s.module.dir, lvl)
                names.update(self.star_names(mv))
            for n in names:
                if n in out or MARK in n:
                    continue
                c = self.scope_candidates(s, n, line, filt)
                if c:
                    out[n] = c[0]
        for n in dir(builtins):
            if n not in out and n not in KEYWORD_SET:
                out[n] = self._rt_attr_entry(builtins, n)
        return out

    # ----- lookup (flow sensitive) -----

    def reach(self, s, name, pos):
        key = (id(s), name, pos)
        if key in self.reach_cache:
            return self.reach_cache[key]
        if s.kind in ('comp', 'lambda'):
            bl = s.bindings.get(name)
            r = tuple(('b', b, ()) for b in bl) if bl else None
        elif name not in s.bindings and not (s.stars and self.star_has(s, name)):
            r = None
        else:
            self.reach_cache[key] = _EMPTY
            try:
                r = Flow(self, s, name, pos).run()
            except RecursionError:
                r = None
            if r is None:
                r = _EMPTY
        self.reach_cache[key] = r
        return r

    def lookup_state(self, name, sc, pos):
        deferred = False
        for i, (s, _) in enumerate(self.chain(sc)):
            if i == 0:
                r = self.reach(s, name, pos)
                if r:
                    return r
                if r is not None and pos is not None:
                    bl = [b for b in s.bindings.get(name, ()) if b.line <= pos[0]]
                    if bl:
                        return (('b', max(bl, key=lambda x: x.line), ()),)
            else:
                r = self.reach(s, name, None if deferred else pos)
                if r is not None and not r and not deferred:
                    r = self.reach(s, name, None)
                if r is not None:
                    if deferred:
                        r = tuple((e[0], e[1], ()) for e in r)
                    if not r:
                        r = tuple(('b', b, ()) for b in s.bindings.get(name, ()))
                    if r:
                        return r
            if s.kind in ('function', 'lambda'):
                deferred = True
        return None

    def scope_end_entries(self, s, name):
        r = self.reach(s, name, None)
        if r is None:
            return []
        if r:
            return list(r)
        return [('b', b, ()) for b in s.bindings.get(name, ())]

    def lookup_values(self, name, sc, pos, depth):
        st = self.lookup_state(name, sc, pos)
        if st is None:
            if hasattr(builtins, name):
                return [RtV(getattr(builtins, name))]
            return []
        return self.entries_values(st, depth)

    def apply_narrows(self, vals, narrows, depth):
        for op in narrows:
            if op[0] == 'isinstance':
                node, positive, sc = op[1], op[2], op[3]
                nodes = node.elts if isinstance(node, ast.Tuple) else [node]
                classes = []
                for n in nodes:
                    classes += self.infer(n, sc, None, depth + 1)
                classes = [c for c in uniq(classes) if kind_of(c) == 'class']
                if positive:
                    vals = uniq(instantiate(c) for c in classes)
                else:
                    vals = [v for v in vals if not self.is_instance_of(v, classes)]
            elif op[0] == 'none':
                if op[1]:
                    vals = [RtV(None)]
                else:
                    vals = [v for v in vals if not (isinstance(v, RtV) and v.obj is None)]
        return vals

    def is_instance_of(self, v, classes):
        for c in classes:
            if isinstance(c, StClass):
                if isinstance(v, StInst) and c in self.mro(v.cls):
                    return True
            elif isinstance(c, RtV) and inspect.isclass(c.obj):
                try:
                    if isinstance(v, RtV) and kind_of(v) == 'instance' and isinstance(v.obj, c.obj):
                        return True
                    if isinstance(v, RtInst) and issubclass(v.cls, c.obj):
                        return True
                except Exception:
                    pass
        return False

    # ----- entries -----

    def entries_values(self, ents, depth=0):
        vals = []
        for ent in ents:
            if ent[0] == 'b' and id(ent[1]) in self.inferring:
                continue
            ev = self.entry_values(ent, depth)
            if len(ent) > 2 and ent[2]:
                ev = self.apply_narrows(ev, ent[2], depth)
            vals += ev
        return uniq(vals)

    def entry_values(self, ent, depth=0):
        if ent[0] == 'b':
            return self.binding_values(ent[1], depth)
        v = ent[1]()
        return [v] if v is not None else []

    def entry_value(self, ent, depth=0):
        vals = self.entry_values(ent, depth)
        return vals[0] if vals else None

    def describe_entry(self, name, ent):
        if ent[0] == 'b':
            b = ent[1]
            if b.kind == 'def':
                return 'function', 'def %s(...)' % name
            if b.kind == 'class':
                return 'class', 'class ' + name
            if b.kind == 'import':
                return 'module', 'module ' + name
            if b.kind == 'param':
                return 'param', 'param ' + name
        try:
            v = self.entry_value(ent)
        except RecursionError:
            v = None
        return describe_value(name, v)

    def binding_values(self, b, depth=0):
        if depth > MAX_DEPTH:
            return []
        key = id(b)
        if key in self.inferring:
            return []
        self.inferring.add(key)
        try:
            return uniq(self._binding_values(b, depth))
        except RecursionError:
            return []
        finally:
            self.inferring.discard(key)

    def _binding_values(self, b, depth):
        k = b.kind
        sc = b.scope
        if k == 'def':
            return [StFunc(b.node, b.extra)]
        if k == 'class':
            return [class_value(b.extra)]
        if k == 'import':
            full, asname = b.extra
            if asname:
                return [self.resolve_module(full, sc.module.dir)]
            top = full.split('.')[0]
            if '.' in full:
                self.resolve_module(full, sc.module.dir)
            return [self.resolve_module(top, sc.module.dir)]
        if k == 'from':
            mod, level, attr = b.extra
            mv = self.resolve_module(mod, sc.module.dir, level)
            vals = self.get_attr(mv, attr, depth + 1)
            if not vals and level == 0 and isinstance(mv, RtV):
                m = self.rt_import(mod + '.' + attr)
                if m is not None:
                    return [RtV(m)]
            return vals
        if k == 'assign':
            return self.infer(b.extra, sc, None, depth + 1)
        if k == 'unpack':
            value, path = b.extra
            return self.path_values(('n', value, sc), path, depth + 1)
        if k == 'ann':
            ann, value = b.extra
            vals = self.infer_annotation(ann, sc, depth + 1)
            if vals:
                return vals
            if value is not None:
                return self.infer(value, sc, None, depth + 1)
            return []
        if k == 'param':
            return self.param_values(b, depth)
        if k == 'except':
            if b.extra is None:
                return []
            nodes = b.extra.elts if isinstance(b.extra, ast.Tuple) else [b.extra]
            out = []
            for n in nodes:
                out += [instantiate(v) for v in self.infer(n, sc, None, depth + 1)]
            return out
        if k == 'for':
            it, path, isc = b.extra
            out = []
            for item in self.iter_items(it, isc, depth + 1):
                out += self.path_values(item, path, depth + 1)
            return out
        if k == 'with':
            expr, path, wsc = b.extra
            out = []
            for v in self.infer(expr, wsc, None, depth + 1):
                ent = self.get_attr(v, '__enter__', depth + 1) if isinstance(v, StInst) else []
                got = []
                for f in ent:
                    got += self.call(f, None, depth + 1)
                out += got if got else [v]
            if path:
                return []
            return out
        return []

    # ----- iteration / unpacking -----

    def iter_items(self, node, sc, depth):
        """Return items for the elements of iterable `node`.

        An item is ('n', node, scope), ('v', value) or ('t', [items_per_index]).
        """
        if depth > MAX_DEPTH:
            return []
        t = type(node)
        if t in (ast.List, ast.Tuple, ast.Set):
            return [('n', e, sc) for e in node.elts if not isinstance(e, ast.Starred)]
        if t is ast.Dict:
            return [('n', k, sc) for k in node.keys if k is not None]
        if t in (ast.ListComp, ast.SetComp, ast.GeneratorExp):
            cs = self._comp_scope(node, sc)
            return [('n', node.elt, cs)] if cs is not None else []
        if t is ast.DictComp:
            cs = self._comp_scope(node, sc)
            return [('n', node.key, cs)] if cs is not None else []
        if t is ast.Constant and isinstance(node.value, (str, bytes)):
            return [('v', RtV(type(node.value)()))]
        if t is ast.Call:
            f = node.func
            fname = f.id if isinstance(f, ast.Name) else None
            if fname == 'range':
                return [('v', RtV(0))]
            if fname == 'enumerate' and node.args:
                return [('t', [[('v', RtV(0))], self.iter_items(node.args[0], sc, depth + 1)])]
            if fname == 'zip' and node.args:
                return [('t', [self.iter_items(a, sc, depth + 1) for a in node.args])]
            if fname in ('sorted', 'reversed', 'list', 'tuple', 'set', 'iter') and node.args:
                return self.iter_items(node.args[0], sc, depth + 1)
            if isinstance(f, ast.Attribute) and f.attr in ('items', 'keys', 'values') \
                    and not node.args:
                d = self._dict_node(f.value, sc, depth + 1)
                if d is not None:
                    dn, dsc = d
                    keys = [('n', k, dsc) for k in dn.keys if k is not None]
                    vals = [('n', v, dsc) for k, v in zip(dn.keys, dn.values) if k is not None]
                    if f.attr == 'keys':
                        return keys
                    if f.attr == 'values':
                        return vals
                    return [('t', [keys, vals])]
        if t is ast.Name:
            st = self.lookup_state(node.id, sc, _start(node))
            out = []
            if st is not None:
                for ent in st:
                    if ent[0] != 'b':
                        continue
                    b = ent[1]
                    if id(b) in self.inferring:
                        continue
                    if b.kind == 'assign':
                        self.inferring.add(id(b))
                        try:
                            out += self.iter_items(b.extra, b.scope, depth + 1)
                        finally:
                            self.inferring.discard(id(b))
                    elif b.kind == 'ann':
                        out += self._ann_items(b.extra[0], b.scope, depth)
                    elif b.kind == 'param' and b.node.annotation is not None:
                        out += self._ann_items(b.node.annotation, b.scope.parent, depth)
            if out:
                return out
        if t is ast.Attribute:
            out = []
            for v in self.infer(node.value, sc, None, depth + 1):
                if isinstance(v, (StInst, StClass)):
                    for b in self.attr_bindings(v, node.attr):
                        if b.kind == 'assign' and id(b) not in self.inferring:
                            self.inferring.add(id(b))
                            try:
                                out += self.iter_items(b.extra, b.scope, depth + 1)
                            finally:
                                self.inferring.discard(id(b))
                        elif b.kind == 'ann':
                            out += self._ann_items(b.extra[0], b.scope, depth)
            if out:
                return out
        out = []
        for v in self.infer(node, sc, None, depth + 1):
            if isinstance(v, RtV) and isinstance(v.obj, (str, bytes)):
                out.append(('v', RtV(type(v.obj)())))
            elif isinstance(v, StInst):
                for f in self.get_attr(v, '__iter__', depth + 1):
                    for it in self.call(f, None, depth + 1):
                        for g in self.get_attr(it, '__next__', depth + 1):
                            out += [('v', x) for x in self.call(g, None, depth + 1)]
        return out

    def _ann_items(self, ann, sc, depth):
        if isinstance(ann, ast.Subscript):
            sl = ann.slice
            if isinstance(sl, ast.Tuple) and sl.elts:
                sl = sl.elts[0]
            return [('v', v) for v in self.infer_annotation(sl, sc, depth + 1)]
        return []

    def _dict_node(self, node, sc, depth):
        if isinstance(node, ast.Dict):
            return node, sc
        if isinstance(node, ast.Name) and depth < MAX_DEPTH:
            st = self.lookup_state(node.id, sc, _start(node))
            if st is not None:
                for ent in st:
                    if ent[0] == 'b' and ent[1].kind == 'assign' and id(ent[1]) not in self.inferring:
                        self.inferring.add(id(ent[1]))
                        try:
                            r = self._dict_node(ent[1].extra, ent[1].scope, depth + 1)
                        finally:
                            self.inferring.discard(id(ent[1]))
                        if r is not None:
                            return r
        return None

    def _comp_scope(self, node, sc):
        for ch in self._all_children(sc):
            if ch.node is node:
                return ch
        return None

    def _all_children(self, sc):
        out = []
        stack = [sc]
        while stack:
            s = stack.pop()
            for ch in s.children:
                out.append(ch)
                if ch.kind in ('comp', 'lambda'):
                    stack.append(ch)
        return out

    def path_values(self, item, path, depth):
        if depth > MAX_DEPTH:
            return []
        kind = item[0]
        if not path:
            if kind == 'n':
                return self.infer(item[1], item[2], None, depth + 1)
            if kind == 'v':
                return [item[1]]
            return [RtV(())]
        i = path[0]
        if kind == 't':
            parts = item[1]
            if i < len(parts):
                out = []
                for sub in parts[i]:
                    out += self.path_values(sub, path[1:], depth + 1)
                return out
            return []
        if kind == 'n':
            node, sc = item[1], item[2]
            if isinstance(node, (ast.Tuple, ast.List)):
                if any(isinstance(e, ast.Starred) for e in node.elts) or i >= len(node.elts):
                    return []
                return self.path_values(('n', node.elts[i], sc), path[1:], depth + 1)
            if isinstance(node, ast.Name):
                st = self.lookup_state(node.id, sc, _start(node))
                out = []
                if st is not None:
                    for ent in st:
                        b = ent[1] if ent[0] == 'b' else None
                        if b is not None and b.kind == 'assign' and id(b) not in self.inferring:
                            self.inferring.add(id(b))
                            try:
                                out += self.path_values(('n', b.extra, b.scope), path, depth + 1)
                            finally:
                                self.inferring.discard(id(b))
                return out
            if isinstance(node, ast.Call):
                out = []
                for f in self.infer(node.func, sc, None, depth + 1):
                    if isinstance(f, StFunc):
                        out += self.return_paths(f, (node, sc, self.frames), path, depth + 1)
                return out
        return []

    def return_paths(self, f, args, path, depth):
        fnode, fs = f.node, f.scope
        key = id(fnode)
        if key in self.calling:
            return []
        mapping = self.bind_args(fnode, args, f.bound, f.skip)
        saved = self.frames
        self.frames = dict(saved)
        self.frames[id(fs)] = mapping
        self.calling.add(key)
        try:
            out = []
            for s in _iter_stmts(fnode.body):
                if isinstance(s, ast.Return) and s.value is not None:
                    out += self.path_values(('n', s.value, fs), path, depth + 1)
            return out
        finally:
            self.calling.discard(key)
            self.frames = saved

    # ----- params and calls -----

    def bind_args(self, fnode, args, bound, skip):
        m = {}
        a = fnode.args
        params = list(getattr(a, 'posonlyargs', [])) + list(a.args)
        if skip and params:
            if bound is not None:
                m[params[0].arg] = ('vals', [bound])
            params = params[1:]
        if args is None:
            return m
        cnode, csc, cframes = args
        names = set(p.arg for p in params) | set(p.arg for p in a.kwonlyargs)
        i = 0
        for x in cnode.args:
            if isinstance(x, ast.Starred):
                break
            if i < len(params):
                m[params[i].arg] = ('node', x, csc, cframes)
                i += 1
            else:
                break
        for kw in cnode.keywords:
            if kw.arg is not None and kw.arg in names:
                m[kw.arg] = ('node', kw.value, csc, cframes)
        return m

    def arg_values(self, ent, depth):
        if ent[0] == 'vals':
            return list(ent[1])
        _, node, sc, frames = ent
        saved = self.frames
        self.frames = frames
        try:
            return self.infer(node, sc, None, depth + 1)
        finally:
            self.frames = saved

    def param_values(self, b, depth):
        a = b.node
        fnode, idx, default = b.extra
        fs = b.scope
        outer = fs.parent
        fr = self.frames.get(id(fs))
        if fr is not None and a.arg in fr:
            vals = self.arg_values(fr[a.arg], depth)
            if vals:
                return vals
        if a.annotation is not None:
            vals = self.infer_annotation(a.annotation, outer, depth + 1)
            if a is fnode.args.vararg:
                return [RtV(())]
            if a is fnode.args.kwarg:
                return [RtV({})]
            if vals:
                return vals
        if a is fnode.args.vararg:
            return [RtV(())]
        if a is fnode.args.kwarg:
            return [RtV({})]
        if idx == 0 and isinstance(fnode, (ast.FunctionDef, ast.AsyncFunctionDef)) \
                and outer is not None and outer.kind == 'class':
            decos = _decorator_names(fnode)
            if 'staticmethod' in decos:
                pass
            elif 'classmethod' in decos or fnode.name in ('__new__', '__init_subclass__',
                                                          '__class_getitem__'):
                return [class_value(outer)]
            else:
                return [StInst(class_value(outer))]
        if default is not None:
            vals = self.infer(default, outer, None, depth + 1)
            if vals and not (len(vals) == 1 and isinstance(vals[0], RtV) and vals[0].obj is None):
                return vals
            dyn = self.dynamic_params(b, depth)
            return uniq(vals + dyn)
        return self.dynamic_params(b, depth)

    def dynamic_params(self, b, depth):
        """Infer a parameter from the call sites in its module."""
        a = b.node
        fnode, idx, default = b.extra
        fs = b.scope
        if not isinstance(fnode, (ast.FunctionDef, ast.AsyncFunctionDef)):
            return []
        if depth > MAX_DEPTH // 2:
            return []
        key = ('dyn', id(fnode))
        if key in self.calling:
            return []
        info = fs.module
        outer = fs.parent
        is_method = outer is not None and outer.kind == 'class'
        cls = class_value(outer) if is_method else None
        decos = _decorator_names(fnode)
        target_names = {fnode.name}
        if is_method and fnode.name == '__init__':
            target_names = {outer.node.name}
        self.calling.add(key)
        out = []
        try:
            count = 0
            for node in ast.walk(info.tree):
                if not isinstance(node, ast.Call):
                    continue
                f = node.func
                fname = f.id if isinstance(f, ast.Name) else (f.attr if isinstance(f, ast.Attribute)
                                                               else None)
                if fname not in target_names:
                    continue
                csc = info.node_scopes.get(id(node))
                if csc is None:
                    continue
                matched = None
                for fv in self.infer(f, csc, None, depth + 1):
                    if isinstance(fv, StFunc) and fv.node is fnode:
                        matched = fv
                        break
                    if isinstance(fv, StClass) and is_method and fnode.name == '__init__' \
                            and cls in self.mro(fv):
                        matched = StFunc(fnode, fs, None, True)
                        break
                if matched is None:
                    continue
                skip = matched.skip
                if is_method and 'staticmethod' not in decos and not skip and \
                        isinstance(f, ast.Attribute) and fnode.name != '__init__':
                    skip = True
                mapping = self.bind_args(fnode, (node, csc, self.frames), None, skip)
                if a.arg in mapping:
                    out += self.arg_values(mapping[a.arg], depth + 1)
                count += 1
                if count >= 8:
                    break
        finally:
            self.calling.discard(key)
        return uniq(out)

    def call(self, f, args, depth):
        if depth > MAX_DEPTH:
            return []
        if isinstance(f, StClass):
            return [StInst(f, args)]
        if isinstance(f, StFunc):
            return self.func_returns(f, args, depth)
        if isinstance(f, StInst):
            out = []
            for g in self.get_attr(f, '__call__', depth + 1):
                if isinstance(g, StFunc):
                    out += self.func_returns(g, args, depth + 1)
            return out
        if isinstance(f, RtV):
            o = f.obj
            if inspect.isclass(o):
                if o is type and args is not None and len(args[0].args) == 1:
                    out = []
                    for v in self.infer(args[0].args[0], args[1], None, depth + 1):
                        if isinstance(v, StInst):
                            out.append(v.cls)
                        elif isinstance(v, RtV) and kind_of(v) == 'instance':
                            out.append(RtV(type(v.obj)))
                        elif isinstance(v, RtInst):
                            out.append(RtV(v.cls))
                        elif isinstance(v, StFunc):
                            out.append(RtV(types.FunctionType))
                        elif isinstance(v, StClass):
                            out.append(RtV(type))
                        elif isinstance(v, StMod):
                            out.append(RtV(types.ModuleType))
                    if out:
                        return out
                return [rt_instance(o)]
            if getattr(o, '__module__', None) == 'builtins' or inspect.isbuiltin(o):
                name = getattr(o, '__name__', None)
                if name in _BUILTIN_RETURNS and getattr(builtins, name, None) is o:
                    return [rt_instance(_BUILTIN_RETURNS[name])]
                cargs = args[0].args if args is not None else []
                if args is not None and getattr(builtins, name or '', None) is o:
                    csc = args[1]
                    if name == 'abs' and cargs:
                        return self.infer(cargs[0], csc, None, depth + 1)
                    if name in ('min', 'max') and cargs:
                        if len(cargs) == 1:
                            out = []
                            for item in self.iter_items(cargs[0], csc, depth + 1):
                                out += self.path_values(item, (), depth + 1)
                            return out
                        out = []
                        for x in cargs:
                            out += self.infer(x, csc, None, depth + 1)
                        return out
                    if name == 'getattr' and len(cargs) >= 2 and \
                            isinstance(cargs[1], ast.Constant) and isinstance(cargs[1].value, str):
                        out = []
                        for x in self.infer(cargs[0], csc, None, depth + 1):
                            out += self.get_attr(x, cargs[1].value, depth + 1)
                        if len(cargs) > 2:
                            out += self.infer(cargs[2], csc, None, depth + 1)
                        return out
                    if name == 'next' and cargs:
                        out = []
                        for item in self.iter_items(cargs[0], csc, depth + 1):
                            out += self.path_values(item, (), depth + 1)
                        return out
                owner = getattr(o, '__self__', None)
                if isinstance(owner, str) and name in _STR_RETURNS:
                    return [rt_instance(_STR_RETURNS[name])]
                if isinstance(owner, (list, dict, set)) and name in ('append', 'extend', 'insert',
                                                                     'clear', 'update', 'add',
                                                                     'remove', 'sort', 'reverse',
                                                                     'discard'):
                    return [RtV(None)]
                if isinstance(owner, (list, dict, set)) and name == 'copy':
                    return [rt_instance(type(owner))]
                if o is getattr(builtins, 'open', None):
                    return [RtInst(io.TextIOWrapper)]
            return []
        return []

    def func_returns(self, f, args, depth):
        fnode, fs = f.node, f.scope
        key = id(fnode)
        if key in self.calling:
            return []
        if isinstance(fnode, ast.Lambda):
            mapping = self.bind_args(fnode, args, f.bound, f.skip)
            saved = self.frames
            self.frames = dict(saved)
            self.frames[id(fs)] = mapping
            self.calling.add(key)
            try:
                return self.infer(fnode.body, fs, None, depth + 1)
            finally:
                self.calling.discard(key)
                self.frames = saved
        if fnode.returns is not None:
            vals = self.infer_annotation(fnode.returns, fs.parent, depth + 1)
            if vals:
                return vals
        if _has_yield(fnode):
            return [RtV(_sample_generator())]
        mapping = self.bind_args(fnode, args, f.bound, f.skip)
        saved = self.frames
        self.frames = dict(saved)
        self.frames[id(fs)] = mapping
        self.calling.add(key)
        try:
            vals = []
            has_value = False
            for s in _iter_stmts(fnode.body):
                if isinstance(s, ast.Return) and s.value is not None:
                    has_value = True
                    vals += self.infer(s.value, fs, None, depth + 1)
            if not has_value:
                vals = [RtV(None)]
            return uniq(vals)
        finally:
            self.calling.discard(key)
            self.frames = saved

    # ----- expressions -----

    def infer_annotation(self, node, sc, depth=0, pos=None):
        if node is None or depth > MAX_DEPTH:
            return []
        t = type(node)
        if t is ast.Constant:
            if node.value is None:
                return [RtV(None)]
            if isinstance(node.value, str):
                try:
                    sub = ast.parse(node.value.strip(), mode='eval').body
                except (SyntaxError, ValueError, RecursionError):
                    return []
                return self.infer_annotation(sub, sc, depth + 1, _start(node))
            return []
        if t is ast.BinOp and isinstance(node.op, ast.BitOr):
            return uniq(self.infer_annotation(node.left, sc, depth + 1, pos) +
                        self.infer_annotation(node.right, sc, depth + 1, pos))
        if t is ast.Subscript:
            base = node.value
            bname = base.id if isinstance(base, ast.Name) else \
                (base.attr if isinstance(base, ast.Attribute) else None)
            sl = node.slice
            elts = sl.elts if isinstance(sl, ast.Tuple) else [sl]
            if bname == 'Optional':
                return uniq(self.infer_annotation(elts[0], sc, depth + 1, pos) + [RtV(None)])
            if bname == 'Union':
                out = []
                for e in elts:
                    out += self.infer_annotation(e, sc, depth + 1, pos)
                return uniq(out)
            if bname in ('Annotated', 'Final', 'ClassVar', 'Required', 'NotRequired'):
                return self.infer_annotation(elts[0], sc, depth + 1, pos)
            if bname in ('Type', 'type'):
                return [v for v in self.infer(elts[0], sc, pos, depth + 1)
                        if kind_of(v) == 'class']
            node = base
        out = []
        for v in self.infer(node, sc, pos, depth + 1):
            if isinstance(v, RtV) and v.obj is None:
                out.append(v)
                continue
            if isinstance(v, RtV) and not inspect.isclass(v.obj):
                origin = getattr(v.obj, '__origin__', None)
                if inspect.isclass(origin):
                    out.append(rt_instance(origin))
                    continue
                o = v.obj
                name = getattr(o, '_name', None) or getattr(o, '__name__', None)
                mapped = {'List': list, 'Dict': dict, 'Set': set, 'Tuple': tuple,
                          'FrozenSet': frozenset, 'Callable': None}.get(name)
                if mapped is not None:
                    out.append(rt_instance(mapped))
                continue
            out.append(instantiate(v))
        return uniq(out)

    def infer(self, node, sc, pos=None, depth=0):
        if node is None or depth > MAX_DEPTH:
            return []
        self.steps += 1
        if self.steps > self.max_steps:
            return []
        try:
            return uniq(self._infer(node, sc, pos, depth))
        except RecursionError:
            return []

    def _infer(self, node, sc, pos, depth):
        t = type(node)
        if t is ast.Constant:
            if node.value is Ellipsis:
                return [RtV(Ellipsis)]
            return [RtV(node.value)]
        if t is ast.JoinedStr:
            return [RtV('')]
        if t in (ast.List, ast.ListComp):
            return [RtV([])]
        if t is ast.Tuple:
            return [RtV(())]
        if t in (ast.Dict, ast.DictComp):
            return [RtV({})]
        if t in (ast.Set, ast.SetComp):
            return [RtV(set())]
        if t is ast.GeneratorExp:
            return [RtV(_sample_generator())]
        if t is ast.Lambda:
            for ch in sc.children:
                if ch.node is node:
                    return [StFunc(node, ch)]
            return [RtV(lambda: None)]
        if t is ast.Name:
            return self.lookup_values(node.id, sc, pos or _start(node), depth + 1)
        if t is ast.Attribute:
            out = []
            for base in self.infer(node.value, sc, pos, depth + 1):
                out += self.get_attr(base, node.attr, depth + 1)
            return out
        if t is ast.Call:
            if isinstance(node.func, ast.Name) and node.func.id == 'super' and not node.args:
                s = sc
                while s is not None and s.kind != 'function':
                    s = s.parent
                if s is not None and s.parent is not None and s.parent.kind == 'class':
                    sv = self.lookup_values('super', sc, pos or _start(node), depth + 1)
                    if any(isinstance(v, RtV) and v.obj is super for v in sv):
                        return [SuperInst(class_value(s.parent))]
            out = []
            args = (node, sc, self.frames)
            for f in self.infer(node.func, sc, pos, depth + 1):
                out += self.call(f, args, depth + 1)
            return out
        if t is ast.NamedExpr:
            return self.infer(node.value, sc, pos, depth + 1)
        if t is ast.Await:
            return []
        if t is ast.Compare:
            return [RtV(False)]
        if t is ast.Subscript:
            out = []
            for v in self.infer(node.value, sc, pos, depth + 1):
                if isinstance(v, RtV) and isinstance(v.obj, (str, bytes)):
                    out.append(RtV(type(v.obj)()))
                elif isinstance(v, StInst):
                    for g in self.get_attr(v, '__getitem__', depth + 1):
                        out += self.call(g, None, depth + 1)
            if not out:
                out = self.subscript_items(node, sc, depth)
            return out
        if t is ast.UnaryOp:
            if isinstance(node.op, ast.Not):
                return [RtV(False)]
            out = []
            for v in self.infer(node.operand, sc, pos, depth + 1):
                s = self._sample(v)
                if s is _NOSAMPLE:
                    continue
                try:
                    ops = {ast.USub: lambda x: -x, ast.UAdd: lambda x: +x,
                           ast.Invert: lambda x: ~x}
                    out.append(RtV(ops[type(node.op)](s)))
                except Exception:
                    pass
            return out
        if t is ast.BinOp:
            lvals = self.infer(node.left, sc, pos, depth + 1)
            rvals = self.infer(node.right, sc, pos, depth + 1)
            out = []
            for lv in lvals:
                if isinstance(lv, StInst):
                    dn = _DUNDERS.get(type(node.op))
                    if dn:
                        for g in self.get_attr(lv, dn, depth + 1):
                            out += self.call(g, None, depth + 1)
                    continue
                ls = self._sample(lv)
                if ls is _NOSAMPLE:
                    continue
                for rv in rvals:
                    rs = self._sample(rv)
                    if rs is _NOSAMPLE:
                        continue
                    r = self._binop(node.op, ls, rs)
                    if r is not None:
                        out.append(r)
            return out
        if t is ast.BoolOp:
            out = []
            for v in node.values:
                out += self.infer(v, sc, pos, depth + 1)
            return out
        if t is ast.IfExp:
            return self.infer(node.body, sc, pos, depth + 1) + \
                self.infer(node.orelse, sc, pos, depth + 1)
        return []

    def subscript_items(self, node, sc, depth):
        """Element inference for subscripts of literal containers."""
        base = node.value
        lit = None
        if isinstance(base, (ast.List, ast.Tuple, ast.Dict)):
            lit = (base, sc)
        elif isinstance(base, ast.Name):
            st = self.lookup_state(base.id, sc, _start(base))
            if st is not None:
                for ent in st:
                    if ent[0] == 'b' and ent[1].kind == 'assign' and \
                            isinstance(ent[1].extra, (ast.List, ast.Tuple, ast.Dict)):
                        lit = (ent[1].extra, ent[1].scope)
                        break
        if lit is None:
            return []
        ln, lsc = lit
        sl = node.slice
        if isinstance(ln, ast.Dict):
            if isinstance(sl, ast.Constant):
                for k, v in zip(ln.keys, ln.values):
                    if isinstance(k, ast.Constant) and k.value == sl.value:
                        return self.infer(v, lsc, None, depth + 1)
            out = []
            for v in ln.values:
                out += self.infer(v, lsc, None, depth + 1)
            return out
        if isinstance(sl, ast.Slice):
            return [RtV([] if isinstance(ln, ast.List) else ())]
        if any(isinstance(e, ast.Starred) for e in ln.elts):
            return []
        if isinstance(sl, ast.Constant) and isinstance(sl.value, int) and \
                not isinstance(sl.value, bool):
            try:
                return self.infer(ln.elts[sl.value], lsc, None, depth + 1)
            except IndexError:
                return []
        out = []
        for e in ln.elts:
            out += self.infer(e, lsc, None, depth + 1)
        return out

    def _sample(self, v):
        if isinstance(v, RtV) and type(v.obj) in _NUM_SAMPLES:
            return _NUM_SAMPLES[type(v.obj)]
        if isinstance(v, RtInst) and v.cls in _NUM_SAMPLES:
            return _NUM_SAMPLES[v.cls]
        return _NOSAMPLE

    def _binop(self, op, lv, rv):
        f = _BINOPS.get(type(op))
        if f is None:
            return None
        try:
            return RtV(f(lv, rv))
        except Exception:
            return None

    # ----- attributes -----

    def bind_member(self, v, owner, cls, depth):
        """Adjust a class attribute value for access through `owner`."""
        if not isinstance(v, StFunc) or isinstance(v.node, ast.Lambda):
            return [v]
        decos = _decorator_names(v.node)
        if 'staticmethod' in decos:
            return [StFunc(v.node, v.scope)]
        if 'classmethod' in decos:
            return [StFunc(v.node, v.scope, cls, True)]
        if isinstance(owner, (StInst, SuperInst)):
            inst = owner if isinstance(owner, StInst) else StInst(owner.cls)
            if decos & {'property', 'cached_property'}:
                return self.func_returns(StFunc(v.node, v.scope, inst, True), None, depth + 1)
            return [StFunc(v.node, v.scope, inst, True)]
        return [v]

    def get_attr(self, v, name, depth=0):
        if v is None or depth > MAX_DEPTH:
            return []
        if isinstance(v, RtV):
            try:
                with warnings.catch_warnings():
                    warnings.simplefilter('ignore')
                    return [RtV(getattr(v.obj, name))]
            except BaseException:
                if inspect.ismodule(v.obj):
                    m = self.rt_import(v.obj.__name__ + '.' + name)
                    if m is not None:
                        return [RtV(m)]
                return []
        if isinstance(v, RtInst):
            try:
                return [RtV(getattr(v.cls, name))]
            except BaseException:
                return []
        if isinstance(v, StMod):
            if v.info is not None:
                ents = self.scope_end_entries(v.info.scope, name)
                if ents:
                    vals = self.entries_values(ents, depth + 1)
                    if vals or not v.pkgdir:
                        return vals
            if v.pkgdir:
                found = self.find_local(name, v.pkgdir)
                if found:
                    return [self.static_module(found, (v.name + '.' + name).strip('.'))]
            return []
        if isinstance(v, (StInst, SuperInst)):
            classes = self.mro(v.cls)
            if isinstance(v, SuperInst):
                classes = classes[1:]
                inst = StInst(v.cls)
            else:
                inst = v
            for c in classes:
                bl = self.self_attr_map(c).get(name)
                if bl:
                    vals = []
                    for b in bl:
                        vals += self.self_attr_values(inst, b, depth + 1)
                    vals = uniq(vals)
                    if vals:
                        return vals
                    break
            for c in classes:
                if name in c.scope.bindings:
                    out = []
                    for val in self.entries_values(self.scope_end_entries(c.scope, name), depth + 1):
                        out += self.bind_member(val, v, c, depth)
                    return uniq(out)
            return []
        if isinstance(v, StClass):
            for c in self.mro(v):
                if name in c.scope.bindings:
                    out = []
                    for val in self.entries_values(self.scope_end_entries(c.scope, name), depth + 1):
                        out += self.bind_member(val, v, v, depth)
                    return uniq(out)
            return []
        if isinstance(v, StFunc):
            try:
                return [RtV(getattr(_sample_function, name))]
            except AttributeError:
                return []
        return []

    def self_attr_values(self, inst, b, depth):
        fs = b.scope
        fnode = fs.node
        args = inst.args if fnode.name == '__init__' else None
        mapping = self.bind_args(fnode, args, inst, True)
        saved = self.frames
        self.frames = dict(saved)
        self.frames[id(fs)] = mapping
        try:
            return self.binding_values(b, depth)
        finally:
            self.frames = saved

    def attr_bindings(self, v, name):
        """Bindings defining attribute `name` on a static class/instance."""
        if isinstance(v, (StInst, SuperInst)):
            classes = self.mro(v.cls)
            if isinstance(v, SuperInst):
                classes = classes[1:]
            for c in classes:
                bl = self.self_attr_map(c).get(name)
                if bl:
                    return list(bl)
            v = None
        else:
            classes = self.mro(v) if isinstance(v, StClass) else []
        for c in classes:
            if name in c.scope.bindings:
                return [e[1] for e in self.scope_end_entries(c.scope, name) if e[0] == 'b']
        if v is None:
            for c in classes:
                bl = self.self_aug_map(c).get(name)
                if bl:
                    return list(bl)
        return []

    def mro(self, cls, visiting=None):
        if visiting is None:
            visiting = set()
        if id(cls) in visiting:
            return []
        visiting.add(id(cls))
        out = [cls]
        for base in self.bases(cls):
            for c in self.mro(base, visiting):
                if c not in out:
                    out.append(c)
        return out

    def bases(self, cls):
        sc = cls.scope
        if sc._bases is None:
            sc._bases = []
            res = []
            for bnode in sc.node.bases:
                for v in self.infer(bnode, sc.parent, None):
                    if isinstance(v, StClass) and v is not cls:
                        res.append(v)
            sc._bases = res
        return sc._bases

    def class_attrs(self, classes):
        d = {}
        for c in reversed(classes):
            for n, lst in c.scope.bindings.items():
                if MARK in n:
                    continue
                d[n] = ('b', max(lst, key=lambda x: x.line))
        return d

    def self_attr_map(self, cls):
        sc = cls.scope
        if sc._self_attrs is not None:
            return sc._self_attrs
        sc._self_attrs = {}
        sc._self_aug = {}
        res = {}
        augs = {}
        info = sc.module
        methods = []
        for s in _iter_stmts(sc.node.body):
            if isinstance(s, (ast.FunctionDef, ast.AsyncFunctionDef)):
                methods.append(s)
        methods.sort(key=lambda m: 0 if m.name == '__init__' else 1)
        fscopes = {id(ch.node): ch for ch in sc.children}
        for fnode in methods:
            fs = fscopes.get(id(fnode))
            if fs is None:
                continue
            decos = _decorator_names(fnode)
            if 'staticmethod' in decos or 'classmethod' in decos:
                continue
            positional = list(getattr(fnode.args, 'posonlyargs', [])) + list(fnode.args.args)
            if not positional:
                continue
            selfname = positional[0].arg
            aug = {}
            for s in _iter_stmts(fnode.body):
                if isinstance(s, ast.Assign):
                    for tgt in s.targets:
                        self._collect_self(tgt, selfname, s.value, (), fs, res, s, info)
                elif isinstance(s, ast.AnnAssign):
                    tgt = s.target
                    if self._is_self_attr(tgt, selfname):
                        nb = self._self_binding(tgt, 'ann', (s.annotation, s.value), fs, s, info)
                        res.setdefault(tgt.attr, []).append(nb)
                elif isinstance(s, ast.AugAssign):
                    tgt = s.target
                    if self._is_self_attr(tgt, selfname):
                        nb = self._self_binding(tgt, 'stmt', None, fs, s, info)
                        aug.setdefault(tgt.attr, nb)
            for n, nb in aug.items():
                augs.setdefault(n, [nb])
        sc._self_attrs = {n: bl for n, bl in res.items() if MARK not in n}
        sc._self_aug = {n: bl for n, bl in augs.items() if MARK not in n and n not in res}
        return sc._self_attrs

    def self_aug_map(self, cls):
        self.self_attr_map(cls)
        return cls.scope._self_aug

    def self_attrs(self, cls):
        return {n: ('b', bl[0]) for n, bl in self.self_attr_map(cls).items()}

    def _is_self_attr(self, tgt, selfname):
        return isinstance(tgt, ast.Attribute) and isinstance(tgt.value, ast.Name) \
            and tgt.value.id == selfname

    def _self_binding(self, tgt, kind, extra, fs, stmt, info):
        ln = tgt.end_lineno
        col = _char_col(info.lines, ln, tgt.end_col_offset) - len(tgt.attr)
        nb = Binding(tgt.attr, tgt.lineno, kind, tgt, extra, (ln, col))
        nb.scope = fs
        nb.stmt = stmt
        nb.attr = True
        return nb

    def _collect_self(self, tgt, selfname, value, path, fs, res, stmt, info):
        if self._is_self_attr(tgt, selfname):
            if path:
                nb = self._self_binding(tgt, 'unpack', (value, path), fs, stmt, info)
            else:
                nb = self._self_binding(tgt, 'assign', value, fs, stmt, info)
            res.setdefault(tgt.attr, []).append(nb)
        elif isinstance(tgt, (ast.Tuple, ast.List)):
            for i, e in enumerate(tgt.elts):
                if not isinstance(e, ast.Starred):
                    self._collect_self(e, selfname, value, path + (i,), fs, res, stmt, info)

    def attributes(self, v):
        """Return dict name -> entry for attribute completion on value v."""
        out = {}
        if v is None:
            return out
        if isinstance(v, RtV):
            o = v.obj
            try:
                names = dir(o)
            except Exception:
                names = []
            pub = inspect.ismodule(o)
            for n in names:
                if pub and n.startswith('_'):
                    continue
                out[n] = self._rt_attr_entry(o, n)
            return out
        if isinstance(v, RtInst):
            try:
                names = dir(v.cls)
            except Exception:
                names = []
            for n in names:
                out[n] = self._rt_attr_entry(v.cls, n)
            return out
        if isinstance(v, StMod):
            if v.info is not None:
                out.update(self.module_entries(v.info))
            if v.pkgdir:
                try:
                    listing = sorted(os.listdir(v.pkgdir))
                except OSError:
                    listing = []
                for fn in listing:
                    full = os.path.join(v.pkgdir, fn)
                    if fn.endswith('.py') and os.path.isfile(full):
                        sub = fn[:-3]
                    elif os.path.isfile(os.path.join(full, '__init__.py')):
                        sub = fn
                    else:
                        continue
                    if sub.startswith('_') or not sub.isidentifier() or sub in out:
                        continue
                    out[sub] = ('v', lambda s=sub: (self.get_attr(v, s) or [None])[0])
            return out
        if isinstance(v, StClass):
            return self.class_attrs(self.mro(v))
        if isinstance(v, (StInst, SuperInst)):
            classes = self.mro(v.cls)
            if isinstance(v, SuperInst):
                classes = classes[1:]
            out = self.class_attrs(classes)
            for c in reversed(classes):
                for n in self.self_aug_map(c):
                    out.setdefault(n, ('v', lambda n=n: (self.get_attr(v, n) or [None])[0]))
                for n in self.self_attr_map(c):
                    out[n] = ('v', lambda n=n: (self.get_attr(v, n) or [None])[0])
            return out
        if isinstance(v, StFunc):
            for n in dir(_sample_function):
                out[n] = self._rt_attr_entry(_sample_function, n)
            return out
        return out


_NOSAMPLE = object()
_NUM_SAMPLES = {int: 1, float: 1.0, complex: 1j, bool: True, str: '', bytes: b'',
                list: [], tuple: (), dict: {}, set: set(), frozenset: frozenset()}
_BINOPS = {
    ast.Add: lambda a, b: a + b, ast.Sub: lambda a, b: a - b, ast.Mult: lambda a, b: a * b,
    ast.Div: lambda a, b: a / b, ast.FloorDiv: lambda a, b: a // b,
    ast.Mod: lambda a, b: a % b, ast.Pow: lambda a, b: a ** b,
    ast.LShift: lambda a, b: a << b, ast.RShift: lambda a, b: a >> b,
    ast.BitOr: lambda a, b: a | b, ast.BitXor: lambda a, b: a ^ b,
    ast.BitAnd: lambda a, b: a & b,
}
_DUNDERS = {
    ast.Add: '__add__', ast.Sub: '__sub__', ast.Mult: '__mul__', ast.Div: '__truediv__',
    ast.FloorDiv: '__floordiv__', ast.Mod: '__mod__', ast.Pow: '__pow__',
    ast.MatMult: '__matmul__', ast.BitOr: '__or__', ast.BitAnd: '__and__',
    ast.BitXor: '__xor__', ast.LShift: '__lshift__', ast.RShift: '__rshift__',
}


# ---------------------------------------------------------------------------
# Cursor context
# ---------------------------------------------------------------------------

def is_ident_char(c):
    return c == '_' or c.isalnum()


def in_comment_or_string(text, n):
    i = 0
    while i < n:
        c = text[i]
        if c == '#':
            j = text.find('\n', i)
            if j == -1 or j >= n:
                return True
            i = j + 1
            continue
        if c in '"\'':
            if text.startswith(c * 3, i):
                q = c * 3
                i += 3
                while True:
                    if i >= n:
                        return True
                    if text[i] == '\\':
                        i += 2
                        continue
                    if text.startswith(q, i):
                        i += 3
                        if i > n:
                            return True
                        break
                    i += 1
            else:
                i += 1
                while True:
                    if i >= n:
                        return True
                    ch = text[i]
                    if ch == '\\':
                        i += 2
                        continue
                    if ch == '\n':
                        break
                    i += 1
                    if ch == c:
                        break
            continue
        i += 1
    return False


def _match_back(text, i):
    """text[i] is a closing bracket; return index of matching opener or -1."""
    depth = 0
    while i >= 0:
        c = text[i]
        if c in ')]}':
            depth += 1
        elif c in '([{':
            depth -= 1
            if depth == 0:
                return i
        i -= 1
    return -1


def extract_expr(text, end):
    """Extract the primary expression ending right before text[end] (a '.')."""
    i = end
    while i > 0 and text[i - 1] in ' \t':
        i -= 1
    start = i
    while i > 0:
        c = text[i - 1]
        group = False
        if is_ident_char(c):
            j = i
            while j > 0 and is_ident_char(text[j - 1]):
                j -= 1
            i = j
        elif c in ')]}':
            j = _match_back(text, i - 1)
            if j < 0:
                return ''
            i = j
            group = True
        elif c in '"\'':
            q = c * 3 if i >= 3 and text[i - 3:i] == c * 3 else c
            j = text.rfind(q, 0, i - len(q))
            while j > 0 and text[j - 1] == '\\' and len(q) == 1:
                j = text.rfind(q, 0, j)
            if j < 0:
                return ''
            i = j
            k = 0
            while k < 2 and i > 0 and text[i - 1] in 'rRbBuUfF':
                i -= 1
                k += 1
            group = True
        else:
            break
        start = i
        if i > 0 and text[i - 1] == '.':
            if i > 1 and text[i - 2] == '.':
                break
            i -= 1
            while i > 0 and text[i - 1] in ' \t':
                i -= 1
            continue
        if group and i > 0 and (is_ident_char(text[i - 1]) or text[i - 1] in ')]"\''):
            continue
        break
    return text[start:end]


def find_scope_by_pos(sc, line, bcol, lines, before):
    for ch in sc.children:
        if _contains(ch, line, bcol, lines, before):
            return find_scope_by_pos(ch, line, bcol, lines, before)
    return sc


def _contains(sc, line, bcol, lines, before):
    node = sc.node
    pos = (line, bcol)
    end = (getattr(node, 'end_lineno', node.lineno), getattr(node, 'end_col_offset', 0))
    if sc.kind in ('function', 'class'):
        if not node.body:
            return False
        b = node.body[0]
        src = lines[b.lineno - 1].encode('utf-8') if b.lineno - 1 < len(lines) else b''
        if src[:b.col_offset].strip() == b'':
            start = (b.lineno, 0)
        else:
            start = (b.lineno, b.col_offset)
        if start <= pos <= end:
            return True
        if line > end[0] and before.strip() == '' and \
                len(before.expandtabs(8)) > node.col_offset:
            for k in range(end[0], line - 1):
                t = lines[k].strip() if k < len(lines) else ''
                if t and not t.startswith('#'):
                    return False
            return True
        return False
    if sc.kind == 'lambda':
        b = node.body
        return (b.lineno, b.col_offset) <= pos <= end
    return (node.lineno, node.col_offset) < pos < end


def match_name(name, prefix, fuzzy):
    if not prefix:
        return True
    n = name.lower()
    p = prefix.lower()
    if not fuzzy:
        return n.startswith(p)
    it = iter(n)
    return all(c in it for c in p)


def sort_key(item):
    name, typ = item['name'], item['type']
    if typ == 'keyword':
        g = 3
    elif name.startswith('__') and name.endswith('__'):
        g = 2
    elif name.startswith('_'):
        g = 1
    else:
        g = 0
    return (g, name.lower(), name)



def read_source(path):
    if not os.path.isfile(path):
        raise SithError('file not found or not a regular file: %s' % path)
    try:
        with open(path, 'rb') as f:
            raw = f.read()
    except OSError as e:
        raise SithError('cannot read file: %s' % e)
    try:
        text = raw.decode('utf-8')
    except UnicodeDecodeError:
        raise SithError('file is not valid UTF-8')
    if text.startswith('\ufeff'):
        text = text[1:]
    return text.replace('\r\n', '\n').replace('\r', '\n')


def complete(path, line, col, fuzzy=False):
    text = read_source(path)
    lines = text.split('\n')
    if line < 1 or line > len(lines):
        raise SithError('line out of range')
    cl = lines[line - 1]
    if col < 0 or col > len(cl):
        raise SithError('column out of range')

    offset = sum(len(lines[k]) + 1 for k in range(line - 1)) + col
    if in_comment_or_string(text, offset):
        return []

    i = col
    while i > 0 and is_ident_char(cl[i - 1]):
        i -= 1
    prefix = cl[i:col]
    if prefix and prefix[0].isdigit():
        return []
    j = i
    while j > 0 and cl[j - 1] in ' \t':
        j -= 1
    is_attr = j > 0 and cl[j - 1] == '.'

    engine = Engine(os.path.dirname(os.path.abspath(path)))
    tree = parse_source(text, (line, col))
    info = ModuleInfo(os.path.abspath(path), tree, '__main__', text)
    engine.static_cache[os.path.realpath(path)] = info
    sc = info.cursor_scope
    bcol = len(cl[:col].encode('utf-8'))
    if sc is None:
        sc = find_scope_by_pos(info.scope, line, bcol, lines, cl[:col])

    results = []
    if is_attr:
        dot = offset - (col - (j - 1))
        expr = extract_expr(text, dot).strip()
        if not expr or expr.isdigit():
            return []
        node = None
        for cand in (expr, '(' + expr + ')'):
            try:
                node = ast.parse(cand, mode='eval').body
                break
            except (SyntaxError, ValueError, RecursionError):
                continue
        if node is None:
            return []
        entries = {}
        for v in engine.infer(node, sc, (line, bcol)):
            for n, ent in engine.attributes(v).items():
                entries.setdefault(n, ent)
        for n, ent in entries.items():
            if MARK in n or not match_name(n, prefix, fuzzy):
                continue
            typ, desc = engine.describe_entry(n, ent)
            results.append({'name': n, 'complete': n[len(prefix):], 'type': typ,
                            'description': desc})
    else:
        entries = engine.visible(sc, line)
        for n, ent in entries.items():
            if not match_name(n, prefix, fuzzy):
                continue
            typ, desc = engine.describe_entry(n, ent)
            results.append({'name': n, 'complete': n[len(prefix):], 'type': typ,
                            'description': desc})
        for kw in KEYWORDS:
            if match_name(kw, prefix, fuzzy):
                results.append({'name': kw, 'complete': kw[len(prefix):], 'type': 'keyword',
                                'description': kw})
    results.sort(key=sort_key)
    return results


# ---------------------------------------------------------------------------
# Definitions (infer / goto)
# ---------------------------------------------------------------------------

class NotAName(SithError):
    pass


def _doc(node):
    try:
        return ast.get_docstring(node) or ''
    except Exception:
        return ''


def _rt_doc(o):
    d = getattr(o, '__doc__', None)
    if isinstance(d, str):
        return inspect.cleandoc(d)
    return ''


class Navigator:
    def __init__(self, engine, root):
        self.e = engine
        self.root = os.path.abspath(root)

    # ----- naming -----

    def rel(self, path):
        ap = os.path.abspath(path)
        try:
            rp = os.path.relpath(ap, self.root)
        except ValueError:
            return ap
        if rp == '..' or rp.startswith('..' + os.sep):
            return ap
        return rp

    def modname(self, info):
        path = info.path
        rp = self.rel(path)
        if os.path.isabs(rp):
            base = os.path.basename(path)
            if base == '__init__.py':
                return os.path.basename(os.path.dirname(path))
            return base[:-3] if base.endswith('.py') else base
        if rp.endswith('.py'):
            rp = rp[:-3]
        parts = rp.split(os.sep)
        if parts[-1] == '__init__' and len(parts) > 1:
            parts.pop()
        return '.'.join(parts)

    def qual(self, sc, name):
        parts = []
        s = sc
        while s is not None and s.kind != 'module':
            if s.kind in ('function', 'class'):
                parts.append(s.node.name)
            s = s.parent
        mod = self.modname(s.module) if s is not None else ''
        return '.'.join(p for p in [mod] + parts[::-1] + [name] if p)

    def seg(self, info, node):
        try:
            s = ast.get_source_segment(info.text, node)
        except Exception:
            s = None
        if s is None:
            s = _unparse(node)
        return _ws(s)

    @staticmethod
    def mk(name, typ, full, mp, line, col, desc, doc):
        return {'name': name, 'type': typ, 'full_name': full, 'module_path': mp,
                'line': line, 'column': col, 'description': desc, 'docstring': doc or ''}

    # ----- static values -----

    def class_def(self, cls, typ='class'):
        sc = cls.scope
        node = sc.node
        info = sc.module
        line, col = _def_name_pos(info.lines, node)
        desc = ('class ' if typ == 'class' else 'instance of ') + node.name
        return self.mk(node.name, typ, self.qual(sc.parent, node.name), self.rel(info.path),
                       line, col, desc, _doc(node))

    def func_def(self, f):
        node = f.node
        info = f.scope.module
        if isinstance(node, ast.Lambda):
            line = node.lineno
            col = _char_col(info.lines, line, node.col_offset)
            return self.mk('<lambda>', 'function', self.qual(f.scope.parent, '<lambda>'),
                           self.rel(info.path), line, col,
                           'lambda %s' % _params_text(node.args), '')
        line, col = _def_name_pos(info.lines, node)
        return self.mk(node.name, 'function', self.qual(f.scope.parent, node.name),
                       self.rel(info.path), line, col,
                       'def %s(%s)' % (node.name, _params_text(node.args)), _doc(node))

    def module_def(self, mv):
        if mv.info is not None:
            full = self.modname(mv.info)
            name = full.split('.')[-1]
            return self.mk(name, 'module', full, self.rel(mv.info.path), 1, 0,
                           'module ' + name, _doc(mv.info.tree))
        if mv.pkgdir:
            full = mv.name or os.path.basename(mv.pkgdir)
            name = full.split('.')[-1]
            return self.mk(name, 'module', full, self.rel(mv.pkgdir), 1, 0, 'module ' + name, '')
        return None

    # ----- runtime values -----

    def rt_loc(self, o):
        mod = getattr(o, '__module__', None)
        if not isinstance(mod, str) or mod == 'builtins':
            return '', 0, 0
        try:
            f = inspect.getsourcefile(o)
            src, ln = inspect.getsourcelines(o)
        except Exception:
            return '', 0, 0
        if not f:
            return '', 0, 0
        name = getattr(o, '__name__', '')
        pat = re.compile(r'\s*(?:async\s+)?(?:def|class)\s+' + re.escape(name) + r'\b')
        for k, t in enumerate(src):
            m = pat.match(t)
            if m:
                return self.rel(f), ln + k, m.end() - len(name)
        return self.rel(f), max(ln, 1), 0

    def rt_full(self, o):
        mod = getattr(o, '__module__', None)
        if not isinstance(mod, str):
            oc = getattr(o, '__objclass__', None)
            mod = getattr(oc, '__module__', None) if oc is not None else None
        qn = getattr(o, '__qualname__', None) or getattr(o, '__name__', '')
        if isinstance(mod, str) and mod:
            return mod + '.' + qn
        return qn

    def rt_class_def(self, cls, typ='class'):
        name = getattr(cls, '__name__', 'object')
        mp, line, col = self.rt_loc(cls)
        doc = _rt_doc(cls) if mp else ''
        desc = ('class ' if typ == 'class' else 'instance of ') + name
        return self.mk(name, typ, self.rt_full(cls), mp, line, col, desc, doc)

    def rt_func_def(self, o):
        f = o
        if isinstance(o, _ROUTINE_TYPES):
            f = o.__func__
        name = getattr(f, '__name__', '') or ''
        try:
            sig = inspect.signature(f)
            sig = sig.replace(return_annotation=inspect.Signature.empty)
            params = str(sig)[1:-1]
        except (TypeError, ValueError):
            params = '...'
        mp, line, col = self.rt_loc(f)
        doc = _rt_doc(f) if mp else ''
        return self.mk(name, 'function', self.rt_full(f), mp, line, col,
                       'def %s(%s)' % (name, params), doc)

    def rt_module_def(self, o):
        full = getattr(o, '__name__', '') or ''
        name = full.split('.')[-1]
        f = getattr(o, '__file__', None)
        if isinstance(f, str) and f.endswith('.pyc'):
            try:
                import importlib.util as _iu
                f = _iu.source_from_cache(f)
            except Exception:
                pass
        if isinstance(f, str) and f.endswith('.py') and os.path.isfile(f):
            return self.mk(name, 'module', full, self.rel(f), 1, 0, 'module ' + name, _rt_doc(o))
        return self.mk(name, 'module', full, '', 0, 0, 'module ' + name, '')

    def value_defs(self, v):
        if isinstance(v, StClass):
            return [self.class_def(v)]
        if isinstance(v, StInst):
            return [self.class_def(v.cls, 'instance')]
        if isinstance(v, StFunc):
            return [self.func_def(v)]
        if isinstance(v, StMod):
            d = self.module_def(v)
            return [d] if d else []
        if isinstance(v, SuperInst):
            return [self.rt_class_def(super, 'instance')]
        if isinstance(v, RtInst):
            return [self.rt_class_def(v.cls, 'instance')]
        if isinstance(v, RtV):
            o = v.obj
            if inspect.ismodule(o):
                return [self.rt_module_def(o)]
            if inspect.isclass(o):
                return [self.rt_class_def(o)]
            if inspect.isroutine(o) or isinstance(o, _ROUTINE_TYPES):
                return [self.rt_func_def(o)]
            return [self.rt_class_def(type(o), 'instance')]
        return []

    def values_defs(self, vals):
        out = []
        for v in vals:
            out += self.value_defs(v)
        return out

    # ----- bindings -----

    def stmt_desc(self, b):
        info = b.scope.module
        k = b.kind
        if k == 'assign':
            return self.seg(info, b.extra)
        if k == 'unpack':
            return self.seg(info, b.extra[0])
        if k == 'ann':
            ann, value = b.extra
            if value is not None:
                return self.seg(info, value)
            node = b.stmt if isinstance(b.stmt, ast.AnnAssign) else b.node
            return self.seg(info, node)
        if k == 'for':
            it = b.extra[0]
            tgt = b.node
            if isinstance(b.stmt, (ast.For, ast.AsyncFor)) and b.stmt.iter is it:
                tgt = b.stmt.target
            return 'for %s in %s' % (self.seg(info, tgt), self.seg(info, it))
        if k == 'with':
            expr = b.extra[0]
            tgt = b.node
            if isinstance(b.stmt, (ast.With, ast.AsyncWith)):
                for item in b.stmt.items:
                    if item.context_expr is expr and item.optional_vars is not None:
                        tgt = item.optional_vars
            return 'with %s as %s' % (self.seg(info, expr), self.seg(info, tgt))
        if k == 'except':
            if b.extra is not None:
                return 'except %s as %s' % (self.seg(info, b.extra), b.name)
            return 'except'
        node = b.stmt if isinstance(b.stmt, ast.stmt) else b.node
        if node is None:
            return b.name
        s = ast.get_source_segment(info.text, node) if hasattr(node, 'lineno') else None
        if s is None:
            s = _unparse(node)
        first = s.split('\n')[0].strip()
        if first.endswith(':'):
            first = first[:-1].rstrip()
        return _ws(first)

    def binding_def(self, b):
        info = b.scope.module
        line, col = b.pos
        mp = self.rel(info.path)
        k = b.kind
        if k == 'def':
            return self.func_def(StFunc(b.node, b.extra))
        if k == 'class':
            return self.class_def(class_value(b.extra))
        owner = b.scope.parent if b.attr else b.scope
        full = self.qual(owner, b.name)
        if k == 'param':
            fnode, idx, default = b.extra
            a = b.node
            txt = _param_str(a, default)
            if a is fnode.args.vararg:
                txt = '*' + txt
            elif a is fnode.args.kwarg:
                txt = '**' + txt
            return self.mk(b.name, 'param', full, mp, line, col, 'param ' + txt, '')
        if k in ('import', 'from'):
            vals = self.e.binding_values(b)
            typ = 'module'
            full2 = None
            doc = ''
            if vals:
                v = vals[0]
                typ = kind_of(v) or 'module'
                ds = self.value_defs(v)
                if ds:
                    doc = ds[0]['docstring']
                    if k == 'import' or typ in ('module', 'class', 'function'):
                        full2 = ds[0]['full_name']
            if full2 is None:
                if k == 'import':
                    nm, asname = b.extra
                    full2 = nm if asname else nm.split('.')[0]
                else:
                    mod, level, attr = b.extra
                    mv = self.e.resolve_module(mod, info.dir, level)
                    mfull = mod
                    if isinstance(mv, StMod):
                        md = self.module_def(mv)
                        if md:
                            mfull = md['full_name']
                    full2 = '.'.join(p for p in (mfull, attr) if p)
            return self.mk(b.name, typ, full2, mp, line, col, self.seg(info, b.node), doc)
        return self.mk(b.name, 'statement', full, mp, line, col, self.stmt_desc(b), '')

    def entries_defs(self, ents):
        out = []
        for ent in ents:
            if ent[0] == 'b':
                out.append(self.binding_def(ent[1]))
            else:
                v = ent[1]()
                if v is not None:
                    out += self.value_defs(v)
        return out

    # ----- operations -----

    def scope_of(self, info, node):
        sc = info.node_scopes.get(id(node))
        if sc is None:
            line = node.lineno
            t = _line_text(info.lines, line)
            bcol = node.col_offset
            before = t.encode('utf-8')[:bcol].decode('utf-8', errors='ignore')
            sc = find_scope_by_pos(info.scope, line, bcol, info.lines, before)
        return sc

    def self_store_binding(self, info, node):
        sc = self.scope_of(info, node)
        line = node.end_lineno
        col = _char_col(info.lines, line, node.end_col_offset) - len(node.attr)
        for v in self.e.infer(node.value, sc, None):
            if isinstance(v, StInst):
                for c in self.e.mro(v.cls):
                    for b in self.e.self_attr_map(c).get(node.attr, ()):
                        if b.pos == (line, col):
                            return v, b
        return None, None

    def call_params(self, info, kw, call):
        sc = self.scope_of(info, call)
        out = []
        for f in self.e.infer(call.func, sc, None):
            fn = None
            if isinstance(f, StFunc):
                fn = f
            elif isinstance(f, StClass):
                for g in self.e.get_attr(StInst(f), '__init__'):
                    if isinstance(g, StFunc):
                        fn = g
                if fn is None:
                    for c in self.e.mro(f):
                        for b in c.scope.bindings.get(kw.arg, ()):
                            if b.kind == 'ann':
                                out.append(b)
                    continue
            if fn is not None:
                for b in fn.scope.bindings.get(kw.arg, ()):
                    if b.kind == 'param':
                        out.append(b)
        return out

    def goto(self, info, tgt):
        e = self.e
        kind = tgt[0]
        if kind == 'binding':
            return [self.binding_def(tgt[1])]
        if kind == 'name':
            node = tgt[1]
            sc = self.scope_of(info, node)
            st = e.lookup_state(node.id, sc, _start(node))
            if st is None:
                if hasattr(builtins, node.id):
                    return self.value_defs(RtV(getattr(builtins, node.id)))
                return []
            return self.entries_defs(st)
        if kind == 'attr':
            node = tgt[1]
            if isinstance(node.ctx, ast.Store):
                v, b = self.self_store_binding(info, node)
                if b is not None:
                    return [self.binding_def(b)]
            sc = self.scope_of(info, node)
            out = []
            for v in e.infer(node.value, sc, None):
                out += self.attr_goto(v, node.attr)
            return out
        if kind == 'kwarg':
            return [self.binding_def(b) for b in self.call_params(info, tgt[1], tgt[2])]
        if kind == 'module':
            return self.value_defs(e.resolve_module(tgt[1], info.dir, tgt[2]))
        if kind == 'fromattr':
            mv = e.resolve_module(tgt[1], info.dir, tgt[2])
            return self.attr_goto(mv, tgt[3])
        if kind == 'global':
            return self.entries_defs(e.scope_end_entries(info.scope, tgt[1]))
        return []

    def attr_goto(self, v, name):
        e = self.e
        if isinstance(v, (StInst, StClass, SuperInst)):
            return [self.binding_def(b) for b in e.attr_bindings(v, name)]
        if isinstance(v, StMod) and v.info is not None:
            ents = e.scope_end_entries(v.info.scope, name)
            if ents:
                return self.entries_defs(ents)
        return self.values_defs(e.get_attr(v, name))

    def infer(self, info, tgt):
        e = self.e
        kind = tgt[0]
        vals = []
        if kind == 'binding':
            vals = e.binding_values(tgt[1])
        elif kind == 'name':
            node = tgt[1]
            sc = self.scope_of(info, node)
            vals = e.lookup_values(node.id, sc, _start(node), 0)
        elif kind == 'attr':
            node = tgt[1]
            done = False
            if isinstance(node.ctx, ast.Store):
                v, b = self.self_store_binding(info, node)
                if b is not None:
                    vals = e.self_attr_values(v, b, 0)
                    done = True
            if not done:
                sc = self.scope_of(info, node)
                for v in e.infer(node.value, sc, None):
                    vals += e.get_attr(v, node.attr)
        elif kind == 'kwarg':
            kw, call = tgt[1], tgt[2]
            vals = e.infer(kw.value, self.scope_of(info, call), None)
        elif kind == 'module':
            vals = [e.resolve_module(tgt[1], info.dir, tgt[2])]
        elif kind == 'fromattr':
            mv = e.resolve_module(tgt[1], info.dir, tgt[2])
            vals = e.get_attr(mv, tgt[3])
        elif kind == 'global':
            vals = e.entries_values(e.scope_end_entries(info.scope, tgt[1]))
        return self.values_defs(uniq(vals))


def _all_scopes(sc):
    out = [sc]
    stack = [sc]
    while stack:
        s = stack.pop()
        for ch in s.children:
            out.append(ch)
            stack.append(ch)
    return out


_FROM_RE = re.compile(r'from\s+')


def locate(info, line, s, e, ident):
    """Find what the identifier spanning [s, e) on `line` refers to."""
    lines = info.lines
    for sc in _all_scopes(info.scope):
        for b in sc.bindings.get(ident, ()):
            if b.pos == (line, s):
                return ('binding', b)
    cl = _line_text(lines, line)
    bs = len(cl[:s].encode('utf-8'))
    be = len(cl[:e].encode('utf-8'))
    parents = {}
    for node in ast.walk(info.tree):
        for ch in ast.iter_child_nodes(node):
            parents[id(ch)] = node
    found = None
    for node in ast.walk(info.tree):
        t = type(node)
        if t is ast.Name:
            if node.id == ident and node.lineno == line and node.col_offset == bs:
                return ('name', node)
        elif t is ast.Attribute:
            if node.attr == ident and node.end_lineno == line and node.end_col_offset == be:
                found = found or ('attr', node)
        elif t is ast.keyword:
            if node.arg == ident and getattr(node, 'lineno', None) == line and \
                    node.col_offset == bs:
                found = found or ('kwarg', node, parents.get(id(node)))
        elif t is ast.Import:
            for a in node.names:
                parts, asp = _alias_parts(lines, a)
                for k, (p, pp) in enumerate(parts):
                    if p == ident and pp == (line, s):
                        found = found or ('module', '.'.join(x for x, _ in parts[:k + 1]), 0)
        elif t is ast.ImportFrom:
            if node.module and node.lineno <= line:
                st = _line_text(lines, node.lineno)
                c = _char_col(lines, node.lineno, node.col_offset)
                m = _FROM_RE.match(st, c)
                if m:
                    i = m.end()
                    while i < len(st) and st[i] in '. \t':
                        i += 1
                    mparts = node.module.split('.')
                    for k, p in enumerate(mparts):
                        j = st.find(p, i)
                        if j < 0:
                            break
                        if p == ident and (node.lineno, j) == (line, s):
                            found = found or ('module', '.'.join(mparts[:k + 1]), node.level or 0)
                        i = j + len(p)
            for a in node.names:
                if a.asname and a.name == ident:
                    parts, asp = _alias_parts(lines, a)
                    if parts and parts[0][1] == (line, s):
                        found = found or ('fromattr', node.module or '', node.level or 0, a.name)
        elif t in (ast.Global, ast.Nonlocal):
            if ident in node.names and node.lineno <= line <= (node.end_lineno or node.lineno):
                found = found or ('global', ident)
    return found


def navigate(path, line, col, mode, project=None):
    text = read_source(path)
    lines = text.split('\n')
    if line < 1 or line > len(lines):
        raise SithError('line out of range')
    cl = lines[line - 1]
    if col < 0 or col > len(cl):
        raise SithError('column out of range')
    if col < len(cl) and is_ident_char(cl[col]):
        s = col
    elif col > 0 and is_ident_char(cl[col - 1]):
        s = col - 1
    else:
        raise NotAName('cursor is not on a name')
    while s > 0 and is_ident_char(cl[s - 1]):
        s -= 1
    e = s
    while e < len(cl) and is_ident_char(cl[e]):
        e += 1
    ident = cl[s:e]
    if not ident or ident[0].isdigit() or keyword.iskeyword(ident) or \
            (s > 0 and cl[s - 1].isdigit() and not is_ident_char(cl[s - 1])):
        raise NotAName('cursor is not on a name')
    offset = sum(len(lines[k]) + 1 for k in range(line - 1)) + s
    in_str = in_comment_or_string(text, offset)

    root = os.path.abspath(project) if project else os.path.dirname(os.path.abspath(path))
    engine = Engine(root)
    tree, fixed = parse_source(text, with_text=True)
    base = os.path.basename(path)
    info = ModuleInfo(os.path.abspath(path), tree, base[:-3] if base.endswith('.py') else base,
                      fixed)
    engine.static_cache[os.path.realpath(path)] = info
    tgt = locate(info, line, s, e, ident)
    if in_str and (tgt is None or tgt[0] not in ('name', 'attr')):
        raise NotAName('cursor is not on a name')
    if tgt is None:
        return []
    nav = Navigator(engine, root)
    defs = nav.goto(info, tgt) if mode == 'goto' else nav.infer(info, tgt)
    out = []
    seen = set()
    for d in defs:
        if d is None:
            continue
        k = tuple(d[f] for f in ('name', 'type', 'full_name', 'module_path', 'line', 'column',
                                 'description'))
        if k in seen:
            continue
        seen.add(k)
        out.append(d)
    out.sort(key=lambda d: (d['module_path'], d['line'], d['column']))
    return out


def _parse_int(s, what):
    try:
        return int(s)
    except ValueError:
        raise SithError('invalid %s: %r' % (what, s))


USAGE = ('usage: sith.py complete <file> <line> <col> [--fuzzy]\n'
         '       sith.py infer <file> <line> <col>\n'
         '       sith.py goto <file> <line> <col>\n')


def main(argv):
    project = None
    rest = []
    i = 0
    while i < len(argv):
        a = argv[i]
        if a == '--project' and i + 1 < len(argv):
            project = argv[i + 1]
            i += 2
            continue
        if a.startswith('--project='):
            project = a[len('--project='):]
        else:
            rest.append(a)
        i += 1
    args = [a for a in rest if a != '--fuzzy']
    fuzzy = len(args) != len(rest)
    if len(args) != 4 or args[0] not in ('complete', 'infer', 'goto'):
        sys.stderr.write(USAGE)
        return 1
    try:
        line = _parse_int(args[2], 'line')
        col = _parse_int(args[3], 'column')
        sys.setrecursionlimit(max(sys.getrecursionlimit(), 10000))
        if args[0] == 'complete':
            out = {'completions': complete(args[1], line, col, fuzzy)}
        else:
            out = {'definitions': navigate(args[1], line, col, args[0], project)}
    except SithError as e:
        sys.stderr.write('error: %s\n' % e)
        return 1
    sys.stdout.write(json.dumps(out, separators=(',', ':')) + '\n')
    sys.stdout.flush()
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
