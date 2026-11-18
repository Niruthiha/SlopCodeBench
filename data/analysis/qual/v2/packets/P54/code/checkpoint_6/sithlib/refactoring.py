"""Refactorings (``rename``, ``inline``, ``extract-variable``, ``extract-function``).

Secret: how each refactoring decides what to change (which occurrences a
rename touches and when it moves a module's file, what an inlined name is
replaced by and when that needs parentheses, which statement an extracted
expression goes before, which names an extracted function takes and returns),
which requests are refused, and how the edits are applied to file texts.
"""

import ast
import keyword
import os

from . import navigation, parsing, scopes, symbols
from .inference import DirectoryModule, Project, StaticModule, ValueTarget
from .source import SourceError, SourceFile


class RefactoringError(Exception):
    """The refactoring cannot be performed (bad request or unsafe change)."""


class Result:
    """The outcome of a refactoring: new texts of changed files and path renames.

    ``files`` maps absolute paths to ``(old_text, new_text)``; ``renames`` is a
    list of absolute ``(old_path, new_path)``.
    """

    def __init__(self, root):
        self.root = os.path.abspath(root)
        self.files = {}
        self.renames = []

    def set_text(self, path, old, new):
        if old != new:
            self.files[os.path.abspath(path)] = (old, new)

    def relative(self, path):
        relative = os.path.relpath(os.path.abspath(path), self.root)
        if relative.startswith(os.pardir):
            relative = os.path.abspath(path)
        return relative.replace(os.sep, "/")

    def changed_files(self):
        return {self.relative(path): new for path, (_, new) in sorted(self.files.items())}

    def renamed_paths(self):
        return {self.relative(old): self.relative(new) for old, new in self.renames}

    def diff(self):
        import difflib
        text = ""
        for old, new in self.renames:
            text += "rename from %s\nrename to %s\n" % (self.relative(old), self.relative(new))
        for path, (before, after) in sorted(self.files.items()):
            old_lines = before.splitlines(True)
            new_lines = after.splitlines(True)
            if old_lines and not old_lines[-1].endswith("\n"):
                old_lines[-1] += "\n"
            if new_lines and not new_lines[-1].endswith("\n"):
                new_lines[-1] += "\n"
            from_path = to_path = self.relative(path)
            for old, new in self.renames:
                if os.path.abspath(path) == old or path.startswith(old + os.sep):
                    to_path = self.relative(new + path[len(old):])
            text += "".join(difflib.unified_diff(old_lines, new_lines, fromfile=from_path,
                                                 tofile=to_path))
        return text


def check_identifier(name):
    if not name or not name.isidentifier() or keyword.iskeyword(name):
        raise RefactoringError("%r is not a valid Python identifier" % (name,))


# ---------------------------------------------------------------------------
# Text editing

class _Text:
    """A file's text addressed by (1-based line, 0-based character column)."""

    def __init__(self, text):
        self.text = text
        self.lines = text.split("\n")
        self.starts = []
        offset = 0
        for line in self.lines:
            self.starts.append(offset)
            offset += len(line) + 1

    def offset(self, line, col):
        line = max(1, min(line, len(self.lines)))
        return self.starts[line - 1] + max(0, min(col, len(self.lines[line - 1])))

    def line(self, number):
        return self.lines[number - 1] if 0 < number <= len(self.lines) else ""

    def char_col(self, line, byte_col):
        """Character column of an AST (UTF-8 byte) column on ``line``."""
        text = self.line(line)
        if text.isascii():
            return byte_col
        return len(text.encode("utf-8")[:byte_col].decode("utf-8", errors="ignore"))

    def start(self, node):
        return node.lineno, self.char_col(node.lineno, node.col_offset)

    def end(self, node):
        return node.end_lineno, self.char_col(node.end_lineno, node.end_col_offset)

    def segment(self, start, end):
        return self.text[self.offset(*start):self.offset(*end)]

    def find_name(self, line, col, name):
        """Character column of ``name`` reported at (line, col), or None."""
        text = self.line(line)
        if text[col:col + len(name)] == name:
            return col
        converted = self.char_col(line, col)
        if text[converted:converted + len(name)] == name:
            return converted
        return None


