# MTL — design plan

`mtl.py` is a thin entry point. The logic lives in the `mtl_engine` package,
where each module has one job.

| Module | Responsibility |
|---|---|
| `errors.py` | Error hierarchy: `bad_dsl`=1, `type_error`=2, `bad_io`=3, `runtime_error`=4 |
| `dtypes.py` | Value types (`int`, `float`, `string`, `bool`, `timestamp`) and helpers |
| `timeutil.py` | Timezone resolution, timestamp parsing (ISO 8601 / strptime), UTC formatting, epoch math |
| `csv_loader.py` | Reads the CSV, validates the header, types each column, converts the values |
| `lexer.py` | Tokenises the DSL: comments, strings, numbers, durations, operators, and joining logical lines |
| `ast_nodes.py` | AST node classes for expressions and statements |
| `parser.py` | Recursive-descent parser that produces a `Program` and enforces statement cardinality |
| `functions.py` | Scalar transforms (`len`, `day`, `month`, `year`, `round`): signatures and implementations |
| `typecheck.py` | Static type checking of the whole pipeline against the CSV schema |
| `evaluator.py` | Evaluates expressions for each row (SQL-like null propagation, runtime errors) |
| `aggregates.py` | Aggregate functions (`sum`, `average`, `median`, `count`, `std`, `var`, `min`, `max`) |
| `pipeline.py` | Runs the program: row ops, then bucketing by window and group, then aggregation |
| `output.py` | Applies the normalization rules (row order, key order) and writes deterministic JSON |
| `cli.py` | Parses arguments and runs the stages; maps errors to `ERROR:<TYPE>:<msg>` and exit codes |

## Flow
1. Parse the CLI arguments (an argument error is `bad_io`) and resolve `--tz`.
2. Read the DSL from a file or STDIN (`bad_io`), then lex and parse it (`bad_dsl`).
3. Load the CSV (`bad_io` for structure problems, `type_error` for values that don't match the column type).
4. Type-check the program statically. This catches errors even when the CSV has no rows.
5. Execute and serialize. Division by zero or NaN/Inf raises `runtime_error`.

## Key decisions
- **Column types.** `timestamp` is a timestamp. `price` and `quantity` are floats. `location`, `item`, `unit`
  and `category` are strings. For an extra column, the type is inferred from its non-empty values, in this
  order: int, then float, then bool (`true`/`false`), and string otherwise. An empty numeric cell becomes null.
- **Expressions.** Literals, column refs, `!`, `&`, `|` (`!` > `&` > `|`), comparisons (not chainable),
  `'lit' in col`, arithmetic `+ - * / %` (numeric only) and transform calls. Comparisons follow
  the type rules: numeric with numeric, string with string, timestamp with timestamp, and bool with
  bool for `==`/`!=` only.
- **`apply`** accepts any scalar expression, so a transform call or arithmetic both work. It defines or
  overrides a column for the statements after it.
- **Statement order.** `filter` and `apply` run in file order. `group_by`, `window` and `aggregate`
  are declarations that are resolved against the schema after all `apply` statements.
- **Lines.** A statement continues onto the next line when brackets are open, the line ends with `,`,
  the next line starts with `,`, or the line is just the word `aggregate`.
- **Nulls.** Null values propagate through expressions. `filter` keeps a row only when the predicate is `true`.
  Aggregates ignore nulls. `count(*)` counts rows.
- **Windows.** Tumbling windows aligned to the epoch, computed in integer microseconds UTC. Only
  non-empty windows are emitted. `day`, `month` and `year` use the UTC timestamp.
- **`round`.** Rounds half away from zero, using `Decimal` on the shortest repr of the float.
- **Output.** `json.dumps(indent=2)`. Key order and row order follow the spec. Only finite numbers are emitted.
