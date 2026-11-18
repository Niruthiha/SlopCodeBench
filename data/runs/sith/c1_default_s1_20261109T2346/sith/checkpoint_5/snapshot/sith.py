#!/usr/bin/env python3
"""sith - a small static Python code intelligence tool.

Usage:
    python sith.py complete <file> <line> <col> [--fuzzy] [--project <dir>]
    python sith.py infer <file> <line> <col> [--project <dir>]
    python sith.py goto <file> <line> <col> [--follow-imports] [--project <dir>]
    python sith.py signatures <file> <line> <col> [--project <dir>]
    python sith.py references <file> <line> <col> [--scope file|project] [--project <dir>]
    python sith.py search <query> [--project <dir>]
    python sith.py names <file> [--all-scopes] [--project <dir>]
    python sith.py rename <file> <line> <col> --new-name <name> [--diff] [--project <dir>]
    python sith.py inline <file> <line> <col> [--diff] [--project <dir>]
    python sith.py extract-variable <file> <line> <col> --until <line>:<col> --name <name>
                   [--diff] [--project <dir>]
    python sith.py extract-function <file> <line> <col> --until <line>:<col> --name <name>
                   [--diff] [--project <dir>]
    python sith.py errors <file>
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
        self.is_package = os.path.basename(path) in ('__init__.py', '__init__.pyi')
        self.is_stub = path.endswith('.pyi')
        self.stub_src = None
        self.stub = False
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


def _posix(p):
    return p.replace(os.sep, '/') if os.sep != '/' else p


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

def _str_list(node):
    """String constants of a list/tuple literal (possibly concatenated), or None."""
    if isinstance(node, (ast.List, ast.Tuple)):
        out = []
        for e in node.elts:
            if isinstance(e, ast.Constant) and isinstance(e.value, str):
                out.append(e.value)
        return out
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        a, b = _str_list(node.left), _str_list(node.right)
        if a is not None and b is not None:
            return a + b
    return None


def _inside(path, root):
    """True if ``path`` is ``root`` or lies below it."""
    path = os.path.realpath(path)
    root = os.path.realpath(root)
    return path == root or path.startswith(root.rstrip(os.sep) + os.sep)


_STDLIB_NAMES = set(getattr(sys, 'stdlib_module_names', ())) | set(sys.builtin_module_names)
_RT_BLOCKED = {'antigravity'}


def is_stdlib(dotted):
    top = dotted.split('.')[0]
    if not top or top in _RT_BLOCKED:
        return False
    return top in _STDLIB_NAMES


_stdlib_listing = None


def stdlib_top_names():
    """Names of the standard library modules available in this runtime."""
    global _stdlib_listing
    if _stdlib_listing is None:
        names = set(sys.builtin_module_names)
        base = os.path.dirname(os.__file__)
        for d in (base, os.path.join(base, 'lib-dynload')):
            names.update(dir_modules(d))
        if _STDLIB_NAMES - set(sys.builtin_module_names):
            names &= _STDLIB_NAMES
        names.discard('__main__')
        _stdlib_listing = names - _RT_BLOCKED
    return _stdlib_listing


def dir_modules(d):
    """Module and package names found directly inside directory ``d``."""
    out = set()
    try:
        listing = os.listdir(d)
    except OSError:
        return out
    for fn in listing:
        full = os.path.join(d, fn)
        if fn.endswith('.py'):
            name = fn[:-3]
            if not os.path.isfile(full):
                continue
        elif '.' in fn and (fn.endswith('.so') or fn.endswith('.pyd')):
            name = fn.split('.')[0]
            if not os.path.isfile(full):
                continue
        elif fn != '__pycache__' and os.path.isdir(full):
            name = fn
        else:
            continue
        if name.isidentifier() and name != '__init__' and not keyword.iskeyword(name):
            out.add(name)
    return out


class Engine:
    def __init__(self, root=None, script=None):
        self.static_cache = {}
        self.rt_cache = {}
        self.inferring = set()
        self.calling = set()
        self.frames = {}
        self.reach_cache = {}
        self.root = os.path.abspath(root) if root else None
        self.steps = 0
        self.max_steps = 400000
        self.import_stack = []
        self.star_cache = {}
        self.all_cache = {}
        self.extra_paths = self._script_paths(script)

    def _script_paths(self, script):
        """Directories of the script (outside packages) that act as sys.path entries."""
        if not script:
            return []
        d = os.path.dirname(os.path.abspath(script))
        if self.root is None or not _inside(d, self.root):
            return [d]
        out = []
        while _inside(d, self.root) and os.path.realpath(d) != os.path.realpath(self.root):
            if not os.path.isfile(os.path.join(d, '__init__.py')):
                out.append(d)
            nd = os.path.dirname(d)
            if nd == d:
                break
            d = nd
        return out

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
            f = os.path.join(d, p, '__init__.py')
            if os.path.isfile(f):
                return ('file', f)
            f = os.path.join(d, p + '.py')
            if os.path.isfile(f):
                return ('file', f)
            f = os.path.join(d, p, '__init__.pyi')
            if os.path.isfile(f):
                return ('file', f)
            f = os.path.join(d, p + '.pyi')
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
            pkgdir = os.path.dirname(p) if os.path.basename(p) in ('__init__.py', '__init__.pyi') \
                else None
            return StMod(info, pkgdir, name)
        return StMod(None, p, name)

    def rt_import(self, name):
        if name in self.rt_cache:
            return self.rt_cache[name]
        if not is_stdlib(name):
            self.rt_cache[name] = None
            return None
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
            if self.root and _inside(base_dir, self.root) and not _inside(d, self.root):
                return UnMod(dotted)
            if not dotted:
                init = os.path.join(d, '__init__.py')
                if os.path.isfile(init):
                    return StMod(self.load_static(init, ''), d, '')
                return StMod(None, d, '')
            found = self.find_local(dotted, d)
            if found:
                return self.static_module(found, dotted)
            return UnMod(dotted)
        if not dotted:
            return UnMod(dotted)
        roots = [self.root] if self.root else [base_dir]
        for r in roots:
            found = self.find_local(dotted, r)
            if found:
                return self.static_module(found, dotted)
        sd = self.stubs_dir()
        if sd:
            found = self.find_local(dotted, sd)
            if found and found[0] == 'file':
                return self.static_module(found, dotted)
        mod = self.rt_import(dotted)
        if mod is not None:
            return RtV(mod)
        for r in self.extra_paths:
            found = self.find_local(dotted, r)
            if found:
                return self.static_module(found, dotted)
        return UnMod(dotted)

    def module_all(self, info):
        """The names listed in a module's ``__all__``, or None."""
        key = id(info)
        if key in self.all_cache:
            return self.all_cache[key]
        names = None
        for s in _iter_stmts(info.tree.body):
            if isinstance(s, (ast.Assign, ast.AnnAssign)):
                tgts = s.targets if isinstance(s, ast.Assign) else [s.target]
                if any(isinstance(t, ast.Name) and t.id == '__all__' for t in tgts):
                    vals = _str_list(s.value)
                    if vals is not None:
                        names = vals
                    elif names is None:
                        names = []
            elif isinstance(s, ast.AugAssign) and isinstance(s.target, ast.Name) and \
                    s.target.id == '__all__' and isinstance(s.op, ast.Add):
                vals = _str_list(s.value)
                if vals is not None:
                    names = (names or []) + vals
            elif isinstance(s, ast.Expr) and isinstance(s.value, ast.Call):
                f = s.value.func
                if isinstance(f, ast.Attribute) and isinstance(f.value, ast.Name) and \
                        f.value.id == '__all__' and len(s.value.args) == 1:
                    arg = s.value.args[0]
                    if f.attr == 'extend':
                        vals = _str_list(arg)
                        if vals is not None:
                            names = (names or []) + vals
                    elif f.attr == 'append' and isinstance(arg, ast.Constant) and \
                            isinstance(arg.value, str):
                        names = (names or []) + [arg.value]
        if names is not None:
            names = list(dict.fromkeys(n for n in names if n.isidentifier()))
        self.all_cache[key] = names
        return names

    def export_entries(self, mv, seen=None):
        """Names exported by a module (``__all__`` or public names) as entries."""
        if isinstance(mv, RtV) and inspect.ismodule(mv.obj):
            o = mv.obj
            names = getattr(o, '__all__', None)
            if not isinstance(names, (list, tuple)) or \
                    not all(isinstance(n, str) for n in names):
                try:
                    names = [n for n in dir(o) if not n.startswith('_')]
                except Exception:
                    names = []
            out = {}
            for n in names:
                if hasattr(o, n):
                    out[n] = self._rt_attr_entry(o, n)
                else:
                    full = o.__name__ + '.' + n
                    out[n] = ('v', lambda f=full: (lambda m: RtV(m) if m is not None else None)(
                        self.rt_import(f)))
            return out
        if not isinstance(mv, StMod):
            return {}
        out = {}
        if mv.info is not None:
            names = self.module_all(mv.info)
            if names is None:
                out = self.module_entries(mv.info, seen)
                self._merge_stub(out, self.stub_entries(mv))
            else:
                ents = self.module_entries(mv.info, seen, private=True)
                for n in names:
                    if n in ents:
                        out[n] = ents[n]
                    elif mv.pkgdir and self.find_local(n, mv.pkgdir):
                        out[n] = ('v', lambda n=n: (self.get_attr(mv, n) or [None])[0])
        return out

    def star_names(self, mv, seen=None):
        """Return dict name -> entry for names exported by a star import."""
        if seen is None:
            key = _vkey(mv)
            if key not in self.star_cache:
                self.star_cache[key] = {}
                self.star_cache[key] = self._star_names(mv, None)
            return self.star_cache[key]
        return self._star_names(mv, seen)

    def _star_names(self, mv, seen):
        if isinstance(mv, StMod) and mv.info is not None:
            if seen is None:
                seen = set()
            if id(mv.info) in seen:
                return {}
            seen.add(id(mv.info))
        return self.export_entries(mv, seen)

    def star_entry(self, sc, node, name):
        mv = self.resolve_module(node.module or '', sc.module.dir, node.level or 0)
        return self.star_names(mv).get(name)

    def star_has(self, sc, name):
        for (sl, mod, lvl) in sc.stars:
            mv = self.resolve_module(mod, sc.module.dir, lvl)
            if name in self.star_names(mv):
                return True
        return False

    def module_entries(self, info, seen=None, private=False):
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
            if (private or not n.startswith('_')) and MARK not in n:
                out[n] = ent
        return out

    def import_limit(self, info):
        """Line at which ``info`` is paused by a circular import, or None."""
        for inf, line in self.import_stack:
            if inf is info:
                return line
        return None

    def module_attr_entries(self, info, name):
        """Entries for ``name`` at module level, honouring circular imports."""
        lim = self.import_limit(info)
        if lim is None:
            return self.scope_end_entries(info.scope, name)
        r = self.reach(info.scope, name, (lim, 0))
        return list(r) if r else []

    # ----- stubs -----

    def stubs_dir(self):
        if self.root:
            d = os.path.join(self.root, 'stubs')
            if os.path.isdir(d):
                return d
        return None

    def stub_for(self, info):
        """The ``.pyi`` stub module providing type information for ``info``."""
        if info is None or info.is_stub:
            return None
        if info.stub is not False:
            return info.stub
        info.stub = None
        path = info.path
        cands = [os.path.splitext(path)[0] + '.pyi']
        sd = self.stubs_dir()
        if sd and _inside(path, self.root):
            rp = os.path.relpath(os.path.realpath(path), os.path.realpath(self.root))
            parts = os.path.splitext(rp)[0].split(os.sep)
            if parts[-1] == '__init__':
                parts.pop()
            if parts and parts[0] != 'stubs':
                base = os.path.join(sd, *parts)
                cands += [base + '.pyi', os.path.join(base, '__init__.pyi')]
        for c in cands:
            if os.path.isfile(c):
                st = self.load_static(c, info.name)
                if st is not None and st is not info:
                    st.stub_src = info
                    info.stub = st
                    break
        return info.stub

    @staticmethod
    def scope_path(sc):
        """Names of the classes/functions leading from the module to ``sc``."""
        path = []
        s = sc
        while s is not None and s.kind != 'module':
            if s.kind not in ('class', 'function'):
                return None
            path.append(s.node.name)
            s = s.parent
        if s is None:
            return None
        return s.module, path[::-1]

    @staticmethod
    def scope_at(info, path):
        cur = info.scope
        for name in path:
            nxt = None
            for b in cur.bindings.get(name, ()):
                if b.kind in ('class', 'def'):
                    nxt = b.extra
            if nxt is None:
                return None
            cur = nxt
        return cur

    def stub_scope(self, sc):
        """The scope of the stub corresponding to source scope ``sc``."""
        r = self.scope_path(sc)
        if r is None:
            return None
        stub = self.stub_for(r[0])
        if stub is None:
            return None
        return self.scope_at(stub, r[1])

    def from_stub(self, v):
        """Map a class (instance) defined in a stub back to its source class."""
        if isinstance(v, StInst):
            c = self.from_stub(v.cls)
            return v if c is v.cls else StInst(c, v.args)
        if isinstance(v, StClass):
            info = v.scope.module
            if info.is_stub and info.stub_src is not None:
                r = self.scope_path(v.scope)
                if r is not None:
                    sc = self.scope_at(info.stub_src, r[1])
                    if sc is not None and sc.kind == 'class':
                        return class_value(sc)
        return v

    def stub_ann(self, node, sc, depth):
        return uniq(self.from_stub(v) for v in self.infer_annotation(node, sc, depth))

    def stub_defs(self, fnode, fs):
        """Stub variants ([(node, scope)]) of the source function ``fnode``."""
        if fs.module.is_stub or fs.parent is None:
            return []
        ssc = self.stub_scope(fs.parent)
        if ssc is None:
            return []
        defs = [(b.node, b.extra) for b in ssc.bindings.get(fnode.name, ()) if b.kind == 'def']
        if not defs:
            return []
        ovs = [d for d in defs if 'overload' in _decorator_names(d[0])]
        return ovs or [defs[-1]]

    @staticmethod
    def overloads(psc, name):
        if psc is None:
            return []
        return [(b.node, b.extra) for b in psc.bindings.get(name, ())
                if b.kind == 'def' and 'overload' in _decorator_names(b.node)]

    def sig_variants(self, f):
        """The declarations ([(node, scope)]) describing the signature of ``f``."""
        fnode, fs = f.node, f.scope
        if isinstance(fnode, ast.Lambda):
            return [(fnode, fs)]
        sd = self.stub_defs(fnode, fs)
        if sd:
            return sd
        return self.overloads(fs.parent, fnode.name) or [(fnode, fs)]

    def stub_param_values(self, b, depth):
        a = b.node
        fnode = b.extra[0]
        fs = b.scope
        if not isinstance(fnode, (ast.FunctionDef, ast.AsyncFunctionDef)):
            return []
        out = []
        for node, vsc in self.stub_defs(fnode, fs):
            for p in _all_args(node.args):
                if p.arg != a.arg or p.annotation is None:
                    continue
                if p is node.args.vararg:
                    out.append(RtV(()))
                elif p is node.args.kwarg:
                    out.append(RtV({}))
                else:
                    out += self.stub_ann(p.annotation, vsc.parent, depth + 1)
        return uniq(out)

    def stub_module_attr(self, info, name, depth):
        """Values of module attribute ``name`` according to the stub, or None."""
        stub = self.stub_for(info)
        if stub is None:
            return None
        bl = stub.scope.bindings.get(name)
        if not bl:
            return None
        b = bl[-1]
        if b.kind == 'ann':
            return self.stub_ann(b.extra[0], stub.scope, depth + 1) or None
        if self.module_attr_entries(info, name):
            return None
        vals = self.entries_values(self.scope_end_entries(stub.scope, name), depth + 1)
        return uniq(self.from_stub(v) for v in vals) or None

    def stub_class_attr(self, classes, name, owner, depth):
        """Values of class attribute ``name`` according to stubs, or None."""
        for c in classes:
            ssc = self.stub_scope(c.scope)
            if ssc is None:
                continue
            bl = ssc.bindings.get(name)
            if not bl:
                continue
            b = bl[-1]
            in_src = name in c.scope.bindings or name in self.self_attr_map(c)
            if b.kind == 'ann':
                return self.stub_ann(b.extra[0], ssc, depth + 1) or None
            if b.kind == 'def':
                decos = _decorator_names(b.node)
                if decos & {'property', 'cached_property'} and isinstance(owner, (StInst, SuperInst)):
                    if b.node.returns is not None:
                        vals = self.stub_ann(b.node.returns, ssc, depth + 1)
                        if vals:
                            return vals
                    return None if in_src else []
                if in_src:
                    return None
                return uniq(self.bind_member(StFunc(b.node, b.extra), owner, c, depth))
            if in_src:
                return None
            vals = self.entries_values(self.scope_end_entries(ssc, name), depth + 1)
            return uniq(self.from_stub(v) for v in vals) or None
        return None

    def stub_entries(self, v, classes=None):
        """Completion entries contributed by stubs for value ``v``."""
        out = {}
        scopes = []
        if isinstance(v, StMod) and v.info is not None:
            stub = self.stub_for(v.info)
            if stub is not None:
                scopes.append(stub.scope)
        for c in reversed(classes or []):
            ssc = self.stub_scope(c.scope)
            if ssc is not None:
                scopes.append(ssc)
        for ssc in scopes:
            for n, lst in ssc.bindings.items():
                b = lst[-1]
                if MARK in n or b.kind in ('import', 'from'):
                    continue
                if ssc.kind == 'module' and n.startswith('_'):
                    continue
                out[n] = (b.kind, ('v', lambda n=n: (self.get_attr(v, n) or [None])[0]))
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
        if k in ('import', 'from') and sc.kind == 'module':
            self.import_stack.append((sc.module, b.line))
            try:
                return self._import_values(b, depth)
            finally:
                self.import_stack.pop()
        if k in ('import', 'from'):
            return self._import_values(b, depth)
        if k == 'assign':
            return self.infer(b.extra, sc, None, depth + 1)
        return self._other_values(b, depth)

    def _import_values(self, b, depth):
        k = b.kind
        sc = b.scope
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
        return []

    def _other_values(self, b, depth):
        k = b.kind
        sc = b.scope
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
        vals = self.stub_param_values(b, depth)
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

    def pick_overload(self, variants, f, args, depth):
        """The first overload accepting the call ``args`` (all if undecidable)."""
        if args is None:
            return variants
        for node, vsc in variants:
            try:
                ok = self._overload_matches(node, vsc, f, args, depth)
            except RecursionError:
                ok = False
            if ok:
                return [(node, vsc)]
        return variants

    def _overload_matches(self, node, vsc, f, args, depth):
        cnode, csc, cframes = args
        a = node.args
        params = list(getattr(a, 'posonlyargs', [])) + list(a.args)
        ndef = len(a.defaults)
        required = params[:len(params) - ndef]
        if f.skip and params:
            required = [p for p in required if p is not params[0]]
            params = params[1:]
        posonly = set(id(p) for p in getattr(a, 'posonlyargs', []))
        bound = {}
        unknown = any(isinstance(x, ast.Starred) for x in cnode.args) or \
            any(kw.arg is None for kw in cnode.keywords)
        pos = [x for x in cnode.args if not isinstance(x, ast.Starred)]
        if len(pos) > len(params) and a.vararg is None:
            return False
        for p, x in zip(params, pos):
            bound[p.arg] = (p, x)
        names = {p.arg: p for p in params + list(a.kwonlyargs) if id(p) not in posonly}
        for kw in cnode.keywords:
            if kw.arg is None:
                continue
            if kw.arg in names:
                if kw.arg in bound:
                    return False
                bound[kw.arg] = (names[kw.arg], kw.value)
            elif a.kwarg is None:
                return False
        if not unknown:
            for p in required:
                if p.arg not in bound:
                    return False
            for p, d in zip(a.kwonlyargs, a.kw_defaults):
                if d is None and p.arg not in bound:
                    return False
        for p, x in bound.values():
            if p.annotation is None:
                continue
            anns = self.infer_annotation(p.annotation, vsc.parent, depth + 1)
            saved = self.frames
            self.frames = cframes
            try:
                vals = self.infer(x, csc, None, depth + 1)
            finally:
                self.frames = saved
            if anns and vals and not any(self._compatible(v, anns) for v in vals):
                return False
        return True

    def _val_cls(self, v):
        if isinstance(v, StInst):
            return v.cls
        if isinstance(v, RtInst):
            return v.cls
        if isinstance(v, RtV) and kind_of(v) == 'instance':
            return type(v.obj)
        return None

    def _compatible(self, v, anns):
        vc = self._val_cls(v)
        if vc is None:
            return True
        for a in anns:
            ac = self._val_cls(a)
            if ac is None or ac is object:
                return True
            if isinstance(vc, StClass) and isinstance(ac, StClass):
                if ac in self.mro(vc):
                    return True
            elif inspect.isclass(vc) and inspect.isclass(ac):
                try:
                    if issubclass(vc, ac):
                        return True
                except Exception:
                    pass
        return False

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
        variants = self.sig_variants(f)
        if len(variants) > 1 or variants[0][0] is not fnode:
            if len(variants) > 1:
                variants = self.pick_overload(variants, f, args, depth)
            vals = []
            for node, vsc in variants:
                if node.returns is not None:
                    vals += self.stub_ann(node.returns, vsc.parent, depth + 1)
            if vals:
                return uniq(vals)
        if fnode.returns is not None:
            vals = self.infer_annotation(fnode.returns, fs.parent, depth + 1)
            if vals:
                return vals
        if fs.module.is_stub:
            return []
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
                sv = self.stub_module_attr(v.info, name, depth)
                if sv is not None:
                    return sv
                ents = self.module_attr_entries(v.info, name)
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
            sv = self.stub_class_attr(classes, name, v, depth)
            if sv is not None:
                return sv
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
            classes = self.mro(v)
            sv = self.stub_class_attr(classes, name, v, depth)
            if sv is not None:
                return sv
            for c in classes:
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
        for c in classes:
            ssc = self.stub_scope(c.scope)
            if ssc is not None and name in ssc.bindings:
                return list(ssc.bindings[name])
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

    @staticmethod
    def _merge_stub(out, stub):
        for n, (kind, ent) in stub.items():
            if kind == 'ann' or n not in out:
                out[n] = ent

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
            self._merge_stub(out, self.stub_entries(v))
            return out
        if isinstance(v, StClass):
            classes = self.mro(v)
            out = self.class_attrs(classes)
            self._merge_stub(out, self.stub_entries(v, classes))
            return out
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
            self._merge_stub(out, self.stub_entries(v, classes))
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


