"""The `extract-variable` and `extract-function` commands."""
import ast
import os

from .errors import SithError
from .refactoring import (Refactoring, Source, apply_edits, check_identifier, dump,
                          replaced_tree, same_tree)

_SCOPES = (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)
_FUNCTIONS = (ast.FunctionDef, ast.AsyncFunctionDef)
_COMPREHENSIONS = (ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp)
_INDENT = "    "


def _identifier_char(char):
    return char == "_" or char.isalnum()


def _selection(source, start, until):
    """Absolute (start, end) offsets of the selection, with surrounding whitespace trimmed."""
    for line, col in (start, until):
        if not 1 <= line <= len(source.lines):
            raise SithError(f"line {line} is out of range (file has {len(source.lines)} lines)")
        if col < 0:
            raise SithError(f"column {col} is out of range")
    text = source.text
    begin = source.offset(start[0], min(start[1], len(source.lines[start[0] - 1])))
    end = source.offset(until[0], min(until[1], len(source.lines[until[0] - 1])))
    if end < begin:
        raise SithError("the selection ends before it starts")
    # An end inside an identifier or number is taken to include it (an inclusive end column).
    if begin < end < len(text) and _identifier_char(text[end - 1]) and _identifier_char(text[end]):
        while end < len(text) and _identifier_char(text[end]):
            end += 1
    while begin < end and text[begin].isspace():
        begin += 1
    while end > begin and text[end - 1].isspace():
        end -= 1
    if begin == end:
        raise SithError("the selection is empty")
    return begin, end


def _ancestors(source, node):
    parent = source.parent(node)
    while parent is not None:
        yield parent
        parent = source.parent(parent)


def _statement_of(source, node):
    for ancestor in _ancestors(source, node):
        if isinstance(ancestor, ast.stmt):
            return ancestor
    return None


# -- extract variable ----------------------------------------------------------------

def extract_variable(path, start, until, name, project=None):
    check_identifier(name, "--name")
    source = Source(path)
    begin, end = _selection(source, start, until)
    node, begin, end = _expression_at(source, begin, end)
    statement = _statement_of(source, node)
    _check_extractable(source, node, statement)
    text = source.text
    expression = text[source.start(node):source.end(node)]
    # The replacement, dropping parentheses that only grouped the extracted expression.
    expected = dump(replaced_tree(source.tree, {id(node): ast.Name(id=name, ctx=ast.Load())}))
    replace = (begin, end)
    outer_begin, outer_end = begin, end
    while True:
        before = text[:outer_begin].rstrip()
        after = text[outer_end:].lstrip()
        if not (before.endswith("(") and after.startswith(")")):
            break
        outer_begin, outer_end = len(before) - 1, len(text) - len(after) + 1
        if same_tree(text[:outer_begin] + name + text[outer_end:], expected):
            replace = (outer_begin, outer_end)
    assignment = f"{name} = {expression}"
    value_dump = dump(node)
    try:
        parsed = ast.parse(assignment)
        valid = len(parsed.body) == 1 and dump(parsed.body[0].value) == value_dump
    except (SyntaxError, ValueError):
        valid = False
    if not valid:
        assignment = f"{name} = ({expression})"
    edits = [(replace[0], replace[1], name), _insertion(source, statement, assignment)]
    refactoring = Refactoring(project or os.path.dirname(source.path))
    refactoring.change(source.path, text, apply_edits(text, edits))
    return refactoring


def _expression_at(source, begin, end):
    """The expression node spanning exactly [begin, end), allowing enclosing parentheses."""
    spans = {}
    for node in ast.walk(source.tree):
        if isinstance(node, ast.expr):
            spans.setdefault((source.start(node), source.end(node)), node)
    text = source.text
    inner_begin, inner_end = begin, end
    while True:
        node = spans.get((inner_begin, inner_end))
        if node is not None:
            return node, begin, end
        if text[inner_begin] == "(" and text[inner_end - 1] == ")" and \
                _matching_paren(text, inner_begin) == inner_end - 1:
            inner_begin += 1
            inner_end -= 1
            while inner_begin < inner_end and text[inner_begin].isspace():
                inner_begin += 1
            while inner_end > inner_begin and text[inner_end - 1].isspace():
                inner_end -= 1
            continue
        raise SithError("selection is not a complete expression")


