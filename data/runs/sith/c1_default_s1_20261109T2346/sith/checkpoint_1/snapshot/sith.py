#!/usr/bin/env python3
"""sith - a small static Python code intelligence tool.

Usage:
    python sith.py complete <file> <line> <col> [--fuzzy]
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


def parse_source(text, cursor=None):
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
            tree = _repair_parse(work, L)
            if tree is not None:
                return tree
    work = list(lines)
    tree = _repair_parse(work, None)
    if tree is None:
        tree = ast.parse('')
    return tree


# ---------------------------------------------------------------------------
# Scopes
# ---------------------------------------------------------------------------

class Binding:
    __slots__ = ('name', 'line', 'kind', 'node', 'extra', 'scope')

    def __init__(self, name, line, kind, node=None, extra=None):
        self.name = name
        self.line = line
        self.kind = kind
        self.node = node
        self.extra = extra
        self.scope = None


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
        self._bases = None
        if parent is not None:
            parent.children.append(self)

    def add(self, b):
        b.scope = self
        self.bindings.setdefault(b.name, []).append(b)


class ModuleInfo:
    def __init__(self, path, tree, name):
        self.path = path
        self.dir = os.path.dirname(os.path.abspath(path))
        self.name = name
        self.is_package = os.path.basename(path) == '__init__.py'
        self.cursor_scope = None
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

    def mark(self, ident, sc):
        if ident and MARK in ident:
            self.m.cursor_scope = sc

    def stmts(self, body, sc):
        for s in body:
            try:
                self.stmt(s, sc)
            except RecursionError:
                pass

    def stmt(self, s, sc):
        t = type(s)
        if t in (ast.FunctionDef, ast.AsyncFunctionDef):
            self.mark(s.name, sc)
            for d in s.decorator_list:
                self.expr(d, sc)
            self.args_outer(s.args, sc)
            if s.returns is not None:
                self.expr(s.returns, sc)
            fs = Scope('function', s, sc, self.m)
            sc.add(Binding(s.name, s.lineno, 'def', s, fs))
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
            sc.add(Binding(s.name, s.lineno, 'class', s, cs))
            self.stmts(s.body, cs)
        elif t is ast.Import:
            for a in s.names:
                self.mark(a.name, sc)
                self.mark(a.asname, sc)
                name = a.asname or a.name.split('.')[0]
                sc.add(Binding(name, s.lineno, 'import', s, (a.name, a.asname)))
        elif t is ast.ImportFrom:
            self.mark(s.module, sc)
            for a in s.names:
                self.mark(a.name, sc)
                self.mark(a.asname, sc)
                if a.name == '*':
                    sc.stars.append((s.lineno, s.module or '', s.level or 0))
                else:
                    name = a.asname or a.name
                    sc.add(Binding(name, s.lineno, 'from', s,
                                   (s.module or '', s.level or 0, a.name)))
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
                sc.add(Binding(s.target.id, s.target.lineno, 'ann', s, (s.annotation, s.value)))
            else:
                self.expr(s.target, sc)
        elif t is ast.AugAssign:
            self.expr(s.target, sc)
            self.expr(s.value, sc)
        elif t in (ast.For, ast.AsyncFor):
            self.expr(s.iter, sc)
            self.target(s.target, sc, ('stmt',))
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
                    self.target(item.optional_vars, sc, ('stmt',))
            self.stmts(s.body, sc)
        elif t is ast.Try or t.__name__ == 'TryStar':
            self.stmts(s.body, sc)
            for h in s.handlers:
                if h.type is not None:
                    self.expr(h.type, sc)
                if h.name:
                    self.mark(h.name, sc)
                    sc.add(Binding(h.name, h.lineno, 'except', h, h.type))
                self.stmts(h.body, sc)
            self.stmts(s.orelse, sc)
            self.stmts(s.finalbody, sc)
        elif t.__name__ == 'Match':
            self.expr(s.subject, sc)
            for case in s.cases:
                self.pattern(case.pattern, sc)
                if case.guard is not None:
                    self.expr(case.guard, sc)
                self.stmts(case.body, sc)
        elif t.__name__ == 'TypeAlias':
            if isinstance(s.name, ast.Name):
                sc.add(Binding(s.name.id, s.lineno, 'stmt', s))
        else:
            for c in ast.iter_child_nodes(s):
                if isinstance(c, ast.expr):
                    self.expr(c, sc)

    def pattern(self, p, sc):
        for n in ast.walk(p):
            name = None
            if type(n).__name__ in ('MatchAs', 'MatchStar'):
                name = n.name
            elif type(n).__name__ == 'MatchMapping':
                name = n.rest
            elif type(n).__name__ == 'MatchValue':
                self.expr(n.value, sc)
            if name:
                self.mark(name, sc)
                sc.add(Binding(name, n.lineno, 'stmt', n))

    def target(self, t, sc, how, path=()):
        if isinstance(t, ast.Name):
            self.mark(t.id, sc)
            if how[0] == 'assign':
                if path:
                    b = Binding(t.id, t.lineno, 'unpack', t, (how[1], path))
                else:
                    b = Binding(t.id, t.lineno, 'assign', t, how[1])
            else:
                b = Binding(t.id, t.lineno, 'stmt', t)
            sc.add(b)
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
            fs.add(Binding(a.arg, fnode.lineno, 'param', a, (fnode, idx, defmap.get(id(a)))))

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
            return
        if t is ast.Attribute:
            self.mark(e.attr, sc)
            self.expr(e.value, sc)
            return
        if t is ast.NamedExpr:
            self.expr(e.value, sc)
            if isinstance(e.target, ast.Name):
                self.mark(e.target.id, sc)
                self.nearest_non_comp(sc).add(
                    Binding(e.target.id, e.target.lineno, 'assign', e.target, e.value))
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
                self.target(g.target, cs, ('stmt',))
                for c in g.ifs:
                    self.expr(c, cs)
            if t is ast.DictComp:
                self.expr(e.key, cs)
                self.expr(e.value, cs)
            else:
                self.expr(e.elt, cs)
            return
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
    def __init__(self, cls):
        self.cls = cls


class SuperInst:
    def __init__(self, cls):
        self.cls = cls


class StFunc:
    def __init__(self, node, scope):
        self.node = node
        self.scope = scope


def _sample_function():
    pass


_SAMPLES = {
    int: lambda: 0, float: lambda: 0.0, complex: lambda: 0j, str: lambda: '',
    bytes: lambda: b'', bytearray: bytearray, list: list, dict: dict, set: set,
    frozenset: frozenset, tuple: tuple, bool: lambda: False, type(None): lambda: None,
    object: object,
}
_ROUTINE_TYPES = (staticmethod, classmethod)


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


def instantiate(v):
    if isinstance(v, StClass):
        return StInst(v)
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


# ---------------------------------------------------------------------------
# Inference engine
# ---------------------------------------------------------------------------

class Engine:
    def __init__(self):
        self.static_cache = {}
        self.rt_cache = {}
        self.inferring = set()

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
        try:
            info = ModuleInfo(path, parse_source(text), name)
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

    # ----- lookup -----

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

    def lookup_value(self, name, sc, line, depth):
        for s, filt in self.chain(sc):
            for ent in self.scope_candidates(s, name, line, filt):
                if ent[0] == 'b' and id(ent[1]) in self.inferring:
                    continue
                return self.entry_value(ent, depth)
        if hasattr(builtins, name):
            return RtV(getattr(builtins, name))
        return None

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

    # ----- entries -----

    def entry_value(self, ent, depth=0):
        if ent[0] == 'b':
            return self.binding_value(ent[1], depth)
        return ent[1]()

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

    def binding_value(self, b, depth=0):
        if depth > MAX_DEPTH:
            return None
        key = id(b)
        if key in self.inferring:
            return None
        self.inferring.add(key)
        try:
            return self._binding_value(b, depth)
        except RecursionError:
            return None
        finally:
            self.inferring.discard(key)

    def _binding_value(self, b, depth):
        k = b.kind
        sc = b.scope
        if k == 'def':
            return StFunc(b.node, b.extra)
        if k == 'class':
            return class_value(b.extra)
        if k == 'import':
            full, asname = b.extra
            if asname:
                return self.resolve_module(full, sc.module.dir)
            top = full.split('.')[0]
            if '.' in full:
                self.resolve_module(full, sc.module.dir)
            return self.resolve_module(top, sc.module.dir)
        if k == 'from':
            mod, level, attr = b.extra
            mv = self.resolve_module(mod, sc.module.dir, level)
            v = self.get_attr(mv, attr, depth + 1)
            if v is None and not isinstance(mv, UnMod):
                if level == 0 and isinstance(mv, RtV):
                    m = self.rt_import(mod + '.' + attr)
                    if m is not None:
                        return RtV(m)
            return v
        if k == 'assign':
            return self.infer(b.extra, sc, b.line, depth + 1)
        if k == 'unpack':
            value, path = b.extra
            node = value
            for i in path:
                if isinstance(node, (ast.Tuple, ast.List)) and i < len(node.elts) \
                        and not any(isinstance(e, ast.Starred) for e in node.elts):
                    node = node.elts[i]
                else:
                    return None
            return self.infer(node, sc, b.line, depth + 1)
        if k == 'ann':
            ann, value = b.extra
            if value is not None:
                v = self.infer(value, sc, b.line, depth + 1)
                if v is not None:
                    return v
            return instantiate(self.infer(ann, sc, b.line, depth + 1))
        if k == 'param':
            return self.param_value(b, depth)
        if k == 'except':
            if b.extra is None:
                return None
            return instantiate(self.infer(b.extra, sc, b.line, depth + 1))
        return None

    def param_value(self, b, depth):
        a = b.node
        fnode, idx, default = b.extra
        fs = b.scope
        outer = fs.parent
        if a.annotation is not None:
            v = instantiate(self.infer(a.annotation, outer, fnode.lineno, depth + 1))
            if v is not None:
                return v
        if idx == 0 and isinstance(fnode, (ast.FunctionDef, ast.AsyncFunctionDef)) \
                and outer is not None and outer.kind == 'class':
            decos = set()
            for d in fnode.decorator_list:
                if isinstance(d, ast.Name):
                    decos.add(d.id)
                elif isinstance(d, ast.Attribute):
                    decos.add(d.attr)
            if 'staticmethod' in decos:
                pass
            elif 'classmethod' in decos or fnode.name in ('__new__', '__init_subclass__',
                                                          '__class_getitem__'):
                return class_value(outer)
            else:
                return StInst(class_value(outer))
        if default is not None:
            return self.infer(default, outer, fnode.lineno, depth + 1)
        return None

    # ----- expressions -----

    def infer(self, node, sc, line, depth=0):
        if node is None or depth > MAX_DEPTH:
            return None
        try:
            return self._infer(node, sc, line, depth)
        except RecursionError:
            return None

    def _infer(self, node, sc, line, depth):
        t = type(node)
        if t is ast.Constant:
            return RtV(node.value)
        if t is ast.JoinedStr:
            return RtV('')
        if t in (ast.List, ast.ListComp):
            return RtV([])
        if t is ast.Tuple:
            return RtV(())
        if t in (ast.Dict, ast.DictComp):
            return RtV({})
        if t in (ast.Set, ast.SetComp):
            return RtV(set())
        if t is ast.GeneratorExp:
            return RtV((x for x in ()))
        if t is ast.Lambda:
            return RtV(lambda: None)
        if t is ast.Name:
            return self.lookup_value(node.id, sc, line, depth + 1)
        if t is ast.Attribute:
            base = self.infer(node.value, sc, line, depth + 1)
            if base is None:
                return None
            return self.get_attr(base, node.attr, depth + 1)
        if t is ast.Call:
            if isinstance(node.func, ast.Name) and node.func.id == 'super' and not node.args:
                s = sc
                while s is not None and s.kind != 'function':
                    s = s.parent
                if s is not None and s.parent is not None and s.parent.kind == 'class':
                    sv = self.lookup_value('super', sc, line, depth + 1)
                    if isinstance(sv, RtV) and sv.obj is super:
                        return SuperInst(class_value(s.parent))
            f = self.infer(node.func, sc, line, depth + 1)
            return instantiate(f)
        if t is ast.NamedExpr:
            return self.infer(node.value, sc, line, depth + 1)
        if t is ast.Compare:
            return RtV(False)
        if t is ast.UnaryOp:
            if isinstance(node.op, ast.Not):
                return RtV(False)
            v = self.infer(node.operand, sc, line, depth + 1)
            s = self._sample(v)
            if s is _NOSAMPLE:
                return None
            try:
                ops = {ast.USub: lambda x: -x, ast.UAdd: lambda x: +x, ast.Invert: lambda x: ~x}
                return RtV(ops[type(node.op)](s))
            except Exception:
                return None
        if t is ast.BinOp:
            lv = self._sample(self.infer(node.left, sc, line, depth + 1))
            rv = self._sample(self.infer(node.right, sc, line, depth + 1))
            if lv is _NOSAMPLE or rv is _NOSAMPLE:
                return None
            return self._binop(node.op, lv, rv)
        if t is ast.BoolOp:
            vals = [self.infer(v, sc, line, depth + 1) for v in node.values]
            return self._common(vals)
        if t is ast.IfExp:
            return self._common([self.infer(node.body, sc, line, depth + 1),
                                 self.infer(node.orelse, sc, line, depth + 1)])
        return None

    def _common(self, vals):
        if not vals or any(v is None for v in vals):
            return None
        first = vals[0]
        k = self._type_key(first)
        if k is None:
            return None
        for v in vals[1:]:
            if self._type_key(v) != k:
                return None
        return first

    def _type_key(self, v):
        if isinstance(v, RtV):
            if kind_of(v) == 'instance':
                return ('rt', type(v.obj))
            return ('obj', id(v.obj))
        if isinstance(v, RtInst):
            return ('rt', v.cls)
        if isinstance(v, StInst):
            return ('st', id(v.cls))
        return None

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

    def get_attr(self, v, name, depth=0):
        if v is None or depth > MAX_DEPTH:
            return None
        if isinstance(v, RtV):
            try:
                with warnings.catch_warnings():
                    warnings.simplefilter('ignore')
                    return RtV(getattr(v.obj, name))
            except BaseException:
                if inspect.ismodule(v.obj):
                    m = self.rt_import(v.obj.__name__ + '.' + name)
                    if m is not None:
                        return RtV(m)
                return None
        if isinstance(v, RtInst):
            try:
                return RtV(getattr(v.cls, name))
            except BaseException:
                return None
        if isinstance(v, StMod):
            if v.info is not None:
                sc = v.info.scope
                cands = self.scope_candidates(sc, name, 10 ** 9, False)
                for ent in cands:
                    if ent[0] == 'b' and id(ent[1]) in self.inferring:
                        continue
                    return self.entry_value(ent, depth + 1)
            if v.pkgdir:
                found = self.find_local(name, v.pkgdir)
                if found:
                    return self.static_module(found, (v.name + '.' + name).strip('.'))
            return None
        if isinstance(v, (StClass, StInst, SuperInst)):
            ent = self.attributes(v).get(name)
            if ent is None:
                return None
            return self.entry_value(ent, depth + 1)
        if isinstance(v, StFunc):
            try:
                return RtV(getattr(_sample_function, name))
            except AttributeError:
                return None
        return None

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
                v = self.infer(bnode, sc.parent, sc.node.lineno)
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

    def self_attrs(self, cls):
        sc = cls.scope
        if sc._self_attrs is not None:
            return sc._self_attrs
        sc._self_attrs = {}
        res = {}
        lst = sc.bindings.get('__init__')
        if lst:
            b = max(lst, key=lambda x: x.line)
            if b.kind == 'def':
                fnode, fs = b.node, b.extra
                positional = list(getattr(fnode.args, 'posonlyargs', [])) + list(fnode.args.args)
                if positional:
                    selfname = positional[0].arg
                    for s in _iter_stmts(fnode.body):
                        if isinstance(s, ast.Assign):
                            for tgt in s.targets:
                                self._collect_self(tgt, selfname, s.value, (), fs, res)
                        elif isinstance(s, ast.AnnAssign):
                            tgt = s.target
                            if isinstance(tgt, ast.Attribute) and isinstance(tgt.value, ast.Name) \
                                    and tgt.value.id == selfname:
                                nb = Binding(tgt.attr, tgt.lineno, 'ann', tgt, (s.annotation, s.value))
                                nb.scope = fs
                                res.setdefault(tgt.attr, nb)
                        elif isinstance(s, ast.AugAssign):
                            tgt = s.target
                            if isinstance(tgt, ast.Attribute) and isinstance(tgt.value, ast.Name) \
                                    and tgt.value.id == selfname:
                                nb = Binding(tgt.attr, tgt.lineno, 'stmt', tgt)
                                nb.scope = fs
                                res.setdefault(tgt.attr, nb)
        sc._self_attrs = {n: ('b', b) for n, b in res.items() if MARK not in n}
        return sc._self_attrs

    def _collect_self(self, tgt, selfname, value, path, fs, res):
        if isinstance(tgt, ast.Attribute) and isinstance(tgt.value, ast.Name) \
                and tgt.value.id == selfname:
            if path:
                nb = Binding(tgt.attr, tgt.lineno, 'unpack', tgt, (value, path))
            else:
                nb = Binding(tgt.attr, tgt.lineno, 'assign', tgt, value)
            nb.scope = fs
            res.setdefault(tgt.attr, nb)
        elif isinstance(tgt, (ast.Tuple, ast.List)):
            for i, e in enumerate(tgt.elts):
                if not isinstance(e, ast.Starred):
                    self._collect_self(e, selfname, value, path + (i,), fs, res)

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
                    out[sub] = ('v', lambda s=sub: self.get_attr(v, s))
            return out
        if isinstance(v, StClass):
            return self.class_attrs(self.mro(v))
        if isinstance(v, StInst):
            classes = self.mro(v.cls)
            out = self.class_attrs(classes)
            for c in reversed(classes):
                out.update(self.self_attrs(c))
            return out
        if isinstance(v, SuperInst):
            classes = self.mro(v.cls)[1:]
            out = self.class_attrs(classes)
            for c in reversed(classes):
                out.update(self.self_attrs(c))
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


def complete(path, line, col, fuzzy=False):
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
    text = text.replace('\r\n', '\n').replace('\r', '\n')
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

    engine = Engine()
    tree = parse_source(text, (line, col))
    info = ModuleInfo(os.path.abspath(path), tree, '__main__')
    engine.static_cache[os.path.realpath(path)] = info
    sc = info.cursor_scope
    if sc is None:
        bcol = len(cl[:col].encode('utf-8'))
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
        v = engine.infer(node, sc, line)
        entries = engine.attributes(v)
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


def _parse_int(s, what):
    try:
        return int(s)
    except ValueError:
        raise SithError('invalid %s: %r' % (what, s))


def main(argv):
    args = [a for a in argv if a != '--fuzzy']
    fuzzy = len(args) != len(argv)
    if len(args) != 4 or args[0] != 'complete':
        sys.stderr.write('usage: sith.py complete <file> <line> <col> [--fuzzy]\n')
        return 1
    try:
        line = _parse_int(args[2], 'line')
        col = _parse_int(args[3], 'column')
        sys.setrecursionlimit(max(sys.getrecursionlimit(), 10000))
        results = complete(args[1], line, col, fuzzy)
    except SithError as e:
        sys.stderr.write('error: %s\n' % e)
        return 1
    out = json.dumps({'completions': results}, separators=(',', ':'))
    sys.stdout.write(out + '\n')
    sys.stdout.flush()
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
