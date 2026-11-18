# MTL — design plan

Single-file CLI `mtl.py` (stdlib only; `tzdata` in `requirements.txt` so IANA zones
resolve on systems without a system tz database).

## Pipeline of the program

1. **CLI** (`argparse`, with usage errors mapped to `ERROR:bad_io:` / exit 3).
2. **Read DSL** (file or STDIN) → I/O errors exit 3.
3. **Parse DSL** → `Program(steps=[filter|apply...], group_by, window, aggregates)`.
   Syntax errors exit 1.
4. **Load CSV** → header + rows, typed columns. Missing file / bad encoding /
   ragged rows / missing required columns exit 3; unparsable typed values exit 2.
5. **Static type check** of the whole pipeline against the CSV schema (so type
   errors surface even with zero rows) → exit 2.
6. **Execute** row ops in order, then bucket by (window, group key), aggregate,
   normalize, serialize. Runtime failures (division by zero, NaN/Inf) exit 4.

All errors are raised as `MTLError(kind, msg)`; `main` prints exactly one line
`ERROR:<kind>:<msg>` to STDERR and exits with the mapped code. Output is only
written after full success.

## DSL parsing

* Lines are scanned with a quote-aware scanner: `#` outside a string starts a
  comment. Physical lines are joined into one statement while brackets are
  unbalanced or the text ends with `,` (this supports the multi-line
  `aggregate` list).
* Statements: `filter(expr)`, `apply(expr, ident)`, `group_by(ident | [ident,...])`,
  `window(<int><m|h|d>)`, `aggregate fn(col|*) as alias, ...`.
  Duplicate `group_by`/`window`, zero or multiple `aggregate`, unknown
  statements, unknown aggregate functions, duplicate aliases, aliases colliding
  with output keys → exit 1.
* `filter`/`apply` run in declared order; `group_by`, `window`, `aggregate` are
  declarative and act on the final row set (their position does not matter).
* Expression grammar (recursive descent), lowest → highest precedence:
  `|` → `&` → `!` → comparison / `in` (non-associative) → `+ -` → `* / %` →
  unary `-` → primary (literal, column, `fn(args)`, `( expr )`).
  Literals: `'string'` (no escapes; backslash rejected), ints, floats
  (`1.`, `.5`, `1e3`), `true`/`false`.
  Functions: `len`, `day`, `month`, `year`, `round(x[, digits])`.

## Types

`int`, `float` (both "numeric"), `str`, `bool`, `timestamp`.

* Required columns: `timestamp`→timestamp, `price`/`quantity`→float, others str.
* Extra columns are inferred over all non-empty values: int → float → bool
  (`true`/`false`) → timestamp (must contain a time part) → str.
* Empty cells in non-string columns are null. Nulls propagate through arithmetic
  and transforms, make comparisons false, are skipped by aggregates (except
  `count(*)`), and rows with a null `timestamp` are dropped from windowing.
* Rules: arithmetic numeric-only (int op int → int, `/` → float); comparisons
  numeric↔numeric, str↔str, timestamp↔timestamp, bool↔bool (`==`/`!=` only);
  `&|!` bool-only; `in` only `'literal' in <str column>`; `filter` needs bool;
  `len` str; `day/month/year` timestamp (evaluated in `--tz`); `round` numeric
  with int digits; aggregates numeric only except `count(*)`; `window` needs
  `timestamp` to be a timestamp column. Unknown columns are type errors.

## Execution & output

* Timestamps parsed with `--timestamp-format` (strptime) or ISO 8601
  (`fromisoformat`, `Z` accepted); naive values localized to `--tz`, stored as
  aware UTC datetimes.
* Windows: tumbling, epoch-aligned, floor((t - epoch)/width) computed in integer
  microseconds. Only non-empty windows are emitted.
* Aggregates: sum (sequential), average = sum/n, median (mean of middle two
  when even), population var (two-pass) and std = sqrt(var), min, max, count.
  No input → `count` 0, others `null`. Any non-finite result → exit 4.
* `round`: half away from zero via `Decimal(repr(x))` + `ROUND_HALF_UP`.
* Row ordering: `window_start`, then group key tuple (nulls first, numbers
  numeric, strings by code point, timestamps chronological).
  Key order: `window_start`, `window_end`, group keys, aliases sorted.
* Timestamps rendered `YYYY-MM-DDTHH:MM:SS[.ffffff]Z`. `-0.0` normalized to `0.0`.
  JSON written with `indent=2`, `ensure_ascii=False`, trailing newline.
