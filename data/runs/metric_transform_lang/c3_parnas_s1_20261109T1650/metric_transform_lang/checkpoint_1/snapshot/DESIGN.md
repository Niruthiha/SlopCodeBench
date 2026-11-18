# MTL — design plan

`mtl.py` is a thin CLI over the `mtl_core` package. The package is decomposed
by **information hiding**: each module owns one design decision that is hard
to make or likely to change, and the rest of the program uses it only through
a small interface that would survive a change of that decision.

## Decisions likely to change → modules

| Module | Secret (one sentence) | Interface |
|---|---|---|
| `errors.py` | How failure categories map to exit codes and the diagnostic line format. | Exception classes `DslError`, `TypeCheckError`, `InputError`, `ExecutionError`; `report(err, stream) -> exit_code`. |
| `valuetypes.py` | The type lattice and compatibility rules (int↔float widening, which kinds compare, what is numeric). | Type constants; `is_numeric`, `can_compare`, `can_order`, `widen`, `type_name`. |
| `timestamps.py` | How timestamp text is parsed (ISO 8601 vs explicit format, default zone) and how instants are represented and formatted. | `TimestampParser(tz, fmt).parse(text)`, `looks_like_timestamp`, `to_epoch_micros`, `from_epoch_micros`, `format_utc`, `calendar_part`. Values are opaque but totally ordered. |
| `dataset.py` | How rows are stored in memory. | `Dataset.from_rows(names, types, rows)`, `has`, `type_of`, `records()` (read-only `Record.get(name)`), `filter(pred)`, `derive(name, type, fn)`. |
| `csv_source.py` | The CSV dialect, the fixed schema of the known columns, cell→value conversion, and type inference for extra columns. | `load_csv(path, timestamp_parser) -> Dataset` (raw read is separated so I/O errors surface first: `read_csv_text`, `build_dataset`). |
| `program.py` | *(the abstract syntax — the shared vocabulary, not a secret)* | Immutable node classes for statements and expressions. |
| `dsl_parser.py` | The concrete DSL syntax: tokens, comments, line continuation, precedence, statement shapes and the structural rules (one aggregate, ≤1 group_by/window, unique aliases). | `parse_program(text) -> program.Program`. |
| `expressions.py` | Static typing and evaluation of scalar/boolean expressions and transforms (null propagation, half-away-from-zero rounding, arithmetic fault detection). | `compile_expression(expr, schema) -> Compiled` with `.type` and `.evaluate(record)`; `schema` is any object with `has/type_of`. |
| `windowing.py` | Duration units and epoch-aligned tumbling-window arithmetic. | `TumblingWindow(amount, unit).bounds(ts) -> (start, end)`. |
| `aggregates.py` | The numeric algorithms of each aggregate (summation order, median, population var/std, finiteness checks) and their typing. | `make_aggregate(fn, input_type_or_None) -> Aggregate` with `.compute(values)`; `.wants_rows` for `count(*)`. |
| `engine.py` | The execution strategy: statement ordering semantics, how rows are bucketed by window and group key. | `execute(program, dataset) -> ResultSet` (`windowed`, `group_columns`, `aliases`, `rows` of `ResultRow`). |
| `output.py` | The JSON shape, key ordering, row ordering and value encoding. | `render(result_set) -> str`. |

`mtl.py` only parses CLI arguments, wires the modules together and converts
exceptions to exit codes via `errors.report`.

## Semantic choices (documented ambiguities)

* Pipeline order: `filter`/`apply` run in file order; `group_by`, `window` and
  `aggregate` are declarative and act on the final row set regardless of
  position.
* Error order: I/O (read DSL, read CSV) → DSL syntax → CSV value typing →
  static type check → execution.
* Known columns: `timestamp` → timestamp, `price`/`quantity` → float, the rest →
  string. A bad price/quantity/timestamp cell is a type error (exit 2).
  Missing required header / malformed CSV → I/O error (exit 3).
* Extra columns are inferred: int, then float, then bool (`true`/`false`),
  then timestamp (ISO-looking), else string. Empty cells in non-string extra
  columns are null; nulls make comparisons false, propagate through
  arithmetic/transforms and are skipped by aggregates (`count(*)` counts rows).
* Scalar expressions also support `+ - * / %` and unary minus on numbers;
  division/modulo by zero or any non-finite result → runtime error (exit 4).
* `day/month/year` are taken in UTC (consistent with window boundaries).
* Unknown columns, `in` misuse, mismatched comparisons, non-bool filters and
  non-numeric aggregate inputs (including `sum(*)`) are type errors (exit 2).
* Only non-empty windows/groups are emitted. With neither group nor window a
  single object is emitted even for zero rows (`count` 0, others `null`).
* `sum/min/max` of an int column stay int; other aggregates are floats.
  `round` returns a float. `-0.0` is emitted as `0.0`.
* Output is UTF-8 JSON, 2-space indented, newline-terminated.