def project_root(path, project):
    if project:
        root = os.path.abspath(project)
        if not os.path.isdir(root):
            raise SithError('project directory not found: %s' % project)
        return root
    return os.path.dirname(os.path.abspath(path))


def _stmt_tokens(lines, first):
    """Tokenize ``lines`` (starting at line number ``first``) and return the
    tokens of the last logical statement as (text, start, end) tuples."""
    stmt = []
    depth = 0
    cont = False
    quote = None
    for li, t in enumerate(lines):
        ln = first + li
        if not cont and depth == 0 and quote is None:
            stmt = []
        cont = False
        i = 0
        n = len(t)
        while i < n:
            if quote is not None:
                if t[i] == '\\':
                    i += 2
                    continue
                if t.startswith(quote, i):
                    i += len(quote)
                    quote = None
                    stmt.append(('<str>', (ln, i), (ln, i)))
                    continue
                i += 1
                continue
            c = t[i]
            if c in ' \t\f':
                i += 1
                continue
            if c == '#':
                break
            if c == '\\' and t[i + 1:].strip() == '':
                cont = True
                break
            if c in '"\'':
                quote = c * 3 if t.startswith(c * 3, i) else c
                i += len(quote)
                continue
            if is_ident_char(c):
                j = i
                while j < n and is_ident_char(t[j]):
                    j += 1
                stmt.append((t[i:j], (ln, i), (ln, j)))
                i = j
                continue
            if t.startswith('...', i):
                stmt.append(('...', (ln, i), (ln, i + 3)))
                i += 3
                continue
            if c in '([{':
                depth += 1
            elif c in ')]}':
                depth = max(0, depth - 1)
            elif c == ';' and depth == 0:
                stmt = []
                i += 1
                continue
            stmt.append((c, (ln, i), (ln, i + 1)))
            i += 1
        if quote is not None and len(quote) == 1:
            quote = None
    return stmt


def import_context(lines, line, col, prefix):
    """Classify an import statement around the cursor.

    Returns None when not inside an import statement, otherwise one of
    ('modules',), ('submodules', level, dotted), ('names', level, dotted),
    ('keyword',) or ('none',).
    """
    cl = lines[line - 1]
    pstart = col - len(prefix)
    toks = None
    for k in range(line - 1, max(-1, line - 1 - 60), -1):
        t = _stmt_tokens(lines[k:line - 1] + [cl[:pstart]], k + 1)
        if t and t[0][0] in ('import', 'from'):
            toks = t
            break
    if toks is None:
        return None
    words = [w for w, _, _ in toks]
    if '<str>' in words:
        return ('none',)
    gap = toks[-1][2] != (line, pstart)
    if words[0] == 'import':
        last = words[1:]
        while ',' in last:
            last = last[last.index(',') + 1:]
        if not last:
            return ('modules',)
        if last[-1] == '.' and _dotted_ok(last[:-1]):
            return ('submodules', 0, ''.join(last[:-1]))
        return ('none',)
    i = 1
    level = 0
    while i < len(words) and words[i] in ('.', '...'):
        level += len(words[i])
        i += 1
    j = i
    while j < len(words) and words[j] != 'import':
        j += 1
    mod = words[i:j]
    if mod and not _dotted_ok(mod[:-1] if mod[-1] == '.' else mod):
        return ('none',)
    if j == len(words):
        if gap and ((mod and mod[-1] != '.') or (not mod and level)):
            return ('keyword',)
        if not mod:
            return ('submodules', level, '') if level else ('modules',)
        if mod[-1] == '.':
            return ('submodules', level, ''.join(mod[:-1]))
        return ('none',)
    if not mod and not level or (mod and mod[-1] == '.'):
        return ('none',)
    names = words[j + 1:]
    if names[:1] == ['(']:
        names = names[1:]
    if ')' in names or '(' in names:
        return ('none',)
    while ',' in names:
        names = names[names.index(',') + 1:]
    if names:
        return ('none',)
    return ('names', level, ''.join(mod))


def _dotted_ok(parts):
    """True if ``parts`` alternate identifier, '.', identifier, ..."""
    for k, p in enumerate(parts):
        if k % 2:
            if p != '.':
                return False
        elif not p.isidentifier() or keyword.iskeyword(p):
            return False
    return len(parts) % 2 == 1


def submodule_entries(engine, mv):
    """Entries for the submodules of a package value."""
    out = {}
    if isinstance(mv, StMod) and mv.pkgdir:
        for n in dir_modules(mv.pkgdir):
            out[n] = ('v', lambda n=n: (engine.get_attr(mv, n) or [None])[0])
    elif isinstance(mv, RtV) and inspect.ismodule(mv.obj):
        paths = getattr(mv.obj, '__path__', None)
        if paths:
            try:
                import pkgutil
                names = [m.name for m in pkgutil.iter_modules(list(paths))]
            except Exception:
                names = []
            base = mv.obj.__name__
            for n in names:
                full = base + '.' + n
                out[n] = ('v', lambda f=full: (lambda m: RtV(m) if m is not None else None)(
                    engine.rt_import(f)))
    return out