def _apply(text, edits):
    """Apply ``(start_offset, end_offset, replacement)`` edits to ``text``."""
    result = text
    last = None
    for start, end, replacement in sorted(edits, key=lambda e: (e[0], e[1]), reverse=True):
        if last is not None and end > last:
            raise RefactoringError("overlapping edits")
        result = result[:start] + replacement + result[end:]
        last = start
    return result


def _parse(text):
    try:
        return ast.parse(text)
    except (SyntaxError, ValueError):
        return parsing.parse_tolerant(text)


def _parses(text):
    try:
        return ast.parse(text)
    except (SyntaxError, ValueError, RecursionError, MemoryError):
        return None


def _read(path):
    return SourceFile(path).text()


def _prepare(path, line, col, root):
    source = SourceFile(path)
    source.check_position(line, col)
    project = Project(source.path, source.text(), root)
    byte_col = len(source.lines()[line - 1][:col].encode("utf-8"))
    found = navigation.find(project.main, line, byte_col)
    if found is None:
        raise navigation.NotOnName("no name at %d:%d" % (line, col))
    return source, project, found


# ---------------------------------------------------------------------------
# rename

def rename(path, line, col, new_name, root=None):
    check_identifier(new_name)
    source, project, found = _prepare(path, line, col, root)
    name, _, _, occurrence = found
    result = Result(project.root)
    module_path = _renamed_module(project, occurrence, name)
    if module_path is not None:
        target = _module_destination(module_path, new_name)
        directory = os.path.dirname(target)
        if new_name != name and (os.path.exists(os.path.join(directory, new_name)) or
                                 os.path.exists(os.path.join(directory, new_name + ".py"))):
            raise RefactoringError("cannot rename module %r: %r already exists"
                                   % (name, new_name))
    sites = {}
    for file_path, number, column, candidate, _ in symbols.occurrences_of(
            project, found, symbols.PROJECT):
        key = (os.path.abspath(file_path), number, column)
        if candidate is not None or key not in sites:
            sites[key] = candidate
    if new_name == name:
        return result
    if module_path is None:
        _check_collisions(project, occurrence, sites, new_name)
    by_file = {}
    for (file_path, number, column), candidate in sites.items():
        by_file.setdefault(file_path, []).append((number, column))
    for file_path, positions in sorted(by_file.items()):
        try:
            before = _read(file_path)
        except SourceError:
            continue
        text = _Text(before)
        edits = {}
        for number, column in positions:
            found_col = text.find_name(number, column, name)
            if found_col is None:
                continue
            start = text.offset(number, found_col)
            edits[start] = (start, start + len(name), new_name)
        result.set_text(file_path, before, _apply(before, edits.values()))
    if module_path is not None:
        result.renames.append((module_path, _module_destination(module_path, new_name)))
    return result


def _module_destination(module_path, new_name):
    directory = os.path.dirname(module_path)
    if os.path.isdir(module_path):
        return os.path.join(directory, new_name)
    return os.path.join(directory, new_name + os.path.splitext(module_path)[1])


def _renamed_module(project, occurrence, name):
    """The file or package directory whose module ``occurrence`` names (when
    renaming it means renaming the module), or None."""
    targets = occurrence.goto()
    importing = occurrence.kind == "module" or any(
        isinstance(t, scopes.Binding) and t.form == scopes.IMPORT
        and not t.details.get("as_name") and t.name == name for t in targets)
    followed = navigation._Follower(project).follow(targets)
    modules = []
    for target in followed:
        if isinstance(target, ValueTarget) and isinstance(target.value,
                                                          (StaticModule, DirectoryModule)):
            modules.append(target.value)
        else:
            modules = []
            break
    if modules:
        value = modules[0]
        if isinstance(value, StaticModule):
            location = value.analysis.path
            if os.path.splitext(os.path.basename(location))[0] == "__init__":
                location = os.path.dirname(location)
        else:
            location = value.directory
        location = os.path.abspath(location)
        base = os.path.splitext(os.path.basename(location))[0]
        if base == name:
            root = os.path.abspath(project.root)
            if not (location + os.sep).startswith(root + os.sep):
                raise RefactoringError("cannot rename module %r outside the project" % name)
            return location
    if importing:
        raise RefactoringError("cannot rename module %r: it is not part of the project" % name)
    return None


