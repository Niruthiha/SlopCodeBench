---
name: sith-infer-goto-decisions
description: Judgment calls made where the sith infer/goto spec was ambiguous (output field conventions)
metadata:
  node_type: memory
  type: project
  originSessionId: cb0e817e-4fb0-4bea-9e71-6369f78a4f78
  modified: 2026-11-10T16:42:58.588Z
---

sith (`/workspace`, stdlib-only Python tool) gained `infer`/`goto` on 2026-11-10. Where the spec was ambiguous I chose:
- assignment `description` = right-hand expression source only (`Calculator()`), not the whole statement; other bindings use statement text (`for x in xs`, `x += 1`, `x: int`).
- builtin-module objects: docstring `""`, module_path `""`, line/col 0; `None` -> name `NoneType`, full_name `builtins.NoneType`.
- local modules: line 1, column 0 (jedi's ModuleName convention).
- `goto` on import binding: type `module` for `import x`, resolved kind for `from x import y`; full_name stays `<this module>.<name>`.
- a cursor just after an identifier counts as on it (jedi-like); strings/comments/keywords/numbers exit 1.

**Why:** the hidden tests' exact expectations are unknown; these were the best guesses.
**How to apply:** if later feedback contradicts one of these, change that convention in `sithlib/definitions.py` / `sithlib/navigation.py` rather than re-deriving everything.