def import_completions(engine, ctx, path):
    """Return dict name -> (type, description) for an import context."""
    kind = ctx[0]
    out = {}
    if kind == 'modules':
        names = set()
        for d in ([engine.root] if engine.root else []) + engine.extra_paths:
            names |= dir_modules(d)
        names |= stdlib_top_names()
        for n in names:
            out[n] = ('module', 'module ' + n)
        return out
    if kind == 'keyword':
        return {'import': ('keyword', 'import')}
    if kind not in ('submodules', 'names'):
        return out
    level, dotted = ctx[1], ctx[2]
    mv = engine.resolve_module(dotted, os.path.dirname(os.path.abspath(path)), level)
    ents = {}
    if kind == 'names':
        ents.update(engine.export_entries(mv))
        has_all = isinstance(mv, StMod) and mv.info is not None and \
            engine.module_all(mv.info) is not None
        if not has_all:
            for n, ent in submodule_entries(engine, mv).items():
                if not n.startswith('_'):
                    ents.setdefault(n, ent)
        for n, ent in ents.items():
            if MARK not in n:
                out[n] = engine.describe_entry(n, ent)
    else:
        for n in submodule_entries(engine, mv):
            out[n] = ('module', 'module ' + n)
    return out


def complete(path, line, col, fuzzy=False, project=None):
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

    root = project_root(path, project)
    engine = Engine(root, path)
    ctx = import_context(lines, line, col, prefix)
    if ctx is not None:
        results = []
        tree = parse_source(text)
        info = ModuleInfo(os.path.abspath(path), tree, '__main__', text)
        engine.static_cache[os.path.realpath(path)] = info
        for n, (typ, desc) in import_completions(engine, ctx, path).items():
            if match_name(n, prefix, fuzzy):
                results.append({'name': n, 'complete': n[len(prefix):], 'type': typ,
                                 'description': desc})
        results.sort(key=sort_key)
        return results

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
    def __init__(self, engine, root, follow_imports=False):
        self.e = engine
        self.root = os.path.abspath(root)
        self.follow_imports = follow_imports

    # ----- naming -----

    def rel(self, path):
        ap = os.path.abspath(path)
        try:
            rp = os.path.relpath(ap, self.root)
        except ValueError:
            return ap
        if rp == '..' or rp.startswith('..' + os.sep):
            return _posix(ap)
        return _posix(rp)

    def modname(self, info):
        path = info.path
        rp = self.rel(path)
        if os.path.isabs(rp) or rp.startswith('/'):
            base = os.path.basename(path)
            if base in ('__init__.py', '__init__.pyi'):
                return os.path.basename(os.path.dirname(path))
            return os.path.splitext(base)[0] if base.endswith(('.py', '.pyi')) else base
        if rp.endswith(('.py', '.pyi')):
            rp = os.path.splitext(rp)[0]
        parts = rp.split('/')
        if info.is_stub and len(parts) > 1 and parts[0] == 'stubs':
            parts = parts[1:]
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

    def follow(self, b, seen=frozenset()):
        """Definitions an import binding ultimately refers to (None if unresolvable)."""
        if id(b) in seen:
            return None
        seen = seen | {id(b)}
        e = self.e
        sc = b.scope
        if b.kind == 'import':
            full, asname = b.extra
            mv = e.resolve_module(full if asname else full.split('.')[0], sc.module.dir)
            if isinstance(mv, StMod):
                d = self.module_def(mv)
                return [d] if d else None
            return None
        mod, level, attr = b.extra
        mv = e.resolve_module(mod, sc.module.dir, level)
        if not isinstance(mv, StMod):
            return None
        pushed = sc.kind == 'module'
        if pushed:
            e.import_stack.append((sc.module, b.line))
        try:
            out = []
            ents = e.module_attr_entries(mv.info, attr) if mv.info is not None else []
            if not ents and mv.info is not None:
                stub = e.stub_for(mv.info)
                if stub is not None:
                    ents = e.module_attr_entries(stub, attr)
            for ent in ents:
                if ent[0] == 'b':
                    if ent[1].kind in ('import', 'from'):
                        out += self.follow(ent[1], seen) or []
                    else:
                        out.append(self.binding_def(ent[1]))
                else:
                    v = ent[1]()
                    if isinstance(v, (StMod, StClass, StFunc)):
                        out += self.value_defs(v)
            if not out and mv.pkgdir:
                found = e.find_local(attr, mv.pkgdir)
                if found:
                    d = self.module_def(e.static_module(found, (mv.name + '.' + attr).strip('.')))
                    if d:
                        out.append(d)
            return out or None
        finally:
            if pushed:
                e.import_stack.pop()

    def entries_defs(self, ents):
        out = []
        for ent in ents:
            if ent[0] == 'b':
                b = ent[1]
                if self.follow_imports and b.kind in ('import', 'from'):
                    out += self.follow(b) or [self.binding_def(b)]
                else:
                    out.append(self.binding_def(b))
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
            return self.entries_defs([('b', tgt[1])])
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
            ents = e.module_attr_entries(v.info, name)
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


class _LocIndex:
    """Positions of the name-like tokens of a module, for ``locate``."""

    def __init__(self, info):
        lines = info.lines
        self.binds = {}
        for sc in _all_scopes(info.scope):
            for name, bl in sc.bindings.items():
                for b in bl:
                    self.binds.setdefault((b.pos, name), b)
        self.names = {}
        self.others = {}
        self.globals = []
        nodes = list(ast.walk(info.tree))
        parents = {}
        for node in nodes:
            for ch in ast.iter_child_nodes(node):
                parents[id(ch)] = node
        others = self.others
        for order, node in enumerate(nodes):
            t = type(node)
            if t is ast.Name:
                self.names.setdefault((node.lineno, node.col_offset, node.id), node)
            elif t is ast.Attribute:
                others.setdefault(('a', node.end_lineno, node.end_col_offset, node.attr),
                                  (order, ('attr', node)))
            elif t is ast.keyword:
                if node.arg is not None and getattr(node, 'lineno', None) is not None:
                    others.setdefault(('k', node.lineno, node.col_offset, node.arg),
                                      (order, ('kwarg', node, parents.get(id(node)))))
            elif t is ast.Import:
                for a in node.names:
                    parts, asp = _alias_parts(lines, a)
                    for k, (p, pp) in enumerate(parts):
                        others.setdefault(('p', pp[0], pp[1], p),
                                          (order, ('module', '.'.join(x for x, _ in parts[:k + 1]), 0)))
            elif t is ast.ImportFrom:
                for p, pp, k, mparts in _from_module_parts(lines, node):
                    others.setdefault(('p', pp[0], pp[1], p),
                                      (order, ('module', '.'.join(mparts[:k + 1]), node.level or 0)))
                for a in node.names:
                    if a.asname:
                        parts, asp = _alias_parts(lines, a)
                        if parts:
                            pp = parts[0][1]
                            others.setdefault(('p', pp[0], pp[1], a.name),
                                              (order, ('fromattr', node.module or '', node.level or 0,
                                                       a.name)))
            elif t in (ast.Global, ast.Nonlocal):
                self.globals.append((node.lineno, node.end_lineno or node.lineno, set(node.names),
                                     order))


def _from_module_parts(lines, node):
    """[(part, pos, index, parts)] for the module name of an ImportFrom."""
    out = []
    if not node.module:
        return out
    st = _line_text(lines, node.lineno)
    c = _char_col(lines, node.lineno, node.col_offset)
    m = _FROM_RE.match(st, c)
    if not m:
        return out
    i = m.end()
    while i < len(st) and st[i] in '. \t':
        i += 1
    mparts = node.module.split('.')
    for k, p in enumerate(mparts):
        j = st.find(p, i)
        if j < 0:
            break
        out.append((p, (node.lineno, j), k, mparts))
        i = j + len(p)
    return out


def _loc_index(info):
    idx = getattr(info, '_loc_idx', None)
    if idx is None:
        idx = info._loc_idx = _LocIndex(info)
    return idx


def locate(info, line, s, e, ident):
    """Find what the identifier spanning [s, e) on `line` refers to."""
    idx = _loc_index(info)
    b = idx.binds.get(((line, s), ident))
    if b is not None:
        return ('binding', b)
    cl = _line_text(info.lines, line)
    bs = len(cl[:s].encode('utf-8'))
    be = len(cl[:e].encode('utf-8'))
    node = idx.names.get((line, bs, ident))
    if node is not None:
        return ('name', node)
    cands = [idx.others.get(('a', line, be, ident)), idx.others.get(('k', line, bs, ident)),
             idx.others.get(('p', line, s, ident))]
    for ln, end, names, order in idx.globals:
        if ident in names and ln <= line <= end:
            cands.append((order, ('global', ident)))
    cands = [c for c in cands if c is not None]
    if not cands:
        return None
    return min(cands, key=lambda c: c[0])[1]


def navigate(path, line, col, mode, project=None, follow_imports=False):
    text = read_source(path)
    lines = text.split('\n')
    _check_pos(lines, line, col)
    cl = lines[line - 1]
    s, e = _cursor_ident(cl, col)
    ident = cl[s:e]
    offset = sum(len(lines[k]) + 1 for k in range(line - 1)) + s
    in_str = in_comment_or_string(text, offset)

    root = project_root(path, project)
    engine = Engine(root, path)
    info = _load_target(engine, path, text)
    tgt = locate(info, line, s, e, ident)
    if in_str and (tgt is None or tgt[0] not in ('name', 'attr')):
        raise NotAName('cursor is not on a name')
    if tgt is None:
        return []
    nav = Navigator(engine, root, follow_imports)
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


def _cursor_ident(cl, col):
    """Return (start, end) of the identifier under the cursor or raise NotAName."""
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
    return s, e


def _check_pos(lines, line, col):
    if line < 1 or line > len(lines):
        raise SithError('line out of range')
    if col < 0 or col > len(lines[line - 1]):
        raise SithError('column out of range')


def _load_target(engine, path, text):
    tree, fixed = parse_source(text, with_text=True)
    base = os.path.basename(path)
    info = ModuleInfo(os.path.abspath(path), tree, base[:-3] if base.endswith('.py') else base,
                      fixed)
    engine.static_cache[os.path.realpath(path)] = info
    return info


def _skip_dir(parent, name):
    if name.startswith('.') or name in ('__pycache__', 'node_modules', 'site-packages'):
        return True
    return os.path.isfile(os.path.join(parent, name, 'pyvenv.cfg'))


def project_files(root):
    """All ``.py`` files of the project below ``root``, sorted."""
    out = []
    for d, dirs, files in os.walk(root):
        dirs[:] = sorted(x for x in dirs if not _skip_dir(d, x))
        for f in sorted(files):
            full = os.path.join(d, f)
            if f.endswith('.py') and os.path.isfile(full):
                out.append(full)
    return out


def _module_name(root, path):
    rp = os.path.relpath(os.path.abspath(path), root)
    if rp.startswith('..'):
        return os.path.splitext(os.path.basename(path))[0]
    parts = os.path.splitext(rp)[0].split(os.sep)
    if parts[-1] == '__init__' and len(parts) > 1:
        parts.pop()
    return '.'.join(parts)


# ---------------------------------------------------------------------------
# Signatures
# ---------------------------------------------------------------------------

_DEF_LINE_RE = re.compile(r'\s*(?:async\s+def|def|class)\s')


def _skip_string(text, i, n):
    """``text[i]`` starts a string; return the index after it (or ``n``)."""
    c = text[i]
    q = c * 3 if text.startswith(c * 3, i) else c
    j = i + len(q)
    while j < n:
        ch = text[j]
        if ch == '\\':
            j += 2
            continue
        if len(q) == 1 and ch == '\n':
            return j
        if text.startswith(q, j):
            return j + len(q)
        j += 1
    return n + 1


def _open_brackets(text, end):
    """Unclosed brackets [(index, char)] before ``end``, and whether ``end``
    lies inside a comment."""
    stack = []
    i = 0
    line_start = True
    while i < end:
        c = text[i]
        if line_start:
            line_start = False
            if stack and _DEF_LINE_RE.match(text, i):
                stack = []
        if c == '\n':
            line_start = True
        elif c == '#':
            j = text.find('\n', i)
            if j < 0 or j >= end:
                return stack, True
            i = j
            continue
        elif c in '"\'':
            i = _skip_string(text, i, end)
            continue
        elif c in '([{':
            stack.append((i, c))
        elif c in ')]}':
            want = {')': '(', ']': '[', '}': '{'}[c]
            for k in range(len(stack) - 1, -1, -1):
                if stack[k][1] == want:
                    del stack[k:]
                    break
        i += 1
    return stack, False


def _paren_kind(text, pos):
    """Classify the '(' at ``pos``: 'call', 'def' (parameter list) or 'other'."""
    i = pos
    while i > 0 and text[i - 1] in ' \t\n\\':
        i -= 1
    if i == 0:
        return 'other'
    c = text[i - 1]
    if c in ')]':
        return 'call'
    if c in '"\'':
        return 'call'
    if not is_ident_char(c):
        return 'other'
    j = i
    while j > 0 and is_ident_char(text[j - 1]):
        j -= 1
    word = text[j:i]
    if word[0].isdigit():
        return 'other'
    if keyword.iskeyword(word) and word not in ('None', 'True', 'False'):
        return 'other'
    k = j
    while k > 0 and text[k - 1] in ' \t':
        k -= 1
    m = k
    while m > 0 and is_ident_char(text[m - 1]):
        m -= 1
    if text[m:k] in ('def', 'class'):
        return 'def'
    return 'call'


def _call_args(text, start, cursor):
    """Split the arguments of a call opened at ``start - 1``.

    Returns (previous_args, current_arg) as source strings.
    """
    depth = 0
    seg = start
    prev = []
    end = len(text)
    i = start
    n = len(text)
    while i < n:
        c = text[i]
        if c == '#':
            j = text.find('\n', i)
            if j < 0:
                break
            i = j
            continue
        if c in '"\'':
            i = _skip_string(text, i, n)
            continue
        if c == '\n' and i >= cursor:
            end = i
            break
        if c in '([{':
            depth += 1
        elif c in ')]}':
            if depth == 0:
                end = i
                break
            depth -= 1
        elif c == ',' and depth == 0:
            if i < cursor:
                prev.append(text[seg:i])
                seg = i + 1
            else:
                end = i
                break
        i += 1
    if end < cursor:
        end = cursor
    return prev, text[seg:end]