def _check_collisions(project, occurrence, sites, new_name):
    """Refuse a rename that would make ``new_name`` clash with an existing name."""
    message = "cannot rename to %r: the name already exists in scope" % new_name
    targets = occurrence.goto()
    targets = targets + navigation._Follower(project).follow(targets)
    for target in targets:
        bindings = getattr(target, "bindings", None) or [getattr(target, "binding", target)]
        for binding in bindings:
            if not isinstance(binding, scopes.Binding):
                continue
            owner = binding.details.get("owner")
            if owner is not None:
                scope_events = list(owner.events) + list(owner.instance_events)
            else:
                scope_events = list(binding.scope.events)
                if binding.scope.kind == scopes.Scope.CLASS:
                    scope_events += list(binding.scope.instance_events)
            if any(e.name == new_name for e in scope_events):
                raise RefactoringError(message)
            if owner is None and binding.scope.kind != scopes.Scope.CLASS:
                node = binding.scope.node
                reads = _NameEvents()
                for statement in getattr(node, "body", []):
                    reads.visit(statement)
                if any(event[1] == new_name for event in reads.events):
                    raise RefactoringError(message)
    for candidate in sites.values():
        if candidate is None or candidate.kind not in ("name", "binding", "global"):
            continue
        binding = candidate.extra.get("binding")
        if binding is not None and binding.details.get("owner") is not None:
            continue
        scope = candidate.scope
        if candidate.kind == "binding" and binding is not None:
            scope = binding.scope
        if any(e.name == new_name for e in scope.events):
            raise RefactoringError(message)


# ---------------------------------------------------------------------------
# inline

_ATOMS = (ast.Name, ast.Constant, ast.Attribute, ast.Call, ast.Subscript, ast.List,
          ast.Dict, ast.Set, ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp,
          ast.JoinedStr)


def inline(path, line, col, root=None):
    source, project, found = _prepare(path, line, col, root)
    name, _, _, occurrence = found
    targets = occurrence.goto()
    bindings = []
    for target in targets:
        target = getattr(target, "binding", target)
        if isinstance(target, scopes.Binding):
            bindings.append(target)
    if any(b.form in (scopes.DEF, scopes.CLASS) for b in bindings) or \
            occurrence.kind == "module":
        raise RefactoringError("cannot inline a function/class definition")
    if not bindings:
        raise RefactoringError("cannot inline %r: no definition found" % name)
    if any(b.form in (scopes.IMPORT, scopes.IMPORT_FROM, scopes.STAR) for b in bindings):
        raise RefactoringError("cannot inline an import")
    if any(b.form == scopes.PARAM for b in bindings):
        raise RefactoringError("cannot inline a parameter")
    if len({id(b) for b in bindings}) > 1:
        raise RefactoringError("cannot inline a name with multiple definitions")
    binding = bindings[0]
    statement = binding.stmt
    if binding.home.tree.path != source.path:
        raise RefactoringError("cannot inline a name defined in another file")
    simple = binding.form == scopes.ASSIGN and binding.details.get("owner") is None and (
        isinstance(statement, ast.Assign) and len(statement.targets) == 1
        and isinstance(statement.targets[0], ast.Name)
        or isinstance(statement, ast.AnnAssign) and statement.value is not None
        and isinstance(statement.target, ast.Name))
    if not simple:
        raise RefactoringError("can only inline a simple assignment (name = <expression>)")
    definition = (binding.position[0], binding.position[1])
    references = []
    for file_path, number, column, candidate, is_definition in symbols.occurrences_of(
            project, found, symbols.FILE):
        if os.path.abspath(file_path) != source.path:
            continue
        if (number, column) == definition:
            continue
        if is_definition:
            raise RefactoringError("cannot inline a name with multiple definitions")
        if (number, column) not in references:
            references.append((number, column))
    if not references:
        raise RefactoringError("name has no references to inline")
    before = source.text()
    text = _Text(before)
    value_text = text.segment(text.start(statement.value), text.end(statement.value))
    edits = [_deletion(text, statement, binding)]
    spots = []
    for number, column in sorted(references):
        found_col = text.find_name(number, column, name)
        if found_col is None:
            continue
        start = text.offset(number, found_col)
        spots.append((start, start + len(name)))
    if not spots:
        raise RefactoringError("name has no references to inline")
    _check_loads(_parse(before), text, spots)
    bare = _bare_spots(before, edits, spots, value_text, statement.value)
    replaced = [(s, e, value_text if (s, e) in bare else "(%s)" % value_text)
                for s, e in spots]
    result = Result(project.root)
    result.set_text(source.path, before, _apply(before, edits + replaced))
    return result


