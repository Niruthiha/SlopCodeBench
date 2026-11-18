# MTL design

Single file `mtl.py`, standard library only (`tzdata` in requirements.txt is a
fallback IANA database for systems without `/usr/share/zoneinfo`).

## Pipeline

1. **CLI**: a tiny hand-written option parser. Usage errors are reported as
   `bad_io` (exit 3). Start-up is kept minimal: there is no `re`, `argparse`,
   `csv.py` or `json` import. The C modules `_csv` and `_json` are used
   directly. `array`, `decimal` and `zoneinfo` are imported only when
   needed.
2. **Read DSL** (file or STDIN). On failure: `bad_io`.
3. **Parse DSL**: a hand-written scanner plus a recursive-descent parser.
   - Newlines end statements, except inside `()`/`[]`, after a `,`, before a
     line that starts with `,`, or right after `aggregate`, so an
     `aggregate` list can span several lines. `#` starts a comment that runs
     to the end of the line.
   - Expression precedence, lowest first: `|` < `&` < `!` < comparison/`in`
     (non-associative) < `+ -` < `* /` < unary `-` < primary.
   - Structural rules (exactly one `aggregate`, at most one `group_by` or
     `window`, unique aliases, valid duration) → `bad_dsl` (exit 1).
4. **Open CSV**, read the header, and check the required columns (`bad_io`).
   Extra columns named in the DSL get their type from one pre-scan, tried in
   this order: int → float → bool → timestamp → string.
5. **Type-check and compile**. The statements are walked in order with a type
   environment (`int`, `float`, `str`, `ts`, `bool`). Any type violation is a
   `type_error` (exit 2). An unknown column is also a `type_error`.
   The walk generates the Python source of one specialised row-loop function
   and runs it with `exec`. This avoids interpreting the AST per row:
   - A raw CSV field is converted only when it is first needed, so rows
     dropped by an earlier filter are never parsed further.
   - Filters become `if not (...): continue`. `&`/`|`/`!` map to
     `and`/`or`/`not`.
   - Timestamps become aware UTC `datetime`s (`fromisoformat` or `strptime`,
     with `--tz` attached to naive values). `day`/`month`/`year` are UTC
     fields. The window index is `ts.timestamp() // width`.
6. **Aggregation state** is one bucket per (window, group key). The bucket is
   a dict entry holding a list: `[count, buf_col1, buf_col2, ...]`. Each
   numeric column used by an aggregate gets one value buffer (`array('d')`
   for floats, `list` for ints), shared by all aggregates on that column. Per
   row, the work is a dict lookup plus a few C-level `append` calls.
   - Columns that need only sum/avg/min/max (and int var/std) are *folded*.
     The rows are processed in chunks via `islice`, so the per-row loop has no
     counter. After each chunk, any buffer with ≥4096 values is reduced into
     `(fsum parts, min, max)` for floats, or exact `(sum, sumsq, min, max)`
     for ints, then cleared. Memory stays bounded. The chunk size grows with
     the bucket count, so total fold work stays linear.
   - Columns that need a median, or a float std/var, keep all their values
     (8 bytes per float).
7. **Finalisation**:
   - Sums use `math.fsum`, so they are correctly rounded.
   - Mean = sum / n.
   - var is exact: `(n·ΣX² − (ΣX)²)/n²` in integers. For floats, X is the
     value scaled to a common 2^-k, since floats are dyadic rationals. This
     is a single pass with rescaling.
   - std is the correctly rounded sqrt of that exact fraction. Both match
     CPython's `statistics.pvariance`/`pstdev` bit for bit.
   - Median sorts the values. An even n gives the mean of the two middle
     values.
   - An empty global result gives `count` → 0 and the others → `null`.
   - Any NaN/Inf in the output → `runtime_error` (exit 4).
8. **Output**: buckets are sorted by key tuple `(window, g1, g2, ...)`, using
   native ordering for each type. Each bucket is popped as it is serialised
   directly to a JSON fragment, in the same layout as `json.dumps`. Object keys go `window_start`,
   `window_end`, group keys, then aliases sorted. Timestamps are written as
   `YYYY-MM-DDTHH:MM:SS[.ffffff]Z`. The JSON is built fully before the
   output is opened, so an error never leaves a partial file.

## Error mapping

| condition | type / exit |
|---|---|
| tokenizer/parser/structure errors, unknown function, bad arity | `bad_dsl` / 1 |
| unknown column, type mismatch, invalid `in`, non-numeric aggregate, unparsable typed CSV value | `type_error` / 2 |
| missing/unreadable files, bad header, malformed rows, bad CLI args/tz | `bad_io` / 3 |
| division by zero, overflow, NaN/Inf result | `runtime_error` / 4 |

## Semantics choices for underspecified points

- `apply` accepts any scalar expression (arithmetic `+ - * /` included), and
  later statements see its column. Overriding a column replaces it and its
  type.
- `round` rounds half away from zero on the shortest decimal repr
  (`Decimal(repr(x))`), so `round(2.675, 2)` → 2.68. An exact float fast
  path is used when the value is not near a .5 tie. Digits are 0 by default
  and may be negative. Int input gives int output.
- `count(col)` needs a numeric column and equals the row count. Empty
  buckets are never emitted, except the global object.
- Statement order matters for `filter`/`apply`. `group_by`, `window` and
  `aggregate` use the final column environment.