_KWARG_RE = re.compile(r'\s*((?!\d)\w+)\s*=(?!=)')


def _arg_kind(seg):
    s = re.sub(r'#[^\n]*', '', seg).strip()
    if s.startswith('**'):
        return ('dstar', None)
    if s.startswith('*'):
        return ('star', None)
    m = _KWARG_RE.match(s)
    if m:
        return ('kw', m.group(1))
    return ('pos', None)


def _param_index(params, prev, cur):
    """Index of the parameter bound to the current argument (or None)."""
    positional = [i for i, p in enumerate(params) if p[1] in ('posonly', 'pos')]
    vararg = next((i for i, p in enumerate(params) if p[1] == 'vararg'), None)
    kwarg = next((i for i, p in enumerate(params) if p[1] == 'kwarg'), None)
    kind, name = cur
    if kind == 'kw':
        for i, p in enumerate(params):
            if p[0] == name and p[1] in ('pos', 'kwonly'):
                return i
        return kwarg
    if kind == 'dstar':
        return kwarg
    kinds = [k for k, _ in prev]
    if 'kw' in kinds or 'dstar' in kinds:
        return None
    if 'star' in kinds:
        return vararg
    n = len(prev)
    if n < len(positional):
        return positional[n]
    return vararg


class SigBuilder:
    def __init__(self, engine, nav):
        self.e = engine
        self.nav = nav

    @staticmethod
    def src(info, node):
        try:
            s = ast.get_source_segment(info.text, node)
        except Exception:
            s = None
        if not s:
            s = _unparse(node)
        return _ws(s)

    def param_text(self, info, a, d):
        s = a.arg
        if a.annotation is not None:
            s += ': ' + self.src(info, a.annotation)
        if d is not None:
            s += '=' + self.src(info, d)
        return s

    def node_params(self, node, info, skip):
        """[(name, kind, text)] for a function node."""
        a = node.args
        posonly = list(getattr(a, 'posonlyargs', []))
        positional = posonly + list(a.args)
        defaults = [None] * (len(positional) - len(a.defaults)) + list(a.defaults)
        out = []
        for i, p in enumerate(positional):
            out.append((p.arg, 'posonly' if i < len(posonly) else 'pos',
                        self.param_text(info, p, defaults[i])))
        if skip and out:
            out = out[1:]
        if a.vararg is not None:
            out.append((a.vararg.arg, 'vararg', '*' + self.param_text(info, a.vararg, None)))
        for p, d in zip(a.kwonlyargs, a.kw_defaults):
            out.append((p.arg, 'kwonly', self.param_text(info, p, d)))
        if a.kwarg is not None:
            out.append((a.kwarg.arg, 'kwarg', '**' + self.param_text(info, a.kwarg, None)))
        return out

    def sig(self, name, params, ret, doc, mp, line):
        desc = 'def %s(%s)' % (name, ', '.join(p[2] for p in params))
        if ret:
            desc += ' -> ' + ret
        return {'name': name, 'params': params, 'description': desc, 'docstring': doc or '',
                '_key': (mp, line)}

    def func_sigs(self, f, name=None, doc=None, with_ret=True):
        out = []
        node0 = f.node
        src_doc = _doc(node0) if not isinstance(node0, ast.Lambda) else ''
        for node, vsc in self.e.sig_variants(f):
            info = vsc.module
            params = self.node_params(node, info, f.skip)
            if isinstance(node, ast.Lambda):
                nm = name or '<lambda>'
                ret = None
                d = doc or ''
            else:
                nm = name or node.name
                ret = self.src(info, node.returns) if with_ret and node.returns is not None \
                    else None
                d = doc if doc is not None else (_doc(node) or src_doc)
            out.append(self.sig(nm, params, ret, d, self.nav.rel(info.path), node.lineno))
        return out

    def dataclass_params(self, cls):
        fields = {}
        is_dc = False
        for c in reversed(self.e.mro(cls)):
            node = c.scope.node
            nt = any((isinstance(b, ast.Name) and b.id == 'NamedTuple') or
                     (isinstance(b, ast.Attribute) and b.attr == 'NamedTuple') for b in node.bases)
            if 'dataclass' not in _decorator_names(node) and not nt:
                continue
            is_dc = True
            info = c.scope.module
            for st in node.body:
                if isinstance(st, ast.AnnAssign) and isinstance(st.target, ast.Name):
                    ann = st.annotation
                    an = ann.value if isinstance(ann, ast.Subscript) else ann
                    if (isinstance(an, ast.Name) and an.id == 'ClassVar') or \
                            (isinstance(an, ast.Attribute) and an.attr == 'ClassVar'):
                        continue
                    a = ast.arg(arg=st.target.id, annotation=st.annotation)
                    fields[st.target.id] = (st.target.id, 'pos', self.param_text(info, a, st.value))
        return list(fields.values()) if is_dc else None

    def class_sigs(self, cls):
        node = cls.scope.node
        info = cls.scope.module
        mp = self.nav.rel(info.path)
        cdoc = _doc(node)
        inits = [g for g in self.e.get_attr(StInst(cls), '__init__') if isinstance(g, StFunc)]
        if inits:
            out = []
            for g in inits:
                d = cdoc or (_doc(g.node) if not isinstance(g.node, ast.Lambda) else '')
                for s in self.func_sigs(g, node.name, d, with_ret=False):
                    s['_key'] = (mp, node.lineno)
                    out.append(s)
            return out
        params = self.dataclass_params(cls)
        if params is None:
            params = []
            for c in self.e.mro(cls):
                for bn in c.scope.node.bases:
                    for bv in self.e.infer(bn, c.scope.parent, None):
                        if isinstance(bv, RtV) and inspect.isclass(bv.obj) and bv.obj is not object:
                            rs = self.rt_sigs(bv.obj)
                            if rs:
                                params = rs[0]['params']
                                break
                    if params:
                        break
                if params:
                    break
        return [self.sig(node.name, params, None, cdoc, mp, node.lineno)]

    def rt_sigs(self, o):
        try:
            sig = inspect.signature(o)
        except (TypeError, ValueError):
            return []
        except Exception:
            return []
        params = []
        kinds = {inspect.Parameter.POSITIONAL_ONLY: 'posonly',
                 inspect.Parameter.POSITIONAL_OR_KEYWORD: 'pos',
                 inspect.Parameter.VAR_POSITIONAL: 'vararg',
                 inspect.Parameter.KEYWORD_ONLY: 'kwonly',
                 inspect.Parameter.VAR_KEYWORD: 'kwarg'}
        for p in sig.parameters.values():
            k = kinds[p.kind]
            t = p.name
            if p.annotation is not inspect.Parameter.empty:
                t += ': ' + inspect.formatannotation(p.annotation)
            if p.default is not inspect.Parameter.empty:
                try:
                    t += '=' + repr(p.default)
                except Exception:
                    t += '=...'
            if k == 'vararg':
                t = '*' + t
            elif k == 'kwarg':
                t = '**' + t
            params.append((p.name, k, t))
        ret = None
        if not inspect.isclass(o) and sig.return_annotation is not inspect.Signature.empty:
            ret = inspect.formatannotation(sig.return_annotation)
        name = getattr(o, '__name__', None) or type(o).__name__
        mp, line, _ = self.nav.rt_loc(o)
        return [self.sig(name, params, ret, _rt_doc(o), mp, line)]

    def value_sigs(self, v):
        if isinstance(v, StFunc):
            return self.func_sigs(v)
        if isinstance(v, StClass):
            return self.class_sigs(v)
        if isinstance(v, StInst):
            out = []
            for g in self.e.get_attr(v, '__call__'):
                if isinstance(g, StFunc):
                    out += self.func_sigs(g)
            return out
        if isinstance(v, RtV):
            o = v.obj
            if inspect.isclass(o) or inspect.isroutine(o) or callable(o):
                if inspect.ismodule(o):
                    return []
                return self.rt_sigs(o)
        return []


def signatures(path, line, col, project=None):
    text = read_source(path)
    lines = text.split('\n')
    _check_pos(lines, line, col)
    offset = sum(len(lines[k]) + 1 for k in range(line - 1)) + col
    stack, in_comment = _open_brackets(text, offset)
    if in_comment:
        return []
    paren = None
    for pos, ch in reversed(stack):
        if ch != '(':
            continue
        kind = _paren_kind(text, pos)
        if kind == 'def':
            return []
        if kind == 'call':
            paren = pos
            break
    if paren is None:
        return []
    expr = extract_expr(text, paren).strip()
    if not expr:
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

    root = project_root(path, project)
    engine = Engine(root, path)
    tree, fixed = parse_source(text, (line, col), with_text=True)
    info = ModuleInfo(os.path.abspath(path), tree, '__main__', fixed)
    engine.static_cache[os.path.realpath(path)] = info
    pline = text.count('\n', 0, paren) + 1
    pcol = paren - (text.rfind('\n', 0, paren) + 1)
    pl = lines[pline - 1]
    pbcol = len(pl[:pcol].encode('utf-8'))
    sc = info.cursor_scope
    if sc is None:
        cl = lines[line - 1]
        sc = find_scope_by_pos(info.scope, line, len(cl[:col].encode('utf-8')), info.lines,
                               cl[:col])
    while sc.kind in ('lambda', 'comp') and sc.parent is not None and \
            (sc.node.lineno, sc.node.col_offset) > (pline, pbcol):
        sc = sc.parent

    nav = Navigator(engine, root)
    sb = SigBuilder(engine, nav)
    sigs = []
    for v in engine.infer(node, sc, (pline, pbcol)):
        try:
            sigs += sb.value_sigs(v)
        except RecursionError:
            pass
    prev, cur = _call_args(text, paren + 1, offset)
    prev = [_arg_kind(a) for a in prev]
    cur = _arg_kind(cur)
    out = []
    seen = set()
    for s in sorted(sigs, key=lambda s: s['_key']):
        k = (s['name'], tuple(p[2] for p in s['params']), s['description'])
        if k in seen:
            continue
        seen.add(k)
        out.append({'name': s['name'], 'params': [p[2] for p in s['params']],
                    'index': _param_index(s['params'], prev, cur),
                    'description': s['description'], 'docstring': s['docstring']})
    return out


# ---------------------------------------------------------------------------
# References
# ---------------------------------------------------------------------------

class RefFinder:
    def __init__(self, engine, nav):
        self.e = engine
        self.nav = nav

    def value_key(self, v):
        if isinstance(v, StMod):
            if v.info is not None:
                return ('m', os.path.realpath(v.info.path))
            return ('m', os.path.realpath(v.pkgdir or ''))
        if isinstance(v, StFunc) and not isinstance(v.node, ast.Lambda) and \
                v.scope.parent is not None:
            return ('s', id(v.scope.parent), v.node.name)
        if isinstance(v, StClass) and v.scope.parent is not None:
            return ('s', id(v.scope.parent), v.name)
        if isinstance(v, RtV) and inspect.ismodule(v.obj):
            return ('rtm', v.obj.__name__)
        return _vkey(v)

    def values_keys(self, vals):
        return set(self.value_key(v) for v in vals if v is not None)

    def entries_keys(self, ents, seen):
        out = set()
        for ent in ents:
            if ent[0] == 'b':
                out |= self.binding_keys(ent[1], seen)
            else:
                try:
                    v = ent[1]()
                except Exception:
                    v = None
                if v is not None:
                    out.add(self.value_key(v))
        return out

    def binding_keys(self, b, seen=frozenset()):
        if b.kind in ('import', 'from'):
            return self.import_keys(b, seen)
        owner = b.scope.parent if b.attr else b.scope
        return {('s', id(owner), b.name)}

    def bindings_keys(self, bl, seen=frozenset()):
        out = set()
        for b in bl:
            out |= self.binding_keys(b, seen)
        return out

    def module_attr_keys(self, mv, attr, seen):
        e = self.e
        keys = set()
        if isinstance(mv, StMod):
            if mv.info is not None:
                keys = self.entries_keys(e.module_attr_entries(mv.info, attr), seen)
                if not keys:
                    stub = e.stub_for(mv.info)
                    if stub is not None:
                        keys = self.entries_keys(e.module_attr_entries(stub, attr), seen)
            if not keys and mv.pkgdir:
                found = e.find_local(attr, mv.pkgdir)
                if found:
                    keys = {self.value_key(e.static_module(found, attr))}
        elif mv is not None:
            keys = self.values_keys(e.get_attr(mv, attr))
        return keys

    def import_keys(self, b, seen):
        if id(b) in seen:
            return set()
        seen = seen | {id(b)}
        e = self.e
        sc = b.scope
        if b.kind == 'import':
            full, asname = b.extra
            mv = e.resolve_module(full if asname else full.split('.')[0], sc.module.dir)
            return {self.value_key(mv)}
        mod, level, attr = b.extra
        mv = e.resolve_module(mod, sc.module.dir, level)
        pushed = sc.kind == 'module'
        if pushed:
            e.import_stack.append((sc.module, b.line))
        try:
            keys = self.module_attr_keys(mv, attr, seen)
        finally:
            if pushed:
                e.import_stack.pop()
        return keys or {('from?', mod, level, attr)}

    def name_keys(self, info, node):
        e = self.e
        name = node.id
        sc = self.nav.scope_of(info, node)
        for s, _ in e.chain(sc):
            bl = s.bindings.get(name)
            if bl:
                return self.bindings_keys(bl)
            if s.stars:
                for (sl, mod, lvl) in s.stars:
                    mv = e.resolve_module(mod, s.module.dir, lvl)
                    ent = e.star_names(mv).get(name)
                    if ent is not None:
                        return self.entries_keys([ent], frozenset())
        if hasattr(builtins, name):
            return {self.value_key(RtV(getattr(builtins, name)))}
        return {('unresolved', name)}

    def target_keys(self, info, tgt):
        e = self.e
        kind = tgt[0]
        if kind == 'binding':
            return self.binding_keys(tgt[1])
        if kind == 'name':
            return self.name_keys(info, tgt[1])
        if kind == 'attr':
            node = tgt[1]
            if isinstance(node.ctx, ast.Store):
                v, b = self.nav.self_store_binding(info, node)
                if b is not None:
                    return self.binding_keys(b)
            sc = self.nav.scope_of(info, node)
            out = set()
            for v in e.infer(node.value, sc, None):
                if isinstance(v, (StInst, StClass, SuperInst)):
                    out |= self.bindings_keys(e.attr_bindings(v, node.attr))
                else:
                    out |= self.module_attr_keys(v, node.attr, frozenset())
            return out
        if kind == 'kwarg':
            return self.bindings_keys(self.nav.call_params(info, tgt[1], tgt[2]))
        if kind == 'module':
            return {self.value_key(e.resolve_module(tgt[1], info.dir, tgt[2]))}
        if kind == 'fromattr':
            mv = e.resolve_module(tgt[1], info.dir, tgt[2])
            return self.module_attr_keys(mv, tgt[3], frozenset())
        if kind == 'global':
            return {('s', id(info.scope), tgt[1])}
        return set()

    def keys(self, info, tgt):
        try:
            return self.target_keys(info, tgt)
        except RecursionError:
            return set()