def _matching_paren(text, index):
    depth = 0
    quote = None
    i = index
    while i < len(text):
        char = text[i]
        if quote:
            if char == "\\":
                i += 1
            elif text.startswith(quote, i):
                i += len(quote) - 1
                quote = None
        elif char in "\"'":
            quote = char * 3 if text.startswith(char * 3, i) else char
            i += len(quote) - 1
        elif char == "#":
            newline = text.find("\n", i)
            i = len(text) if newline < 0 else newline
            continue
        elif char in "([{":
            depth += 1
        elif char in ")]}":
            depth -= 1
            if depth == 0:
                return i
        i += 1
    return None


def _check_extractable(source, node, statement):
    parent = source.parent(node)
    in_format = isinstance(parent, ast.JoinedStr) or \
        isinstance(parent, ast.FormattedValue) and node is parent.format_spec
    if statement is None or in_format or isinstance(node, (ast.Starred, ast.Slice)):
        raise SithError("selection is not a complete expression")
    if not isinstance(getattr(node, "ctx", ast.Load()), ast.Load):
        raise SithError("cannot extract an assignment target")
    if isinstance(parent, ast.comprehension) and node is parent.target:
        raise SithError("cannot extract an assignment target")
    names = {n.id for n in ast.walk(node) if isinstance(n, ast.Name)}
    for ancestor in _ancestors(source, node):
        if ancestor is statement:
            break
        bound = set()
        if isinstance(ancestor, ast.Lambda):
            bound = {a.arg for a in _arguments(ancestor.args)}
        elif isinstance(ancestor, _COMPREHENSIONS):
            for generator in ancestor.generators:
                bound |= {n.id for n in ast.walk(generator.target) if isinstance(n, ast.Name)}
        if names & bound:
            raise SithError("cannot extract an expression that uses names bound inside it "
                            "(lambda parameters or comprehension variables)")
    if isinstance(statement, ast.If) and statement.test is not None and \
            any(statement is s for s in getattr(source.parent(statement), "orelse", [])) and \
            source.text[source.start(statement):].startswith("elif") and \
            _within(source, node, statement.test):
        raise SithError("cannot extract from an elif condition")


def _within(source, node, container):
    return source.start(container) <= source.start(node) and \
        source.end(node) <= source.end(container)


def _arguments(arguments):
    params = arguments.posonlyargs + arguments.args + arguments.kwonlyargs
    return params + [a for a in (arguments.vararg, arguments.kwarg) if a is not None]


def _first_line(statement):
    decorators = getattr(statement, "decorator_list", None) or []
    return min([statement.lineno] + [d.lineno for d in decorators])


def _insertion(source, statement, code):
    """An edit inserting the one-line statement `code` just before `statement`."""
    line = _first_line(statement)
    start = source.offset(line, 0)
    first = source.start(statement) if line == statement.lineno else start
    prefix = source.text[start:first]
    if prefix.strip():  # after `;` or a block header on the same line
        return first, first, f"{code}; "
    return start, start, f"{prefix}{code}\n"


# -- extract function ----------------------------------------------------------------