def _check_loads(tree, text, spots):
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and not isinstance(node.ctx, ast.Load):
            start = text.offset(*text.start(node))
            if any(s == start for s, _ in spots):
                raise RefactoringError("cannot inline a name that is reassigned or deleted")


def _bare_spots(before, edits, spots, value_text, value):
    """The reference spots where the value needs no parentheses."""
    wrapped = "(%s)" % value_text
    reference = _parses(_apply(before, edits + [(s, e, wrapped) for s, e in spots]))
    if reference is None:
        return {spot for spot in spots} if isinstance(value, _ATOMS) else set()
    expected = ast.dump(reference)
    bare = set()
    for spot in spots:
        trial = [(s, e, value_text if (s, e) == spot else wrapped) for s, e in spots]
        tree = _parses(_apply(before, edits + trial))
        if tree is not None and ast.dump(tree) == expected:
            bare.add(spot)
    tree = _parses(_apply(before, edits + [(s, e, value_text if (s, e) in bare else wrapped)
                                           for s, e in spots]))
    if tree is None or ast.dump(tree) != expected:
        return set()
    return bare


def _deletion(text, statement, binding):
    """Edit removing the defining statement."""
    start_line, start_col = text.start(statement)
    end_line, end_col = text.end(statement)
    prefix = text.line(start_line)[:start_col]
    suffix = text.line(end_line)[end_col:]
    start = text.offset(start_line, start_col)
    end = text.offset(end_line, end_col)
    if prefix.strip():
        semicolon = prefix.rstrip()
        if semicolon.endswith(";"):
            return (text.offset(start_line, len(semicolon) - 1), end, "")
        return (start, end, "pass")
    if suffix.strip().startswith(";"):
        rest = suffix[suffix.index(";") + 1:]
        skipped = len(suffix) - len(rest) + len(rest) - len(rest.lstrip())
        return (start, end + skipped, "")
    if _only_statement(binding, statement):
        return (start, text.offset(end_line, len(text.line(end_line))), "pass")
    line_start = text.offset(start_line, 0)
    if end_line < len(text.lines):
        return (line_start, text.offset(end_line + 1, 0), "")
    return (line_start, text.offset(end_line, len(text.line(end_line))), "")


def _only_statement(binding, statement):
    container = binding.home.node
    for node in ast.walk(container):
        for field in ("body", "orelse", "finalbody"):
            body = getattr(node, field, None)
            if isinstance(body, list) and statement in body:
                return len(body) == 1 and not isinstance(node, ast.Module)
    return False


# ---------------------------------------------------------------------------
# extract-variable

def extract_variable(path, line, col, until, new_name, root=None):
    check_identifier(new_name)
    source = SourceFile(path)
    source.check_position(line, col)
    before = source.text()
    text = _Text(before)
    tree = _parse(before)
    start, end = _trim(text, (line, col), _clamp(text, until))
    node, start, end = _expression_at(tree, text, start, end)
    if node is None:
        raise RefactoringError("selection is not a complete expression")
    statement = _statement_containing(tree, text, node)
    if statement is None:
        raise RefactoringError("selection is not a complete expression")
    if _uses_inner_variables(statement, node):
        raise RefactoringError("cannot extract an expression using comprehension or "
                               "lambda variables")
    first_line = min([statement.lineno] + [d.lineno for d in
                                            getattr(statement, "decorator_list", [])])
    indent = _indentation(text.line(first_line))
    expression = text.segment(text.start(node), text.end(node))
    assignment = "%s = %s" % (new_name, expression)
    if _parses(assignment) is None:
        assignment = "%s = (%s)" % (new_name, expression)
    insert = text.offset(first_line, 0)
    begin, finish = _without_grouping(before, text.offset(*start), text.offset(*end), new_name)
    edits = [(insert, insert, indent + assignment + "\n"), (begin, finish, new_name)]
    result = Result(root or os.path.dirname(source.path))
    result.set_text(source.path, before, _apply(before, edits))
    return result