def _candidates(info, ident):
    """Character positions (line, col) of tokens spelled ``ident``."""
    lines = info.lines
    out = set()
    for sc in _all_scopes(info.scope):
        for b in sc.bindings.get(ident, ()):
            out.add(b.pos)
    for node in ast.walk(info.tree):
        t = type(node)
        if t is ast.Name:
            if node.id == ident:
                out.add((node.lineno, _char_col(lines, node.lineno, node.col_offset)))
        elif t is ast.Attribute:
            if node.attr == ident:
                ln = node.end_lineno
                out.add((ln, _char_col(lines, ln, node.end_col_offset) - len(ident)))
        elif t is ast.keyword:
            if node.arg == ident and getattr(node, 'lineno', None) is not None:
                out.add((node.lineno, _char_col(lines, node.lineno, node.col_offset)))
        elif t is ast.Import:
            for a in node.names:
                for p, pp in _alias_parts(lines, a)[0]:
                    if p == ident:
                        out.add(pp)
        elif t is ast.ImportFrom:
            for p, pp, k, mparts in _from_module_parts(lines, node):
                if p == ident:
                    out.add(pp)
            for a in node.names:
                if a.name == ident:
                    parts = _alias_parts(lines, a)[0]
                    if parts:
                        out.add(parts[0][1])
        elif t in (ast.Global, ast.Nonlocal):
            if ident in node.names:
                rx = re.compile(r'(?<!\w)' + re.escape(ident) + r'(?!\w)')
                for ln in range(node.lineno, (node.end_lineno or node.lineno) + 1):
                    m = rx.search(_line_text(lines, ln))
                    if m:
                        out.add((ln, m.start()))
                        break
    return sorted(out)


def _is_def_target(tgt):
    if tgt[0] == 'binding':
        return True
    if tgt[0] == 'attr' and isinstance(tgt[1].ctx, ast.Store):
        return True
    return False


class _RefCtx:
    """Everything a reference search found, for the refactoring commands."""

    def __init__(self):
        self.ident = None
        self.info = None
        self.tgt = None
        self.keys = set()
        self.engine = None
        self.nav = None
        self.rf = None
        self.root = None
        self.hits = []  # (info, line, col, target)


def find_refs(path, line, col, scope='file', project=None):
    text = read_source(path)
    lines = text.split('\n')
    _check_pos(lines, line, col)
    cl = lines[line - 1]
    s, e = _cursor_ident(cl, col)
    ident = cl[s:e]
    offset = sum(len(lines[k]) + 1 for k in range(line - 1)) + s
    in_str = in_comment_or_string(text, offset)

    ctx = _RefCtx()
    ctx.ident = ident
    ctx.root = root = project_root(path, project)
    ctx.engine = engine = Engine(root, path)
    ctx.info = info = _load_target(engine, path, text)
    ctx.tgt = tgt = locate(info, line, s, e, ident)
    if in_str and (tgt is None or tgt[0] not in ('name', 'attr')):
        raise NotAName('cursor is not on a name')
    if tgt is None:
        return ctx
    ctx.nav = nav = Navigator(engine, root)
    ctx.rf = rf = RefFinder(engine, nav)
    ctx.keys = keys = rf.keys(info, tgt)
    hits = {}

    def add(finfo, ln, c, t):
        hits[(nav.rel(finfo.path), ln, c)] = (finfo, ln, c, t)

    add(info, line, s, tgt)
    if keys:
        if scope == 'project':
            files = project_files(root)
            if not any(os.path.realpath(f) == os.path.realpath(path) for f in files):
                files.append(os.path.abspath(path))
        else:
            files = [os.path.abspath(path)]
        for f in files:
            if os.path.realpath(f) == os.path.realpath(path):
                finfo = info
            else:
                try:
                    with open(f, 'rb') as fh:
                        if ident.encode('utf-8') not in fh.read():
                            continue
                except OSError:
                    continue
                finfo = engine.load_static(f, _module_name(root, f))
                if finfo is None:
                    continue
            for ln, c in _candidates(finfo, ident):
                t = locate(finfo, ln, c, c + len(ident), ident)
                if t is None:
                    continue
                if rf.keys(finfo, t) & keys:
                    add(finfo, ln, c, t)
    ctx.hits = [hits[k] for k in sorted(hits)]
    return ctx


def references(path, line, col, scope='file', project=None):
    ctx = find_refs(path, line, col, scope, project)
    out = []
    for finfo, ln, c, t in ctx.hits:
        out.append({'module_path': ctx.nav.rel(finfo.path), 'line': ln, 'column': c,
                    'is_definition': _is_def_target(t)})
    return out


# ---------------------------------------------------------------------------
# Search / names
# ---------------------------------------------------------------------------

def _strip_doc(d):
    d = dict(d)
    d.pop('docstring', None)
    return d


def search(query, project=None):
    root = os.path.abspath(project) if project else os.getcwd()
    if not os.path.isdir(root):
        raise SithError('project directory not found: %s' % project)
    engine = Engine(root)
    nav = Navigator(engine, root)
    q = query.lower()
    found = []
    for f in project_files(root):
        info = engine.load_static(f, _module_name(root, f))
        if info is None:
            continue
        stack = [info.scope]
        while stack:
            sc = stack.pop()
            for name, bl in sc.bindings.items():
                if MARK in name:
                    continue
                low = name.lower()
                if q not in low:
                    continue
                for b in bl:
                    if b.kind in ('def', 'class') or \
                            (sc.kind == 'module' and b.kind in ('assign', 'ann', 'unpack')):
                        found.append(b)
            for ch in sc.children:
                if ch.kind == 'class':
                    stack.append(ch)
    out = []
    seen = set()
    for b in found:
        try:
            d = _strip_doc(nav.binding_def(b))
        except RecursionError:
            continue
        k = (d['module_path'], d['line'], d['column'], d['name'])
        if k in seen:
            continue
        seen.add(k)
        low = d['name'].lower()
        g = 0 if low == q else (1 if low.startswith(q) else 2)
        out.append((g, d))
    out.sort(key=lambda x: (x[0], x[1]['module_path'], x[1]['line'], x[1]['column']))
    return [d for _, d in out]


def names(path, all_scopes=False, project=None):
    text = read_source(path)
    root = project_root(path, project)
    engine = Engine(root, path)
    info = _load_target(engine, path, text)
    nav = Navigator(engine, root)
    bindings = []
    scopes = _all_scopes(info.scope) if all_scopes else [info.scope]
    for sc in scopes:
        for name, bl in sc.bindings.items():
            if MARK not in name:
                bindings += bl
        if all_scopes and sc.kind == 'class':
            for bl in engine.self_attr_map(class_value(sc)).values():
                bindings += bl
    out = []
    seen = set()
    for b in bindings:
        try:
            d = nav.binding_def(b)
        except RecursionError:
            continue
        if b.kind in ('def', 'class'):
            d['line'], d['column'] = b.pos
        k = (d['line'], d['column'], d['name'])
        if k in seen:
            continue
        seen.add(k)
        d['is_definition'] = True
        out.append(d)
    out.sort(key=lambda d: (d['line'], d['column']))
    return out


# ---------------------------------------------------------------------------
# Refactoring
# ---------------------------------------------------------------------------

def _check_ident(name, what='name'):
    if not name or not name.isidentifier() or keyword.iskeyword(name):
        raise SithError('invalid %s %r: not a valid Python identifier' % (what, name))


def _line_starts(text):
    out = [0]
    for i, c in enumerate(text):
        if c == '\n':
            out.append(i + 1)
    return out


def _apply_edits(text, edits):
    """Apply (start, end, replacement) character-offset edits to ``text``."""
    out = []
    last = len(text)
    for s, e, r in sorted(set(edits), key=lambda x: (x[0], x[1]), reverse=True):
        if e > last:
            raise SithError('overlapping edits')
        out.append(text[e:last])
        out.append(r)
        last = s
    out.append(text[:last])
    return ''.join(reversed(out))


def _node_span(lines, node):
    """Character span ((line, col), (end_line, end_col)) of an AST node."""
    return ((node.lineno, _char_col(lines, node.lineno, node.col_offset)),
            (node.end_lineno, _char_col(lines, node.end_lineno, node.end_col_offset)))


def _strict_parse(text):
    try:
        with warnings.catch_warnings():
            warnings.simplefilter('ignore')
            return ast.parse(text)
    except (SyntaxError, ValueError, RecursionError, MemoryError) as e:
        raise SithError('cannot refactor a file with syntax errors: %s' % e)


def _try_strict(text):
    try:
        with warnings.catch_warnings():
            warnings.simplefilter('ignore')
            return ast.parse(text)
    except (SyntaxError, ValueError, RecursionError, MemoryError):
        return None


class _Changes:
    """New file contents (and path renames) produced by a refactoring."""

    def __init__(self, root):
        self.root = os.path.realpath(root)
        self.orig = {}  # realpath -> (text, newline, bom)
        self.new = {}
        self.renames = []

    def text(self, path):
        p = os.path.realpath(path)
        if p not in self.orig:
            try:
                with open(p, 'rb') as f:
                    raw = f.read()
            except OSError as e:
                raise SithError('cannot read file: %s' % e)
            text = raw.decode('utf-8', errors='surrogateescape')
            bom = text.startswith('﻿')
            if bom:
                text = text[1:]
            nl = '\r\n' if '\r\n' in text else '\n'
            self.orig[p] = (text.replace('\r\n', '\n').replace('\r', '\n'), nl, bom)
        return self.orig[p][0]

    def current(self, path):
        p = os.path.realpath(path)
        if p in self.new:
            return self.new[p]
        return self.text(p)

    def set(self, path, text):
        p = os.path.realpath(path)
        self.text(p)
        self.new[p] = text

    def rel(self, p):
        try:
            rp = os.path.relpath(p, self.root)
        except ValueError:
            return _posix(p)
        return _posix(rp)

    def changed(self):
        return sorted((p, self.orig[p][0], t) for p, t in self.new.items()
                      if t != self.orig[p][0])

    def final(self, p, text):
        _, nl, bom = self.orig[p]
        if nl != '\n':
            text = text.replace('\n', nl)
        if bom:
            text = '﻿' + text
        return text

    def to_path(self, p):
        for old, new in self.renames:
            if p == old or p.startswith(old + os.sep):
                return new + p[len(old):]
        return p

    def output(self, diff):
        if not diff:
            out = {'changed_files': {self.rel(p): self.final(p, t) for p, _, t in self.changed()},
                   'renames': {self.rel(o): self.rel(n) for o, n in self.renames}}
            return json.dumps(out, separators=(',', ':')) + '\n'
        import difflib
        text = ''
        for o, n in self.renames:
            text += 'rename from %s\nrename to %s\n' % (self.rel(o), self.rel(n))
        for p, old, new in self.changed():
            a = old.splitlines(True)
            b = new.splitlines(True)
            if a and not a[-1].endswith('\n'):
                a[-1] += '\n'
            if b and not b[-1].endswith('\n'):
                b[-1] += '\n'
            text += ''.join(difflib.unified_diff(a, b, fromfile=self.rel(p),
                                                 tofile=self.rel(self.to_path(p))))
        return text


# ----- rename -----

def _module_target(ctx):
    """Path of the project module/package the cursor name denotes, if any."""
    for k in ctx.keys:
        if k[0] != 'm' or not k[1]:
            continue
        p = k[1]
        base = os.path.basename(p)
        if base in ('__init__.py', '__init__.pyi'):
            p = os.path.dirname(p)
            base = os.path.basename(p)
        elif base.endswith(('.py', '.pyi')):
            base = base.rsplit('.', 1)[0]
        if base != ctx.ident:
            continue
        if not _inside(p, ctx.root):
            raise SithError('cannot rename module %r: it is not part of the project' % ctx.ident)
        return p
    for k in ctx.keys:
        if k[0] == 'rtm' and k[1].split('.')[-1] == ctx.ident:
            raise SithError('cannot rename module %r: it is not part of the project' % ctx.ident)
    return None


def _cursor_binding(ctx):
    tgt = ctx.tgt
    if tgt[0] == 'binding':
        return tgt[1]
    if tgt[0] == 'name':
        sc = ctx.nav.scope_of(ctx.info, tgt[1])
        for s, _ in ctx.engine.chain(sc):
            bl = s.bindings.get(ctx.ident)
            if bl:
                return bl[-1]
    return None


def _is_alias(b):
    if b is None:
        return False
    if b.kind == 'import':
        return bool(b.extra[1])
    if b.kind == 'from':
        return b.name != b.extra[2]
    return False


def _class_has(engine, csc, name):
    if name in csc.bindings:
        return True
    try:
        return name in engine.self_attr_map(class_value(csc))
    except Exception:
        return False


