# sith — design

`python sith.py complete <file> <line> <col> [--fuzzy]` prints completions as JSON.
Standard library only (`requirements.txt` lists no packages).

## Decisions likely to change, and the module that hides each

| Module | Secret (the decision it hides) |
|---|---|
| `sithlib/source.py` | How a file is read, decoded and split into lines, and how a (line, col) cursor is validated. |
| `sithlib/parsing.py` | The repair strategy that turns broken source into a syntax tree without shifting line numbers. |
| `sithlib/cursor.py` | How the text before the cursor is lexed into a context (name / attribute / none), the typed prefix, and the receiver expression. |
| `sithlib/scopes.py` | How bindings are found in the tree, which scope owns them, and the (indentation-aware) rules for the scope at a cursor and for visibility. |
| `sithlib/modules.py` | How an imported module is located: project source file/package first, otherwise a runtime import with side effects contained. |
| `sithlib/introspect.py` | How live Python objects are classified and their attributes enumerated and fetched safely. |
| `sithlib/vocabulary.py` | Where builtin names and keywords come from. |
| `sithlib/inference.py` | How bindings and expressions map to values (module/class/function/instance), name resolution through scopes, star imports and builtins, and member enumeration. |
| `sithlib/matching.py` | The prefix / fuzzy matching algorithm and the "text still to insert" rule. |
| `sithlib/ranking.py` | The ordering rules (public, private, dunder, keywords; case-insensitive). |
| `sithlib/presentation.py` | The wording of the `type` and `description` fields. |
| `sithlib/output.py` | The wire format (compact, newline-terminated JSON). |
| `sithlib/engine.py` | The completion policy: what each cursor context offers and how filtering, wording and ranking combine. |
| `sith.py` | Command-line parsing, exit codes and error reporting. |

## Interfaces between modules

Modules talk only through small interfaces, never through each other's internal
data structures:

* `cursor.analyze(text_before) -> CursorContext(kind, prefix, receiver_text)`
* `inference.Project(path, text).location(line, col)` returns a `Location` with
  `visible_entities()` and `evaluate(expression_text)`.
* A `Value` exposes `kind`, `type_name` and `members()`; an `Entity` exposes `name`,
  `presentation() -> (kind, type_name)` and `value()`.
* `matching.matches(name, query, fuzzy)` and `matching.remaining_text(name, query)`.
* `ranking.rank(items, name_of, is_keyword)`.
* `presentation.describe(name, kind, type_name) -> (type, description)`.
* `output.write_completions([(name, complete, type, description), ...])`.

## Behaviour choices where the specification is silent

* Inside a comment or string literal, no completions are returned.
* `True`, `False` and `None` are offered only as keywords, not also as builtins.
* Class scopes are not visible from inside their methods, matching Python.
* Literal receivers list every attribute of their builtin type, dunders included.
  Module receivers list public names only.
* Star imports bring in every public name. `__all__` is not consulted.
* A trailing newline at the end of the file counts as an extra, empty last line, so
  the cursor can sit on it.