def _without_grouping(text, begin, finish, name):
    """Widen the span ``begin:finish`` over grouping parentheses that would
    only surround ``name`` once it replaces the span."""
    expected = _parses(text[:begin] + name + text[finish:])
    if expected is None:
        return begin, finish
    expected = ast.dump(expected)
    while True:
        left = begin
        while left > 0 and text[left - 1] in " \t\n":
            left -= 1
        right = finish
        while right < len(text) and text[right] in " \t\n":
            right += 1
        if left == 0 or right >= len(text) or text[left - 1] != "(" or text[right] != ")":
            return begin, finish
        trial = _parses(text[:left - 1] + name + text[right + 1:])
        if trial is None or ast.dump(trial) != expected:
            return begin, finish
        begin, finish = left - 1, right + 1


def _uses_inner_variables(statement, node):
    """Whether ``node`` reads a variable of a comprehension or lambda around it
    inside ``statement``."""
    def search(current, local):
        if current is node:
            return any(isinstance(n, ast.Name) and n.id in local for n in ast.walk(node))
        if isinstance(current, (ast.ListComp, ast.SetComp, ast.GeneratorExp, ast.DictComp)):
            local = local | {n.id for g in current.generators for n in ast.walk(g.target)
                             if isinstance(n, ast.Name)}
        elif isinstance(current, ast.Lambda):
            local = local | {a.arg for a in navigation._arguments(current.args)}
        return any(search(child, local) for child in ast.iter_child_nodes(current))

    return search(statement, frozenset())


def _clamp(text, position):
    line, col = position
    line = max(1, min(line, len(text.lines)))
    return line, max(0, min(col, len(text.line(line))))


def _trim(text, start, end):
    """Selection without surrounding whitespace."""
    begin, finish = text.offset(*start), text.offset(*end)
    if finish < begin:
        raise RefactoringError("selection is not a complete expression")
    while begin < finish and text.text[begin].isspace():
        begin += 1
    while finish > begin and text.text[finish - 1].isspace():
        finish -= 1
    return _position(text, begin), _position(text, finish)


def _position(text, offset):
    import bisect
    index = bisect.bisect_right(text.starts, offset) - 1
    return index + 1, offset - text.starts[index]


def _expression_at(tree, text, start, end):
    """The expression node spanning exactly start..end (outer parentheses
    allowed), with the span to replace."""
    candidates = {}
    inside_fstring = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.JoinedStr):
            for inner in ast.walk(node):
                if inner is not node:
                    inside_fstring.add(id(inner))
    for node in ast.walk(tree):
        if not isinstance(node, ast.expr) or id(node) in inside_fstring:
            continue
        if isinstance(node, (ast.Starred, ast.Slice)) or \
                isinstance(getattr(node, "ctx", None), (ast.Store, ast.Del)):
            continue
        if getattr(node, "end_lineno", None) is None:
            continue
        key = (text.start(node), text.end(node))
        candidates.setdefault(key, node)
    outer = (start, end)
    while True:
        node = candidates.get((start, end))
        if node is not None:
            return node, outer[0], outer[1]
        selected = text.segment(start, end)
        if len(selected) < 2 or not (selected.startswith("(") and selected.endswith(")")):
            return None, start, end
        begin, finish = text.offset(*start) + 1, text.offset(*end) - 1
        start, end = _trim(text, _position(text, begin), _position(text, finish))


def _statement_containing(tree, text, node):
    """The innermost statement containing ``node`` where a new statement can go
    right before (an ``elif`` test counts as part of its ``if``)."""
    target = (text.start(node), text.end(node))
    best = None
    parents = {}
    for parent in ast.walk(tree):
        for child in ast.iter_child_nodes(parent):
            parents[id(child)] = parent
    for candidate in ast.walk(tree):
        if not isinstance(candidate, ast.stmt):
            continue
        span = (text.start(candidate), text.end(candidate))
        if span[0] <= target[0] and target[1] <= span[1]:
            if best is None or (span[0] >= best_span[0] and span[1] <= best_span[1]):
                best, best_span = candidate, span
    while best is not None and isinstance(best, ast.If):
        parent = parents.get(id(best))
        if isinstance(parent, ast.If) and parent.orelse == [best] and \
                text.line(best.lineno)[text.char_col(best.lineno, best.col_offset):] \
                .startswith("elif"):
            best = parent
        else:
            break
    return best


def _indentation(line):
    return line[:len(line) - len(line.lstrip())]


# ---------------------------------------------------------------------------
# extract-function

_NOT_VARIABLES = ("def", "class", "import")