def _rename_collision(ctx, hits, new_name):
    e = ctx.engine
    for finfo, ln, c, t in hits:
        kind = t[0]
        scopes = []
        if kind == 'binding':
            b = t[1]
            if b.attr:
                if b.scope.parent is not None and b.scope.parent.kind == 'class' and \
                        _class_has(e, b.scope.parent, new_name):
                    return True
                continue
            if b.scope.kind == 'class':
                if _class_has(e, b.scope, new_name):
                    return True
                continue
            scopes = [s for s, _ in e.chain(b.scope)]
        elif kind == 'name':
            scopes = [s for s, _ in e.chain(ctx.nav.scope_of(finfo, t[1]))]
        elif kind == 'global':
            scopes = [finfo.scope]
        elif kind == 'attr' and isinstance(t[1].ctx, ast.Store):
            v, b = ctx.nav.self_store_binding(finfo, t[1])
            if b is not None and b.scope.parent is not None and \
                    b.scope.parent.kind == 'class' and _class_has(e, b.scope.parent, new_name):
                return True
        for s in scopes:
            if new_name in s.bindings:
                return True
    return False


def rename(path, line, col, new_name, project=None):
    _check_ident(new_name, 'new name')
    ctx = find_refs(path, line, col, 'project', project)
    if ctx.tgt is None:
        raise NotAName('cursor is not on a renamable name')
    ident = ctx.ident
    changes = _Changes(ctx.root)
    if new_name == ident:
        return changes
    hits = ctx.hits
    mod = _module_target(ctx)
    if mod is None and _is_alias(_cursor_binding(ctx)):
        hits = [h for h in hits if h[0] is ctx.info]
    if mod is not None:
        if os.path.isdir(mod):
            dest = os.path.join(os.path.dirname(mod), new_name)
        else:
            dest = os.path.join(os.path.dirname(mod), new_name + os.path.splitext(mod)[1])
        if os.path.exists(dest) or os.path.exists(os.path.join(os.path.dirname(mod), new_name + '.py')) \
                or os.path.isdir(os.path.join(os.path.dirname(mod), new_name)):
            raise SithError('cannot rename module %r to %r: %s already exists'
                            % (ident, new_name, changes.rel(dest)))
        changes.renames.append((os.path.realpath(mod), os.path.realpath(dest)))
    if _rename_collision(ctx, hits, new_name):
        raise SithError('cannot rename %r to %r: the name %r already exists in scope'
                        % (ident, new_name, new_name))
    per_file = {}
    for finfo, ln, c, t in hits:
        per_file.setdefault(os.path.realpath(finfo.path), []).append((ln, c))
    for p, poss in per_file.items():
        text = changes.text(p)
        lines = text.split('\n')
        starts = _line_starts(text)
        edits = []
        for ln, c in poss:
            if ln > len(lines) or lines[ln - 1][c:c + len(ident)] != ident:
                continue
            o = starts[ln - 1] + c
            edits.append((o, o + len(ident), new_name))
        if edits:
            changes.set(p, _apply_edits(text, edits))
    return changes


# ----- inline -----

def _expr_text(text, lines, node):
    """Source text of ``node`` including parentheses that wrap it."""
    starts = _line_starts(text)
    (l1, c1), (l2, c2) = _node_span(lines, node)
    s = starts[l1 - 1] + c1
    e = starts[l2 - 1] + c2
    while True:
        i = s - 1
        while i >= 0 and text[i] in ' \t\n\\':
            i -= 1
        j = e
        while j < len(text) and text[j] in ' \t\n\\':
            j += 1
        if i >= 0 and j < len(text) and text[i] == '(' and text[j] == ')':
            s, e = i, j + 1
            continue
        break
    return text[s:e]


def _replace_node(tree, old, new):
    for parent in ast.walk(tree):
        for field, value in ast.iter_fields(parent):
            if value is old:
                setattr(parent, field, new)
                return True
            if isinstance(value, list):
                for i, x in enumerate(value):
                    if x is old:
                        value[i] = new
                        return True
    return False


def _find_expr(tree, lines, span, types):
    for n in ast.walk(tree):
        if isinstance(n, types) and getattr(n, 'lineno', None) is not None and \
                _node_span(lines, n) == span:
            return n
    return None


def _needs_parens(text, tree, span, rhs, value):
    """Would replacing ``span`` of ``text`` by ``rhs`` change the parsed meaning?"""
    import copy
    lines = text.split('\n')
    if tree is None:
        return not isinstance(value, (ast.Name, ast.Constant, ast.Attribute, ast.Call,
                                      ast.Subscript, ast.List, ast.Tuple, ast.Dict, ast.Set,
                                      ast.ListComp, ast.SetComp, ast.DictComp,
                                      ast.GeneratorExp, ast.JoinedStr)) or \
            isinstance(value, ast.Tuple)
    t2 = copy.deepcopy(tree)
    node = _find_expr(t2, lines, span, (ast.Name, ast.Attribute))
    if node is None or not _replace_node(t2, node, copy.deepcopy(value)):
        return True
    starts = _line_starts(text)
    s = starts[span[0][0] - 1] + span[0][1]
    e = starts[span[1][0] - 1] + span[1][1]
    cand = _try_strict(text[:s] + rhs + text[e:])
    if cand is None:
        return True
    return ast.dump(cand) != ast.dump(t2)


def _stmt_parent_body(tree, stmt):
    for n in ast.walk(tree):
        for field in ('body', 'orelse', 'finalbody', 'handlers'):
            body = getattr(n, field, None)
            if isinstance(body, list) and any(x is stmt for x in body):
                return body
    return None


def _removal_edit(text, lines, tree, stmt):
    """Edit deleting statement ``stmt`` (replacing it by ``pass`` if needed)."""
    starts = _line_starts(text)
    (l1, c1), (l2, c2) = _node_span(lines, stmt)
    s = starts[l1 - 1] + c1
    e = starts[l2 - 1] + c2
    body = _stmt_parent_body(tree, stmt)
    before = lines[l1 - 1][:c1]
    after = lines[l2 - 1][c2:]
    if body is not None and len(body) == 1:
        return (s, e, 'pass')
    m = re.match(r'\s*;\s*', after)
    if m:
        return (s, e + m.end(), '')
    if before.strip():
        m = re.search(r'\s*;\s*$', before)
        if m:
            return (starts[l1 - 1] + m.start(), e, '')
    code_after = _code_part(after).strip()
    if not before.strip() and not code_after:
        ls = starts[l1 - 1]
        le = starts[l2] if l2 < len(starts) else len(text)
        return (ls, le, '')
    return (s, e, 'pass')


def inline(path, line, col, project=None):
    ctx = find_refs(path, line, col, 'project', project)
    if ctx.tgt is None:
        raise NotAName('cursor is not on a name')
    ident = ctx.ident
    defs = [h for h in ctx.hits if _is_def_target(h[3])]
    refs = [h for h in ctx.hits if not _is_def_target(h[3])]
    bdefs = [h[3][1] for h in defs if h[3][0] == 'binding']
    if any(b.kind in ('def', 'class') for b in bdefs):
        raise SithError('cannot inline a function/class definition')
    for b in bdefs:
        if b.kind in ('import', 'from'):
            try:
                tk = ctx.rf.import_keys(b, frozenset())
            except RecursionError:
                tk = set()
            if any(k[0] == 'm' for k in tk):
                raise SithError('cannot inline a module')
    if not defs:
        raise SithError('no definition found to inline')
    if len(defs) > 1:
        raise SithError('cannot inline a name with multiple definitions')
    dinfo, dl, dc, dt = defs[0]
    if dt[0] != 'binding':
        raise SithError('cannot inline an attribute')
    b = dt[1]
    stmt = b.stmt
    ok = False
    if isinstance(stmt, ast.Assign) and len(stmt.targets) == 1 and \
            isinstance(stmt.targets[0], ast.Name) and stmt.targets[0].id == ident:
        ok = True
    elif isinstance(stmt, ast.AnnAssign) and stmt.value is not None and \
            isinstance(stmt.target, ast.Name) and stmt.target.id == ident:
        ok = True
    if not ok:
        raise SithError('cannot inline %r: it is not defined by a simple assignment' % ident)
    if not refs:
        raise SithError('name has no references to inline')
    changes = _Changes(ctx.root)
    dpath = os.path.realpath(dinfo.path)
    dtext = changes.text(dpath)
    dlines = dtext.split('\n')
    if dlines[dl - 1][dc:dc + len(ident)] != ident:
        raise SithError('source changed while refactoring')
    rhs = _expr_text(dtext, dlines, stmt.value)
    try:
        value = ast.parse('(\n' + rhs + '\n)', mode='eval').body
    except SyntaxError:
        raise SithError('cannot inline %r: invalid definition' % ident)
    sspan = _node_span(dlines, stmt)
    per_file = {}
    for finfo, ln, c, t in refs:
        p = os.path.realpath(finfo.path)
        if t[0] == 'name' and isinstance(t[1].ctx, ast.Load):
            span = ((ln, c), (ln, c + len(ident)))
        elif t[0] == 'attr' and isinstance(t[1].ctx, ast.Load):
            span = _node_span(finfo.lines, t[1])
        else:
            raise SithError('cannot inline %r: it is reassigned, deleted or declared global'
                            % ident)
        if p == dpath and sspan[0] <= span[0] and span[1] <= sspan[1]:
            raise SithError('cannot inline a recursive definition')
        per_file.setdefault(p, []).append(span)
    if dpath not in per_file:
        per_file[dpath] = []
    for p, spans in per_file.items():
        text = changes.text(p)
        lines = text.split('\n')
        starts = _line_starts(text)
        tree = _try_strict(text)
        edits = []
        for span in spans:
            (l1, c1), (l2, c2) = span
            if l1 > len(lines) or l2 > len(lines):
                continue
            s = starts[l1 - 1] + c1
            e = starts[l2 - 1] + c2
            r = rhs
            if _needs_parens(text, tree, span, rhs, value):
                r = '(' + rhs + ')'
            edits.append((s, e, r))
        if p == dpath:
            dtree = tree if tree is not None else dinfo.tree
            dstmt = stmt
            if tree is not None:
                dstmt = None
                for n in ast.walk(tree):
                    if isinstance(n, (ast.Assign, ast.AnnAssign)) and \
                            _node_span(lines, n) == sspan:
                        dstmt = n
                        break
                if dstmt is None:
                    dstmt, dtree = stmt, dinfo.tree
            edits.append(_removal_edit(text, lines, dtree, dstmt))
        changes.set(p, _apply_edits(text, edits))
    return changes


# ----- selections -----

def _parse_until(s):
    m = re.match(r'^\s*(-?\d+)\s*[:,]\s*(-?\d+)\s*$', s or '')
    if not m:
        raise SithError('invalid --until value %r (expected <line>:<col>)' % s)
    return int(m.group(1)), int(m.group(2))


def _comment_cols(text):
    """{line: column of its comment} and the set of lines continuing a token."""
    import tokenize
    comments = {}
    cont = set()
    try:
        for tok in tokenize.generate_tokens(io.StringIO(text).readline):
            if tok.type == tokenize.COMMENT:
                comments[tok.start[0]] = tok.start[1]
            elif tok.start[0] < tok.end[0] and tok.type not in (tokenize.NL, tokenize.NEWLINE):
                cont.update(range(tok.start[0] + 1, tok.end[0] + 1))
    except (tokenize.TokenError, SyntaxError, IndentationError):
        pass
    return comments, cont


def _code_range(lines, comments, ln):
    """(first, end) columns of the code on line ``ln`` or None if it has none."""
    t = lines[ln - 1]
    if ln in comments:
        t = t[:comments[ln]]
    t = t.rstrip()
    first = len(t) - len(t.lstrip())
    if first >= len(t):
        return None
    return first, len(t)


def _norm_start(lines, comments, pos):
    ln, c = pos
    while ln <= len(lines):
        r = _code_range(lines, comments, ln)
        if r is not None:
            if c <= r[0]:
                return (ln, r[0])
            if c < r[1]:
                return (ln, c)
        ln += 1
        c = 0
    return (len(lines), len(lines[-1]))


def _norm_end(lines, comments, pos):
    ln, c = pos
    while ln >= 1:
        r = _code_range(lines, comments, ln)
        if r is not None:
            if c >= r[1]:
                return (ln, r[1])
            if c > r[0]:
                return (ln, c)
        ln -= 1
        c = 1 << 30
    return (1, 0)


def _sel_positions(lines, line, col, until):
    _check_pos(lines, line, col)
    ul, uc = until
    if ul > len(lines):
        ul, uc = len(lines), len(lines[-1])
    if ul < 1 or uc < 0:
        raise SithError('--until position out of range')
    uc = min(uc, len(lines[ul - 1]))
    if (ul, uc) < (line, col):
        raise SithError('selection end is before its start')
    return (line, col), (ul, uc)


# ----- extract variable -----

def _parents(tree):
    par = {}
    for n in ast.walk(tree):
        for ch in ast.iter_child_nodes(n):
            par[id(ch)] = n
    return par


def _comp_or_lambda_locals(node, par):
    """Names bound by the lambdas/comprehensions enclosing ``node``."""
    out = set()
    child, n = node, par.get(id(node))
    while n is not None and not isinstance(n, ast.stmt):
        if isinstance(n, ast.comprehension) and child is n.iter:
            comp = par.get(id(n))
            if comp is not None and comp.generators[0] is n:
                # the first iterable is evaluated in the enclosing scope
                child, n = comp, par.get(id(comp))
                continue
        if isinstance(n, ast.Lambda) and child is n.body:
            out.update(a.arg for a in _all_args(n.args))
        elif isinstance(n, (ast.ListComp, ast.SetComp, ast.GeneratorExp, ast.DictComp)):
            for g in n.generators:
                out.update(x.id for x in ast.walk(g.target) if isinstance(x, ast.Name))
        child, n = n, par.get(id(n))
    return out


_NOT_EXTRACTABLE = (ast.Starred, ast.Slice, ast.FormattedValue)