def extract_function(path, start, until, name, project=None):
    check_identifier(name, "--name")
    source = Source(path)
    begin, end = _selection(source, start, until)
    text = source.text
    remainder = text[end:text.find("\n", end) if "\n" in text[end:] else len(text)]
    if len(remainder.strip()) == 1:  # an inclusive end column on the last character
        end += len(remainder.rstrip())
    # Whole lines: only whitespace before the selection and whitespace or a comment after it.
    line_start = text.rfind("\n", 0, begin) + 1
    line_end = text.find("\n", end)
    line_end = len(text) if line_end < 0 else line_end
    if text[line_start:begin].strip():
        raise SithError("selection does not span complete statements")
    statements = _selected_statements(source, begin, end)
    trailing = text[source.end(statements[-1]):line_end].strip()
    if trailing and not trailing.startswith("#"):
        raise SithError("selection does not span complete statements")
    scope = _enclosing_scope(source, statements[0])
    analysis = _Analysis(source, scope, statements, begin, end)
    first_indent = source.indent_of(statements[0].lineno)
    body_lines = text[line_start:line_end].split("\n")
    is_async = analysis.awaits

    params = list(analysis.parameters)
    returns = [] if analysis.ends_with_return else list(analysis.returns)
    decorator = ""
    receiver = ""
    in_module = isinstance(scope, ast.Module)
    if in_module:
        indent = first_indent
        insert_at = line_start
    else:
        indent = source.indent_of(_first_line(scope))
        insert_at = source.offset(_first_line(scope), 0)
        container = source.parent(scope)
        if isinstance(scope, _FUNCTIONS) and isinstance(container, ast.ClassDef):
            decorators = {d.id for d in scope.decorator_list if isinstance(d, ast.Name)}
            if "staticmethod" in decorators:
                decorator = "@staticmethod"
                receiver = container.name + "."
            else:
                arguments = scope.args.posonlyargs + scope.args.args
                if arguments:
                    first = arguments[0].arg
                    params = [first] + [p for p in params if p != first]
                    receiver = first + "."
                if "classmethod" in decorators:
                    decorator = "@classmethod"
    body_indent = indent + _INDENT
    body = []
    for line in body_lines:
        if line.startswith(first_indent):
            body.append(body_indent + line[len(first_indent):] if line.strip() else "")
        else:
            body.append(line if not line.strip() else body_indent + line.lstrip())
    if returns:
        body.append(f"{body_indent}return {', '.join(returns)}")
    header = f"{indent}{'async ' if is_async else ''}def {name}({', '.join(params)}):"
    function_lines = ([f"{indent}{decorator}"] if decorator else []) + [header] + body
    separator = "\n\n\n" if not indent else "\n\n"
    function_code = "\n".join(function_lines) + separator

    call_arguments = [p for p in params if not (receiver and p == params[0] and
                                                 p + "." == receiver)]
    call = f"{'await ' if is_async else ''}{receiver}{name}({', '.join(call_arguments)})"
    if analysis.ends_with_return:
        call_line = f"{first_indent}return {call}"
    elif returns:
        call_line = f"{first_indent}{', '.join(returns)} = {call}"
    else:
        call_line = f"{first_indent}{call}"
    if in_module:
        edits = [(line_start, line_end, function_code + call_line)]
    else:
        edits = [(insert_at, insert_at, function_code), (line_start, line_end, call_line)]
    refactoring = Refactoring(project or os.path.dirname(source.path))
    refactoring.change(source.path, text, apply_edits(text, edits))
    return refactoring


def _selected_statements(source, begin, end):
    """The consecutive sibling statements covering exactly the selection."""
    selected = []
    for node in ast.walk(source.tree):
        if not isinstance(node, ast.stmt):
            continue
        node_start, node_end = source.start(node), source.end(node)
        if node_end <= begin or node_start >= end:
            continue
        if node_start <= begin and node_end >= end and not (node_start == begin and
                                                            node_end == end):
            continue  # encloses the selection
        if begin <= node_start and node_end <= end:
            selected.append(node)
            continue
        raise SithError("selection does not span complete statements")
    ids = {id(node) for node in selected}
    top = [node for node in selected if not any(id(a) in ids for a in _ancestors(source, node))]
    if not top:
        raise SithError("selection does not contain any statement")
    top.sort(key=source.start)
    parent = source.parent(top[0])
    for field in ("body", "orelse", "finalbody"):
        body = getattr(parent, field, None)
        if isinstance(body, list) and any(s is top[0] for s in body):
            index = next(i for i, s in enumerate(body) if s is top[0])
            if body[index:index + len(top)] == top:
                break
    else:
        bodies = [handler.body for handler in getattr(parent, "handlers", [])]
        bodies += [case.body for case in getattr(parent, "cases", [])]
        for body in bodies:
            if any(s is top[0] for s in body):
                index = next(i for i, s in enumerate(body) if s is top[0])
                if body[index:index + len(top)] == top:
                    break
        else:
            raise SithError("selection does not span complete statements")
    # Text between the statements must be whitespace, comments or `;`.
    for previous, current in zip(top, top[1:]):
        between = source.text[source.end(previous):source.start(current)]
        if any(line.strip() and not line.strip().startswith("#") and line.strip() != ";"
               for line in between.split("\n")):
            raise SithError("selection does not span complete statements")
    text = source.text[begin:source.start(top[0])] + source.text[source.end(top[-1]):end]
    if any(line.strip() and not line.strip().startswith("#") and line.strip() != ";"
           for line in text.split("\n")):
        raise SithError("selection does not span complete statements")
    return top