def extract_function(path, line, col, until, new_name, root=None):
    check_identifier(new_name)
    source = SourceFile(path)
    source.check_position(line, col)
    before = source.text()
    text = _Text(before)
    tree = _parse(before)
    until = _clamp(text, until)
    first, last = line, until[0]
    if until[1] == 0 and last > first:
        last -= 1
        until = (last, len(text.line(last)))
    while last > first and not text.line(last).strip():
        last -= 1
        until = (last, len(text.line(last)))
    while first < last and not text.line(first).strip():
        first += 1
        line, col = first, 0
    selection = _statements_at(tree, text, (line, col), until)
    if selection is None:
        raise RefactoringError("selection must span complete statements")
    statements, ancestors = selection
    first = min([statements[0].lineno] + [d.lineno for d in
                                           getattr(statements[0], "decorator_list", [])])
    last = statements[-1].end_lineno
    enclosing = None
    for ancestor in reversed(ancestors):
        if isinstance(ancestor, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            enclosing = ancestor
            break
    scope_body = enclosing.body if enclosing is not None else tree.body
    inside = _NameEvents()
    for statement in statements:
        inside.visit(statement)
    whole = _NameEvents()
    for statement in scope_body:
        whole.visit(statement)

    outside_defined = set()
    for kind, name, number, _, form in whole.events:
        if kind == "store" and not first <= number <= last:
            if enclosing is None and form in _NOT_VARIABLES:
                continue
            outside_defined.add(name)
    if isinstance(enclosing, (ast.FunctionDef, ast.AsyncFunctionDef)):
        outside_defined.update(a.arg for a in navigation._arguments(enclosing.args))
    params = {}
    assigned = set()
    for kind, name, number, column, _ in inside.events:
        if kind == "load":
            if name not in assigned and name in outside_defined and name not in params:
                params[name] = (number, column)
        else:
            assigned.add(name)
    params = sorted(params, key=lambda n: params[n])
    used_after = {name for kind, name, number, _, _ in whole.events
                  if kind == "load" and number > last}
    stores = {}
    for kind, name, number, column, _ in inside.events:
        if kind == "store" and name in used_after and name not in stores:
            stores[name] = (number, column)
    returns = sorted(stores, key=lambda n: stores[n])
    has_return = any(isinstance(n, ast.Return) for s in statements for n in _own_nodes(s))

    method = None
    if isinstance(enclosing, (ast.FunctionDef, ast.AsyncFunctionDef)) and len(ancestors) >= 2:
        holder = ancestors[ancestors.index(enclosing) - 1] \
            if ancestors.index(enclosing) > 0 else None
        if isinstance(holder, ast.ClassDef) and enclosing in holder.body:
            method = _method_kind(enclosing, holder)
    call_target = new_name
    definition_params = list(params)
    decorator = None
    if method is not None:
        kind, receiver = method
        if kind == "static":
            decorator = "@staticmethod"
            call_target = "%s.%s" % (receiver, new_name)
        else:
            if kind == "class":
                decorator = "@classmethod"
            params = [p for p in params if p != receiver]
            definition_params = [receiver] + params
            call_target = "%s.%s" % (receiver, new_name)

    selected_lines = text.lines[first - 1:last]
    base_indent = _indentation(text.line(statements[0].lineno))
    if enclosing is not None:
        anchor = min([enclosing.lineno] + [d.lineno for d in enclosing.decorator_list])
        outer_indent = _indentation(text.line(anchor))
    else:
        anchor = first
        outer_indent = base_indent
    unit = _indent_unit(text, tree)
    body_indent = outer_indent + unit
    body = []
    for selected_line in selected_lines:
        if not selected_line.strip():
            body.append("")
        elif selected_line.startswith(base_indent):
            body.append(body_indent + selected_line[len(base_indent):])
        else:
            body.append(body_indent + selected_line.lstrip())
    if returns and not has_return:
        body.append(body_indent + "return " + ", ".join(returns))
    function = []
    if decorator:
        function.append(outer_indent + decorator)
    function.append("%s%sdef %s(%s):" % (outer_indent,
                                         "async " if _awaits(statements) else "",
                                         new_name, ", ".join(definition_params)))
    function.extend(body)
    function.extend([""] * (2 if not outer_indent else 1))
    call = "%s(%s)" % (call_target, ", ".join(params))
    if _awaits(statements):
        call = "await " + call
    if has_return:
        call = "return " + call
    elif returns:
        call = "%s = %s" % (", ".join(returns), call)
    lines = list(text.lines)
    lines[first - 1:last] = [base_indent + call]
    lines[anchor - 1:anchor - 1] = function
    result = Result(root or os.path.dirname(source.path))
    result.set_text(source.path, before, "\n".join(lines))
    return result


def _awaits(statements):
    return any(isinstance(n, (ast.Await, ast.AsyncFor, ast.AsyncWith))
               for s in statements for n in _own_nodes(s))


def _own_nodes(node):
    """Nodes of ``node`` outside nested function, lambda and class bodies."""
    yield node
    for child in ast.iter_child_nodes(node):
        if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda,
                              ast.ClassDef)):
            continue
        yield from _own_nodes(child)