def extract_variable(path, line, col, until, name, project=None):
    _check_ident(name)
    text = read_source(path)
    lines = text.split('\n')
    start, end = _sel_positions(lines, line, col, until)
    tree = _strict_parse(text)
    comments, _ = _comment_cols(text)
    start = _norm_start(lines, comments, start)
    end = _norm_end(lines, comments, end)
    if end <= start:
        raise SithError('selection is not a complete expression')
    starts = _line_starts(text)
    so = starts[start[0] - 1] + start[1]
    eo = starts[end[0] - 1] + end[1]
    par = _parents(tree)
    node = None
    s, e = so, eo
    while node is None:
        for n in ast.walk(tree):
            if not isinstance(n, ast.expr) or isinstance(n, _NOT_EXTRACTABLE):
                continue
            (a, b), (c, d) = _node_span(lines, n)
            if starts[a - 1] + b == s and starts[c - 1] + d == e:
                node = n
                break
        if node is not None:
            break
        sel = text[s:e]
        if sel.startswith('(') and sel.endswith(')') and e - s >= 2:
            try:
                ast.parse(sel, mode='eval')
            except SyntaxError:
                break
            s += 1
            e -= 1
            while s < e and text[s] in ' \t\n\\':
                s += 1
            while e > s and text[e - 1] in ' \t\n\\':
                e -= 1
            continue
        break
    if node is None:
        raise SithError('selection is not a complete expression')
    p = par.get(id(node))
    if isinstance(getattr(node, 'ctx', None), (ast.Store, ast.Del)) or \
            isinstance(p, ast.JoinedStr):
        raise SithError('selection is not a complete expression')
    if isinstance(p, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and \
            node in getattr(p, 'type_params', ()):
        raise SithError('selection is not a complete expression')
    stmt = p
    while stmt is not None and not isinstance(stmt, ast.stmt):
        stmt = par.get(id(stmt))
    if stmt is None:
        raise SithError('selection is not a complete expression')
    loc = _comp_or_lambda_locals(node, par)
    used = set(x.id for x in ast.walk(node) if isinstance(x, ast.Name))
    if loc & used:
        raise SithError('cannot extract an expression using lambda or comprehension variables')
    # an ``elif`` cannot be preceded by a statement: go up to the full ``if``
    while isinstance(stmt, ast.If):
        pp = par.get(id(stmt))
        if isinstance(pp, ast.If) and len(pp.orelse) == 1 and pp.orelse[0] is stmt and \
                lines[stmt.lineno - 1].lstrip().startswith('elif'):
            stmt = pp
        else:
            break
    sline = min([stmt.lineno] + [d.lineno for d in getattr(stmt, 'decorator_list', ())])
    indent = _indent_of(lines[sline - 1])
    sel = text[so:eo]
    rhs = sel
    if _try_strict(name + ' = ' + rhs) is None:
        rhs = '(' + sel + ')'
    new = _apply_edits(text, [(so, eo, name),
                              (starts[sline - 1], starts[sline - 1],
                               indent + name + ' = ' + rhs + '\n')])
    changes = _Changes(project_root(path, project))
    changes.set(path, new)
    return changes


# ----- extract function -----

class _Flow:
    """Evaluation-order walk recording reads that happen before assignment."""

    def __init__(self):
        self.reads = {}
        self.writes = {}
        self.returns = []
        self.yields = False
        self.awaits = False
        self.escapes = False
        self.decls = False
        self.loop = 0

    @staticmethod
    def pos(n):
        return (n.lineno, n.col_offset)

    def read(self, name, n, A):
        if name not in A and name not in self.reads:
            self.reads[name] = self.pos(n)

    def write(self, name, n, A):
        A.add(name)
        if name not in self.writes:
            self.writes[name] = self.pos(n)

    def stmts(self, body, A):
        for s in body:
            self.stmt(s, A)

    def nested(self, node, A):
        for name, n in _free_loads(node):
            self.read(name, n, A)

    def args(self, args, A):
        for d in list(args.defaults) + [d for d in args.kw_defaults if d is not None]:
            self.expr(d, A)
        for a in _all_args(args):
            if a.annotation is not None:
                self.expr(a.annotation, A)

    def stmt(self, s, A):
        t = type(s)
        if t in (ast.FunctionDef, ast.AsyncFunctionDef):
            for d in s.decorator_list:
                self.expr(d, A)
            self.args(s.args, A)
            if s.returns is not None:
                self.expr(s.returns, A)
            self.nested(s, A)
            self.write(s.name, s, A)
        elif t is ast.ClassDef:
            for d in s.decorator_list:
                self.expr(d, A)
            for x in s.bases:
                self.expr(x, A)
            for k in s.keywords:
                self.expr(k.value, A)
            self.nested(s, A)
            self.write(s.name, s, A)
        elif t is ast.Return:
            if s.value is not None:
                self.expr(s.value, A)
            self.returns.append(s)
        elif t is ast.Delete:
            for x in s.targets:
                self.expr(x, A)
        elif t is ast.Assign:
            self.expr(s.value, A)
            for x in s.targets:
                self.target(x, A)
        elif t is ast.AugAssign:
            if isinstance(s.target, ast.Name):
                self.read(s.target.id, s.target, A)
            else:
                self.expr(s.target, A)
            self.expr(s.value, A)
            if isinstance(s.target, ast.Name):
                self.write(s.target.id, s.target, A)
        elif t is ast.AnnAssign:
            if s.value is not None:
                self.expr(s.value, A)
                self.target(s.target, A)
        elif t in (ast.For, ast.AsyncFor):
            if t is ast.AsyncFor:
                self.awaits = True
            self.expr(s.iter, A)
            A2 = set(A)
            self.target(s.target, A2)
            self.loop += 1
            self.stmts(s.body, A2)
            self.loop -= 1
            self.stmts(s.orelse, set(A))
        elif t is ast.While:
            self.expr(s.test, A)
            self.loop += 1
            self.stmts(s.body, set(A))
            self.loop -= 1
            self.stmts(s.orelse, set(A))
        elif t is ast.If:
            self.expr(s.test, A)
            A1, A2 = set(A), set(A)
            self.stmts(s.body, A1)
            self.stmts(s.orelse, A2)
            A |= A1 & A2
        elif t in (ast.With, ast.AsyncWith):
            if t is ast.AsyncWith:
                self.awaits = True
            for it in s.items:
                self.expr(it.context_expr, A)
                if it.optional_vars is not None:
                    self.target(it.optional_vars, A)
            self.stmts(s.body, A)
        elif t.__name__ in ('Try', 'TryStar'):
            A1 = set(A)
            self.stmts(s.body, A1)
            self.stmts(s.orelse, A1)
            outs = [A1]
            for h in s.handlers:
                Ah = set(A)
                if h.type is not None:
                    self.expr(h.type, Ah)
                if h.name:
                    self.write(h.name, h, Ah)
                self.stmts(h.body, Ah)
                outs.append(Ah)
            common = set.intersection(*outs)
            self.stmts(s.finalbody, A)
            A |= common
        elif t is ast.Raise:
            for x in (s.exc, s.cause):
                if x is not None:
                    self.expr(x, A)
        elif t is ast.Assert:
            self.expr(s.test, A)
            if s.msg is not None:
                self.expr(s.msg, A)
        elif t in (ast.Import, ast.ImportFrom):
            for a in s.names:
                if a.name != '*':
                    self.write(a.asname or a.name.split('.')[0], s, A)
        elif t in (ast.Global, ast.Nonlocal):
            self.decls = True
        elif t is ast.Expr:
            self.expr(s.value, A)
        elif t in (ast.Break, ast.Continue):
            if not self.loop:
                self.escapes = True
        elif t is ast.Match:
            self.expr(s.subject, A)
            for case in s.cases:
                Ac = set(A)
                self.pattern(case.pattern, Ac)
                if case.guard is not None:
                    self.expr(case.guard, Ac)
                self.stmts(case.body, Ac)
        elif t.__name__ == 'TypeAlias':
            self.nested(s, A)
            self.write(s.name.id, s.name, A)

    def pattern(self, p, A):
        for n in ast.walk(p):
            if isinstance(n, (ast.MatchAs, ast.MatchStar)) and n.name:
                self.write(n.name, n, A)
            elif isinstance(n, ast.MatchMapping) and n.rest:
                self.write(n.rest, n, A)
            elif isinstance(n, ast.MatchValue):
                self.expr(n.value, A)
            elif isinstance(n, ast.MatchMapping):
                for k in n.keys:
                    self.expr(k, A)
            elif isinstance(n, ast.MatchClass):
                self.expr(n.cls, A)

    def target(self, t, A):
        if isinstance(t, ast.Name):
            self.write(t.id, t, A)
        elif isinstance(t, (ast.Tuple, ast.List)):
            for x in t.elts:
                self.target(x, A)
        elif isinstance(t, ast.Starred):
            self.target(t.value, A)
        else:
            self.expr(t, A)

    def expr(self, e, A):
        t = type(e)
        if t is ast.Name:
            if isinstance(e.ctx, ast.Store):
                self.write(e.id, e, A)
            else:
                self.read(e.id, e, A)
        elif t is ast.NamedExpr:
            self.expr(e.value, A)
            self.write(e.target.id, e.target, A)
        elif t is ast.Lambda:
            self.args(e.args, A)
            self.nested(e, A)
        elif t in (ast.ListComp, ast.SetComp, ast.GeneratorExp, ast.DictComp):
            gens = e.generators
            self.expr(gens[0].iter, A)
            C = set(A)
            for i, g in enumerate(gens):
                if i:
                    self.expr(g.iter, C)
                for x in ast.walk(g.target):
                    if isinstance(x, ast.Name):
                        C.add(x.id)
                for c in g.ifs:
                    self.expr(c, C)
            if t is ast.DictComp:
                self.expr(e.key, C)
                self.expr(e.value, C)
            else:
                self.expr(e.elt, C)
        elif t is ast.Await:
            self.awaits = True
            self.expr(e.value, A)
        elif t in (ast.Yield, ast.YieldFrom):
            self.yields = True
            if e.value is not None:
                self.expr(e.value, A)
        else:
            for ch in ast.iter_child_nodes(e):
                if isinstance(ch, ast.expr):
                    self.expr(ch, A)
                elif isinstance(ch, ast.keyword):
                    self.expr(ch.value, A)


def _free_loads(node):
    """[(name, node)] of names a nested scope reads from its enclosing scopes."""
    bound = set()
    inner = []
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
        bound.update(a.arg for a in _all_args(node.args))
    if isinstance(node, ast.Lambda):
        inner = [node.body]
    elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
        inner = list(node.body)
    elif type(node).__name__ == 'TypeAlias':
        inner = [node.value]
    loads = []
    for root in inner:
        for n in ast.walk(root):
            if isinstance(n, ast.Name):
                if isinstance(n.ctx, ast.Load):
                    loads.append(n)
                else:
                    bound.add(n.id)
            elif isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                bound.add(n.name)
                if not isinstance(n, ast.ClassDef):
                    bound.update(a.arg for a in _all_args(n.args))
            elif isinstance(n, ast.Lambda):
                bound.update(a.arg for a in _all_args(n.args))
            elif isinstance(n, (ast.Import, ast.ImportFrom)):
                bound.update(a.asname or a.name.split('.')[0] for a in n.names)
            elif isinstance(n, ast.ExceptHandler) and n.name:
                bound.add(n.name)
            elif isinstance(n, (ast.MatchAs, ast.MatchStar)) and n.name:
                bound.add(n.name)
            elif isinstance(n, ast.MatchMapping) and n.rest:
                bound.add(n.rest)
    return [(n.id, n) for n in loads if n.id not in bound]


def _scope_bindings(scope_node):
    """[(name, line)] of the names bound directly in a scope."""
    out = []
    if isinstance(scope_node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
        for a in _all_args(scope_node.args):
            out.append((a.arg, 0))
    body = scope_node.body if isinstance(scope_node.body, list) else [scope_node.body]

    def visit(n):
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            out.append((n.name, n.lineno))
            return
        if isinstance(n, ast.Lambda):
            return
        if isinstance(n, (ast.ListComp, ast.SetComp, ast.GeneratorExp, ast.DictComp)):
            for x in ast.walk(n):
                if isinstance(x, ast.NamedExpr):
                    out.append((x.target.id, x.lineno))
            return
        if isinstance(n, ast.Name) and isinstance(n.ctx, (ast.Store, ast.Del)):
            out.append((n.id, n.lineno))
        elif isinstance(n, (ast.Import, ast.ImportFrom)):
            for a in n.names:
                if a.name != '*':
                    out.append((a.asname or a.name.split('.')[0], n.lineno))
        elif isinstance(n, ast.ExceptHandler) and n.name:
            out.append((n.name, n.lineno))
        elif isinstance(n, (ast.MatchAs, ast.MatchStar)) and n.name:
            out.append((n.name, n.lineno))
        elif isinstance(n, ast.MatchMapping) and n.rest:
            out.append((n.rest, n.lineno))
        for ch in ast.iter_child_nodes(n):
            visit(ch)

    for s in body:
        visit(s)
    return out


def _stmt_start(lines, s):
    decs = getattr(s, 'decorator_list', None)
    if decs:
        d = min(decs, key=lambda x: (x.lineno, x.col_offset))
        t = lines[d.lineno - 1]
        c = _char_col(lines, d.lineno, d.col_offset)
        at = t.rfind('@', 0, c)
        return (d.lineno, at if at >= 0 else c)
    return (s.lineno, _char_col(lines, s.lineno, s.col_offset))


def _stmt_end(lines, s):
    return (s.end_lineno, _char_col(lines, s.end_lineno, s.end_col_offset))


def _child_bodies(s):
    out = []
    for f in ('body', 'orelse', 'finalbody'):
        b = getattr(s, f, None)
        if isinstance(b, list) and b and isinstance(b[0], ast.stmt):
            out.append(b)
    for h in getattr(s, 'handlers', ()) or ():
        out.append(h.body)
    for c in getattr(s, 'cases', ()) or ():
        out.append(c.body)
    return out


_PARTIAL = 'selection must span one or more complete statements'


def _select_stmts(lines, comments, body, start, end, ancestors):
    over = [s for s in body if _stmt_start(lines, s) < end and _stmt_end(lines, s) > start]
    if not over:
        raise SithError(_PARTIAL)
    fs = _stmt_start(lines, over[0])
    le = _stmt_end(lines, over[-1])
    if start == fs and (end == le or (end[0] == le[0] and end[1] >= le[1] - 1)):
        before = lines[fs[0] - 1][:fs[1]]
        after = lines[le[0] - 1]
        if le[0] in comments:
            after = after[:comments[le[0]]]
        after = after[le[1]:].strip()
        if before.strip() or after not in ('', ';'):
            raise SithError(_PARTIAL)
        return over, ancestors
    if len(over) == 1 and start >= fs and end <= le:
        for b in _child_bodies(over[0]):
            if any(_stmt_start(lines, s) < end and _stmt_end(lines, s) > start for s in b):
                return _select_stmts(lines, comments, b, start, end, ancestors + [over[0]])
    raise SithError(_PARTIAL)


def _indent_unit(lines, cont):
    best = None
    for i, t in enumerate(lines):
        if i + 1 in cont or not t.strip() or t.lstrip().startswith('#'):
            continue
        ind = _indent_of(t)
        if ind.startswith('\t'):
            return '\t'
        if ind and (best is None or len(ind) < len(best)):
            best = ind
    return best or '    '


def _loads_after(scope_node, lo, hi, loop):
    """Names read in ``scope_node`` after line ``hi`` (or anywhere in ``loop``)."""
    out = set()
    for n in ast.walk(scope_node):
        if isinstance(n, ast.Name) and getattr(n, 'lineno', None) is not None:
            reading = isinstance(n.ctx, (ast.Load, ast.Del))
            if not reading:
                continue
            if n.lineno > hi:
                out.add(n.id)
            elif loop is not None and not (lo <= n.lineno <= hi) and \
                    loop.lineno <= n.lineno <= loop.end_lineno:
                out.add(n.id)
        elif isinstance(n, ast.AugAssign) and isinstance(n.target, ast.Name):
            if n.lineno > hi or (loop is not None and not (lo <= n.lineno <= hi) and
                                 loop.lineno <= n.lineno <= loop.end_lineno):
                out.add(n.target.id)
    return out


def extract_function(path, line, col, until, name, project=None):
    _check_ident(name)
    text = read_source(path)
    lines = text.split('\n')
    start, end = _sel_positions(lines, line, col, until)
    tree = _strict_parse(text)
    comments, cont = _comment_cols(text)
    start = _norm_start(lines, comments, start)
    end = _norm_end(lines, comments, end)
    if end <= start:
        raise SithError(_PARTIAL)
    stmts, ancestors = _select_stmts(lines, comments, tree.body, start, end, [])
    first = _stmt_start(lines, stmts[0])[0]
    last = stmts[-1].end_lineno

    scope = tree
    loop = None
    for a in reversed(ancestors):
        if isinstance(a, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            scope = a
            break
        if loop is None and isinstance(a, (ast.For, ast.AsyncFor, ast.While)):
            loop = a
    outer = [a for a in ancestors if isinstance(a, (ast.FunctionDef, ast.AsyncFunctionDef))
             and a is not scope]

    flow = _Flow()
    flow.stmts(stmts, set())
    if flow.yields:
        raise SithError('cannot extract code containing yield')
    if flow.decls:
        raise SithError('cannot extract code containing global/nonlocal statements')
    if flow.escapes:
        raise SithError('cannot extract break/continue outside of their loop')
    ends_return = isinstance(stmts[-1], ast.Return)
    if flow.returns and not ends_return:
        raise SithError('can only extract a return statement at the end of the selection')

    # parameters
    known = set()
    for n, ln in _scope_bindings(scope):
        if not (first <= ln <= last):
            known.add(n)
    for f in outer:
        known.update(n for n, _ in _scope_bindings(f))
    params = sorted((p for p in flow.reads if p in known), key=lambda p: flow.reads[p])

    # return values
    outputs = []
    if not ends_return:
        used = _loads_after(scope, first, last, loop)
        outputs = sorted((w for w in flow.writes if w in used), key=lambda w: flow.writes[w])

    # method handling
    self_name = None
    decorator = None
    callee = name
    sp = None
    if scope is not tree:
        sp = ancestors[ancestors.index(scope) - 1] if ancestors.index(scope) > 0 else tree
    if isinstance(scope, (ast.FunctionDef, ast.AsyncFunctionDef)) and isinstance(sp, ast.ClassDef):
        decs = _decorator_names(scope)
        pos_args = list(getattr(scope.args, 'posonlyargs', [])) + list(scope.args.args)
        if 'staticmethod' in decs:
            decorator = '@staticmethod'
            callee = sp.name + '.' + name
        elif pos_args:
            self_name = pos_args[0].arg
            if 'classmethod' in decs:
                decorator = '@classmethod'
            params = [p for p in params if p != self_name]
            callee = self_name + '.' + name

    unit = _indent_unit(lines, cont)
    sel_indent = _indent_of(lines[first - 1])
    if scope is tree:
        ins = first
        base = sel_indent
    else:
        ins = _stmt_start(lines, scope)[0]
        base = _indent_of(lines[ins - 1])
    inner = base + unit
    body = []
    for ln in range(first, last + 1):
        t = lines[ln - 1]
        if ln in cont:
            body.append(t)
        elif not t.strip():
            body.append('')
        elif t.startswith(sel_indent):
            body.append(inner + t[len(sel_indent):])
        else:
            body.append(inner + t.lstrip())
    if outputs:
        body.append(inner + 'return ' + ', '.join(outputs))
    head = []
    if decorator:
        head.append(base + decorator)
    head.append('%s%sdef %s(%s):' % (base, 'async ' if flow.awaits else '', name,
                                     ', '.join(([self_name] if self_name else []) + params)))
    func = head + body + [''] * (2 if not base else 1)

    call = '%s(%s)' % (callee, ', '.join(params))
    if flow.awaits:
        call = 'await ' + call
    if ends_return:
        call = 'return ' + call
    elif outputs:
        call = ', '.join(outputs) + ' = ' + call
    new_lines = lines[:ins - 1] + func + lines[ins - 1:first - 1] + [sel_indent + call] + \
        lines[last:]
    changes = _Changes(project_root(path, project))
    changes.set(path, '\n'.join(new_lines))
    return changes


# ----- syntax errors -----

def _compile_error(src):
    try:
        with warnings.catch_warnings():
            warnings.simplefilter('ignore')
            compile(src, '<sith>', 'exec', dont_inherit=True)
    except SyntaxError as e:
        return e
    except (ValueError, RecursionError, MemoryError, OverflowError) as e:
        err = SyntaxError(str(e))
        err.lineno, err.offset = 1, 1
        return err
    return None


def _error_dict(lines, e):
    ln = e.lineno or 1
    ln = max(1, min(ln, len(lines)))
    col = (e.offset or 1) - 1
    col = max(0, min(col, len(lines[ln - 1])))
    el = getattr(e, 'end_lineno', None)
    ec = getattr(e, 'end_offset', None)
    if el is None or ec is None or el < 1 or ec < 1 or (el, ec - 1) < (ln, col):
        el, ec = ln, col
    else:
        el = min(el, len(lines))
        ec = max(0, min(ec - 1, len(lines[el - 1])))
        if (el, ec) < (ln, col):
            el, ec = ln, col
    if (el, ec) == (ln, col) and col < len(lines[ln - 1]):
        ec = col + 1
    return {'line': ln, 'column': col, 'until_line': el, 'until_column': ec,
            'message': e.msg or 'invalid syntax'}


def syntax_errors(path):
    text = read_source(path)
    lines = text.split('\n')
    work = text.replace('\0', ' ').split('\n')
    out = []
    repaired = set()
    seen = set()
    last = 0
    for _ in range(2 * len(work) + 20):
        e = _compile_error('\n'.join(work))
        if e is None:
            break
        ln = max(1, min(e.lineno or len(work), len(work)))
        msg = e.msg or ''
        spurious = isinstance(e, IndentationError) and 'unexpected indent' in msg and \
            any(k in repaired for k in range(max(1, ln - 3), ln))
        key = (ln, msg)
        if key in seen:
            break
        seen.add(key)
        if not out or (ln > last and not spurious):
            out.append(_error_dict(lines, e))
            last = ln
        # repair the offending line(s) and look for further errors
        if 'indented block' in msg:
            m = _OPENER_RE.search(msg)
            if m and 1 <= int(m.group(1)) <= len(work):
                k = int(m.group(1))
                work[k - 1] = _code_part(work[k - 1]).rstrip() + ' pass'
                repaired.add(k)
                continue
        if isinstance(e, IndentationError) and 'unexpected indent' in msg:
            width = len(_indent_of(work[ln - 1]).expandtabs(8))
            k = ln
            while k <= len(work):
                t = work[k - 1]
                if t.strip() and len(_indent_of(t).expandtabs(8)) < width:
                    break
                work[k - 1] = ''
                repaired.add(k)
                k += 1
            continue
        if 'never closed' in msg:
            # drop the whole unterminated bracket group
            k = ln
            ind = _indent_of(work[ln - 1])
            work[ln - 1] = ind + 'pass'
            repaired.add(ln)
            k = ln + 1
            while k <= len(work) and work[k - 1].strip() and \
                    len(_indent_of(work[k - 1]).expandtabs(8)) > len(ind.expandtabs(8)):
                work[k - 1] = ''
                repaired.add(k)
                k += 1
            continue
        line = work[ln - 1]
        if not line.strip():
            k = ln - 1
            while k >= 1 and not work[k - 1].strip():
                k -= 1
            if k < 1:
                break
            ln = k
            line = work[ln - 1]
        ind = _indent_of(line)
        code = _code_part(line).strip()
        if code.endswith(':') or _next_indent_deeper(work, ln):
            repl = ind + 'if True:'
        else:
            repl = ind + 'pass'
        if line == repl or line.strip() in ('pass', 'if True:'):
            repl = ''
        work[ln - 1] = repl
        repaired.add(ln)
    out.sort(key=lambda d: (d['line'], d['column']))
    return out


def _parse_int(s, what):
    try:
        return int(s)
    except ValueError:
        raise SithError('invalid %s: %r' % (what, s))


USAGE = ('usage: sith.py complete <file> <line> <col> [--fuzzy] [--project <dir>]\n'
         '       sith.py infer <file> <line> <col> [--project <dir>]\n'
         '       sith.py goto <file> <line> <col> [--follow-imports] [--project <dir>]\n'
         '       sith.py signatures <file> <line> <col> [--project <dir>]\n'
         '       sith.py references <file> <line> <col> [--scope file|project] '
         '[--project <dir>]\n'
         '       sith.py search <query> [--project <dir>]\n'
         '       sith.py names <file> [--all-scopes] [--project <dir>]\n'
         '       sith.py rename <file> <line> <col> --new-name <name> [--diff] '
         '[--project <dir>]\n'
         '       sith.py inline <file> <line> <col> [--diff] [--project <dir>]\n'
         '       sith.py extract-variable <file> <line> <col> --until <line>:<col> '
         '--name <name> [--diff] [--project <dir>]\n'
         '       sith.py extract-function <file> <line> <col> --until <line>:<col> '
         '--name <name> [--diff] [--project <dir>]\n'
         '       sith.py errors <file>\n')

_FLAGS = ('--fuzzy', '--follow-imports', '--all-scopes', '--diff')
_OPTIONS = ('--project', '--scope', '--new-name', '--until', '--name')
_ARITY = {'complete': 4, 'infer': 4, 'goto': 4, 'signatures': 4, 'references': 4,
          'search': 2, 'names': 2, 'rename': 4, 'inline': 4, 'extract-variable': 4,
          'extract-function': 4, 'errors': 2}
_REQUIRED = {'rename': ('--new-name',), 'extract-variable': ('--until', '--name'),
             'extract-function': ('--until', '--name')}


def main(argv):
    opts = {}
    rest = []
    i = 0
    while i < len(argv):
        a = argv[i]
        if a in _OPTIONS and i + 1 < len(argv):
            opts[a] = argv[i + 1]
            i += 2
            continue
        k, eq, v = a.partition('=')
        if eq and k in _OPTIONS:
            opts[k] = v
        else:
            rest.append(a)
        i += 1
    project = opts.get('--project')
    scope = opts.get('--scope', 'file')
    flags = set(a for a in rest if a in _FLAGS)
    args = [a for a in rest if a not in _FLAGS]
    if not args or args[0] not in _ARITY or len(args) != _ARITY[args[0]] or \
            scope not in ('file', 'project') or \
            any(o not in opts for o in _REQUIRED.get(args[0], ())):
        sys.stderr.write(USAGE)
        return 1
    cmd = args[0]
    diff = '--diff' in flags
    try:
        sys.setrecursionlimit(max(sys.getrecursionlimit(), 10000))
        if cmd == 'search':
            res = search(args[1], project)
            out = {'results': res, 'definitions': res, 'names': res}
        elif cmd == 'names':
            res = names(args[1], '--all-scopes' in flags, project)
            out = {'names': res, 'definitions': res}
        elif cmd == 'errors':
            out = {'errors': syntax_errors(args[1])}
        else:
            line = _parse_int(args[2], 'line')
            col = _parse_int(args[3], 'column')
            if cmd == 'complete':
                out = {'completions': complete(args[1], line, col, '--fuzzy' in flags, project)}
            elif cmd == 'signatures':
                out = {'signatures': signatures(args[1], line, col, project)}
            elif cmd == 'references':
                out = {'references': references(args[1], line, col, scope, project)}
            elif cmd == 'rename':
                out = rename(args[1], line, col, opts['--new-name'], project)
            elif cmd == 'inline':
                out = inline(args[1], line, col, project)
            elif cmd == 'extract-variable':
                out = extract_variable(args[1], line, col, _parse_until(opts['--until']),
                                       opts['--name'], project)
            elif cmd == 'extract-function':
                out = extract_function(args[1], line, col, _parse_until(opts['--until']),
                                       opts['--name'], project)
            else:
                out = {'definitions': navigate(args[1], line, col, cmd, project,
                                               '--follow-imports' in flags)}
        if isinstance(out, _Changes):
            text = out.output(diff)
        else:
            text = json.dumps(out, separators=(',', ':')) + '\n'
    except SithError as e:
        sys.stderr.write('error: %s\n' % e)
        return 1
    sys.stdout.write(text)
    sys.stdout.flush()
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