def _enclosing_scope(source, node):
    for ancestor in _ancestors(source, node):
        if isinstance(ancestor, (ast.Module,) + _SCOPES):
            return ancestor
    return source.tree


class _Analysis:
    """Which names the selected statements read from and hand back to their scope."""

    def __init__(self, source, scope, statements, begin, end):
        self.source = source
        self.begin, self.end = begin, end
        self.awaits = False
        _check_control_flow(source, statements, self)
        self.ends_with_return = isinstance(statements[-1], ast.Return)

        scope_events = _Scanner(source).scan_scope(scope)
        declared = _declared_names(scope)
        local = set()
        outside = set()
        if isinstance(scope, _FUNCTIONS):
            outside |= {a.arg for a in _arguments(scope.args)}
            local |= outside
        for event in scope_events:
            if event.store and event.name not in declared:
                local.add(event.name)
                if not begin <= event.offset < end:
                    outside.add(event.name)
        for ancestor in _ancestors(source, scope):
            if isinstance(ancestor, _FUNCTIONS):
                closure = {a.arg for a in _arguments(ancestor.args)}
                closure |= {e.name for e in _Scanner(source).scan_scope(ancestor) if e.store}
                outside |= closure - local
                local |= closure

        events = []
        scanner = _Scanner(source)
        for statement in statements:
            scanner.statement(statement, 0, events)
        definite = set()
        parameters = {}
        stored = {}
        for event in events:
            if event.store:
                stored.setdefault(event.name, event.offset)
                if event.depth == 0:
                    definite.add(event.name)
            elif event.name not in definite and event.name in outside and \
                    event.name not in declared:
                parameters.setdefault(event.name, event.offset)
        self.parameters = sorted(parameters, key=lambda n: (parameters[n], n))

        # Reads after the selection (or anywhere in a loop around it) need the new values.
        loop_ranges = [(source.start(a), source.end(a)) for a in _ancestors(source, statements[0])
                       if isinstance(a, (ast.For, ast.AsyncFor, ast.While)) and
                       _inside_scope(source, a, scope)]
        used = set()
        for event in scope_events:
            if event.store or begin <= event.offset < end:
                continue
            if event.offset >= end or any(s <= event.offset < e for s, e in loop_ranges):
                used.add(event.name)
        self.returns = sorted((n for n in stored if n in used and n not in declared),
                              key=lambda n: (stored[n], n))


def _inside_scope(source, node, scope):
    for ancestor in _ancestors(source, node):
        if isinstance(ancestor, (ast.Module,) + _SCOPES):
            return ancestor is scope
    return scope is source.tree


def _declared_names(scope):
    """Names declared `global` or `nonlocal` in a function scope."""
    if not isinstance(scope, _FUNCTIONS):
        return set()
    names = set()
    stack = list(scope.body)
    while stack:
        node = stack.pop()
        if isinstance(node, (ast.Global, ast.Nonlocal)):
            names.update(node.names)
        if not isinstance(node, _SCOPES):
            stack.extend(ast.iter_child_nodes(node))
    return names