def _method_kind(function, cls):
    """``(kind, receiver)``: ``("static", class name)``, ``("class", cls)`` or
    ``("instance", self)``."""
    names = [d.id for d in function.decorator_list if isinstance(d, ast.Name)]
    arguments = function.args.posonlyargs + function.args.args
    if "staticmethod" in names or not arguments:
        return "static", cls.name
    return ("class" if "classmethod" in names else "instance"), arguments[0].arg


def _indent_unit(text, tree):
    for node in ast.walk(tree):
        body = getattr(node, "body", None)
        if isinstance(node, ast.stmt) and isinstance(body, list) and body and \
                isinstance(body[0], ast.stmt) and body[0].lineno > node.lineno:
            outer = _indentation(text.line(node.lineno))
            inner = _indentation(text.line(body[0].lineno))
            if inner.startswith(outer) and len(inner) > len(outer):
                return inner[len(outer):]
    return "    "


def _statements_at(tree, text, start, end):
    """``(statements, ancestors)`` for the run of sibling statements spanning
    the selection exactly (by lines), or None."""
    def first_line(statement):
        return min([statement.lineno] + [d.lineno for d in
                                         getattr(statement, "decorator_list", [])])

    def search(node, ancestors):
        for field in ("body", "orelse", "finalbody", "handlers", "cases"):
            body = getattr(node, field, None)
            if not isinstance(body, list) or not body:
                continue
            if all(isinstance(s, ast.stmt) for s in body):
                for index, statement in enumerate(body):
                    if first_line(statement) != start[0]:
                        continue
                    opening = text.char_col(statement.lineno, statement.col_offset) \
                        if statement.lineno == start[0] else len(text.line(start[0]))
                    if text.line(start[0])[:start[1]].strip() or start[1] > opening:
                        return None
                    for other in body[index:]:
                        if other.end_lineno == end[0]:
                            closing = text.end(other)[1]
                            rest = text.line(end[0])[closing:end[1]]
                            if end[1] < closing and \
                                    text.line(end[0])[end[1]:closing].strip():
                                return None
                            if rest.strip() and not rest.strip().startswith(("#", ";")):
                                return None
                            return body[index:body.index(other) + 1], ancestors
                        if other.end_lineno > end[0]:
                            break
            for child in body:
                if getattr(child, "lineno", 0) <= start[0] <= \
                        (getattr(child, "end_lineno", 0) or 0):
                    found = search(child, ancestors + [child])
                    if found is not None:
                        return found
        return None

    return search(tree, [])