def _check_control_flow(source, statements, analysis):
    """Refuse statements whose control flow cannot move into a function."""
    last = statements[-1]
    stack = [(statement, False) for statement in statements]
    while stack:
        node, in_loop = stack.pop()
        if isinstance(node, (ast.Yield, ast.YieldFrom)):
            raise SithError("cannot extract code containing `yield`")
        if isinstance(node, (ast.Await, ast.AsyncFor, ast.AsyncWith)):
            analysis.awaits = True
        if isinstance(node, ast.Return) and node is not last:
            raise SithError("cannot extract a `return` that does not end the selection")
        if isinstance(node, (ast.Break, ast.Continue)) and not in_loop:
            raise SithError(f"cannot extract `{type(node).__name__.lower()}` "
                            "outside of its loop")
        if isinstance(node, (ast.Global, ast.Nonlocal)):
            raise SithError(f"cannot extract a `{type(node).__name__.lower()}` statement")
        if isinstance(node, _SCOPES):
            continue
        for child in ast.iter_child_nodes(node):
            loop = in_loop or isinstance(node, (ast.For, ast.AsyncFor, ast.While)) and \
                any(child is s for s in node.body)
            stack.append((child, loop))


class _Event:
    __slots__ = ("name", "store", "offset", "depth")

    def __init__(self, name, store, offset, depth):
        self.name = name
        self.store = store
        self.offset = offset
        self.depth = depth


class _Scanner:
    """Name reads and writes of statements, in evaluation order.

    Nested scopes contribute a read of each of their free names (at their
    position) and nothing else; `depth` counts the enclosing blocks that may
    not run, so stores at depth 0 always happen.
    """

    def __init__(self, source):
        self.source = source

    def scan_scope(self, scope):
        events = []
        for statement in scope.body:
            self.statement(statement, 0, events)
        return events

    def _event(self, events, name, store, node, depth):
        events.append(_Event(name, store, self.source.start(node), depth))

    def _store(self, target, depth, events):
        """Events of an assignment target: reads inside it, then the names it binds."""
        names = []
        for node in ast.walk(target):
            if isinstance(node, ast.Name):
                if isinstance(node.ctx, ast.Load):
                    self._event(events, node.id, False, node, depth)
                else:
                    names.append(node)
            elif isinstance(node, (ast.Attribute, ast.Subscript)):
                for child in ast.iter_child_nodes(node):
                    if not isinstance(child, ast.expr_context):
                        self.expression(child, depth, events)
        for node in names:
            self._event(events, node.id, True, node, depth)

    def statement(self, node, depth, events):
        nested = depth + 1
        if isinstance(node, _FUNCTIONS):
            for expression in node.decorator_list + node.args.defaults + \
                    [d for d in node.args.kw_defaults if d is not None]:
                self.expression(expression, depth, events)
            for argument in _arguments(node.args):
                self.expression(argument.annotation, depth, events)
            self.expression(node.returns, depth, events)
            bound = {a.arg for a in _arguments(node.args)}
            self._free(node, node.body, bound, depth, events)
            self._event(events, node.name, True, node, depth)
        elif isinstance(node, ast.ClassDef):
            for expression in node.decorator_list + node.bases + [k.value for k in node.keywords]:
                self.expression(expression, depth, events)
            self._free(node, node.body, set(), depth, events)
            self._event(events, node.name, True, node, depth)
        elif isinstance(node, ast.Assign):
            self.expression(node.value, depth, events)
            for target in node.targets:
                self._store(target, depth, events)
        elif isinstance(node, ast.AugAssign):
            if isinstance(node.target, ast.Name):
                self._event(events, node.target.id, False, node.target, depth)
            self.expression(node.value, depth, events)
            self._store(node.target, depth, events)
        elif isinstance(node, ast.AnnAssign):
            self.expression(node.annotation, depth, events)
            self.expression(node.value, depth, events)
            if node.value is not None or not isinstance(node.target, ast.Name):
                self._store(node.target, depth, events)
        elif isinstance(node, (ast.For, ast.AsyncFor)):
            self.expression(node.iter, depth, events)
            self._store(node.target, nested, events)
            for child in node.body + node.orelse:
                self.statement(child, nested, events)
        elif isinstance(node, (ast.While, ast.If)):
            self.expression(node.test, depth, events)
            for child in node.body + node.orelse:
                self.statement(child, nested, events)
        elif isinstance(node, (ast.With, ast.AsyncWith)):
            for item in node.items:
                self.expression(item.context_expr, depth, events)
                if item.optional_vars is not None:
                    self._store(item.optional_vars, depth, events)
            for child in node.body:
                self.statement(child, depth, events)
        elif isinstance(node, (ast.Try, getattr(ast, "TryStar", ast.Try))):
            for child in node.body:
                self.statement(child, nested, events)
            for handler in node.handlers:
                self.expression(handler.type, nested, events)
                if handler.name:
                    self._event(events, handler.name, True, handler, nested)
                for child in handler.body:
                    self.statement(child, nested, events)
            for child in node.orelse + node.finalbody:
                self.statement(child, nested, events)
        elif isinstance(node, ast.Match):
            self.expression(node.subject, depth, events)
            for case in node.cases:
                for pattern in ast.walk(case.pattern):
                    if isinstance(pattern, ast.MatchValue):
                        self.expression(pattern.value, nested, events)
                    elif isinstance(pattern, ast.MatchClass):
                        self.expression(pattern.cls, nested, events)
                    for attribute in ("name", "rest"):
                        bound = getattr(pattern, attribute, None)
                        if isinstance(bound, str):
                            self._event(events, bound, True, pattern, nested)
                self.expression(case.guard, nested, events)
                for child in case.body:
                    self.statement(child, nested, events)
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            for alias in node.names:
                if alias.name != "*":
                    bound = alias.asname or alias.name.split(".")[0]
                    self._event(events, bound, True, alias, depth)
        elif isinstance(node, ast.Delete):
            for target in node.targets:
                self._store(target, depth, events)
        elif isinstance(node, (ast.Global, ast.Nonlocal)):
            pass
        else:
            for child in ast.iter_child_nodes(node):
                if isinstance(child, ast.stmt):
                    self.statement(child, depth, events)
                else:
                    self.expression(child, depth, events)

    def expression(self, node, depth, events):
        if node is None:
            return
        if isinstance(node, ast.Name):
            self._event(events, node.id, not isinstance(node.ctx, ast.Load), node, depth)
        elif isinstance(node, ast.NamedExpr):
            self.expression(node.value, depth, events)
            self._event(events, node.target.id, True, node.target, depth)
        elif isinstance(node, ast.Lambda):
            for default in node.args.defaults + [d for d in node.args.kw_defaults if d]:
                self.expression(default, depth, events)
            bound = {a.arg for a in _arguments(node.args)}
            inner = []
            self.expression(node.body, depth, inner)
            self._report_free(node, inner, bound, set(), depth, events)
        elif isinstance(node, _COMPREHENSIONS):
            generators = node.generators
            self.expression(generators[0].iter, depth, events)
            inner = []
            bound = set()
            for index, generator in enumerate(generators):
                if index:
                    self.expression(generator.iter, depth, inner)
                self._store(generator.target, depth, inner)
                bound |= {n.id for n in ast.walk(generator.target) if isinstance(n, ast.Name)}
                for condition in generator.ifs:
                    self.expression(condition, depth, inner)
            if isinstance(node, ast.DictComp):
                self.expression(node.key, depth, inner)
                self.expression(node.value, depth, inner)
            else:
                self.expression(node.elt, depth, inner)
            for event in inner:
                if event.name in bound:
                    continue
                events.append(event)  # free reads, and walrus targets binding outside
        elif isinstance(node, ast.AST):
            for child in ast.iter_child_nodes(node):
                if isinstance(child, ast.AST) and not isinstance(child, ast.expr_context):
                    self.expression(child, depth, events)

    def _free(self, node, body, bound, depth, events):
        inner = []
        for statement in body:
            self.statement(statement, 0, inner)
        self._report_free(node, inner, bound, _declared_names(node), depth, events)

    def _report_free(self, node, inner, bound, declared, depth, events):
        local = set(bound) | {e.name for e in inner if e.store and e.name not in declared}
        reported = set()
        for event in inner:
            if not event.store and event.name not in local and event.name not in reported:
                reported.add(event.name)
                self._event(events, event.name, False, node, depth)