class _NameEvents:
    """Name loads and stores of statements in (roughly) execution order:
    ``(kind, name, line, column, form)``; names local to nested scopes are left
    out."""

    def __init__(self):
        self.events = []

    def load(self, name, node, skip):
        if name not in skip:
            self.events.append(("load", name, node.lineno, node.col_offset, None))

    def store(self, name, node, skip, form="var"):
        if name not in skip:
            self.events.append(("store", name, node.lineno, node.col_offset, form))

    def visit(self, node, skip=frozenset()):
        method = getattr(self, "visit_" + type(node).__name__, None)
        if method is not None:
            method(node, skip)
        else:
            for child in ast.iter_child_nodes(node):
                self.visit(child, skip)

    def visit_Name(self, node, skip):
        if isinstance(node.ctx, ast.Load):
            self.load(node.id, node, skip)
        else:
            self.store(node.id, node, skip)

    def visit_Assign(self, node, skip):
        self.visit(node.value, skip)
        for target in node.targets:
            self.visit(target, skip)

    def visit_AugAssign(self, node, skip):
        if isinstance(node.target, ast.Name):
            self.load(node.target.id, node.target, skip)
        else:
            self.visit(node.target, skip)
        self.visit(node.value, skip)
        if isinstance(node.target, ast.Name):
            self.store(node.target.id, node.target, skip)

    def visit_AnnAssign(self, node, skip):
        if node.value is not None:
            self.visit(node.value, skip)
            self.visit(node.target, skip)
        elif not isinstance(node.target, ast.Name):
            self.visit(node.target, skip)

    def visit_NamedExpr(self, node, skip):
        self.visit(node.value, skip)
        self.visit(node.target, skip)

    def visit_For(self, node, skip):
        self.visit(node.iter, skip)
        self.visit(node.target, skip)
        for child in node.body + node.orelse:
            self.visit(child, skip)

    visit_AsyncFor = visit_For

    def _comprehension(self, node, skip, results):
        local = set(skip)
        for generator in node.generators:
            local.update(n.id for n in ast.walk(generator.target) if isinstance(n, ast.Name))
        for index, generator in enumerate(node.generators):
            self.visit(generator.iter, skip if index == 0 else frozenset(local))
            for condition in generator.ifs:
                self.visit(condition, frozenset(local))
        for result in results:
            self.visit(result, frozenset(local))

    def visit_ListComp(self, node, skip):
        self._comprehension(node, skip, [node.elt])

    visit_SetComp = visit_GeneratorExp = visit_ListComp

    def visit_DictComp(self, node, skip):
        self._comprehension(node, skip, [node.key, node.value])

    def visit_Lambda(self, node, skip):
        for default in node.args.defaults + [d for d in node.args.kw_defaults if d]:
            self.visit(default, skip)
        local = set(skip) | {a.arg for a in navigation._arguments(node.args)}
        self.visit(node.body, frozenset(local))

    def visit_FunctionDef(self, node, skip):
        for child in node.decorator_list:
            self.visit(child, skip)
        args = node.args
        for default in args.defaults + [d for d in args.kw_defaults if d]:
            self.visit(default, skip)
        for arg in navigation._arguments(args):
            if arg.annotation is not None:
                self.visit(arg.annotation, skip)
        if node.returns is not None:
            self.visit(node.returns, skip)
        self.store(node.name, node, skip, "def")
        local = set(skip) | {a.arg for a in navigation._arguments(args)} | _bound(node.body)
        for child in node.body:
            self.visit(child, frozenset(local))

    visit_AsyncFunctionDef = visit_FunctionDef

    def visit_ClassDef(self, node, skip):
        for child in node.decorator_list + node.bases + [k.value for k in node.keywords]:
            self.visit(child, skip)
        local = set(skip) | _bound(node.body)
        for child in node.body:
            self.visit(child, frozenset(local))
        self.store(node.name, node, skip, "class")

    def visit_Import(self, node, skip):
        for alias in node.names:
            self.store(alias.asname or alias.name.split(".")[0], node, skip, "import")

    visit_ImportFrom = visit_Import

    def visit_ExceptHandler(self, node, skip):
        if node.type is not None:
            self.visit(node.type, skip)
        if node.name:
            self.store(node.name, node, skip)
        for child in node.body:
            self.visit(child, skip)

    def visit_Global(self, node, skip):
        pass

    visit_Nonlocal = visit_Global


def _bound(statements):
    """Names bound by ``statements`` in their own scope (minus global/nonlocal)."""
    bound, declared = set(), set()

    def walk(node):
        if isinstance(node, (ast.Global, ast.Nonlocal)):
            declared.update(node.names)
        elif isinstance(node, ast.Name) and not isinstance(node.ctx, ast.Load):
            bound.add(node.id)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            bound.add(node.name)
            for child in node.decorator_list:
                walk(child)
            return
        elif isinstance(node, (ast.Lambda, ast.ListComp, ast.SetComp, ast.GeneratorExp,
                               ast.DictComp)):
            return
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            for alias in node.names:
                bound.add(alias.asname or alias.name.split(".")[0])
        elif isinstance(node, ast.ExceptHandler) and node.name:
            bound.add(node.name)
        for child in ast.iter_child_nodes(node):
            walk(child)

    for statement in statements:
        walk(statement)
    return bound - declared
