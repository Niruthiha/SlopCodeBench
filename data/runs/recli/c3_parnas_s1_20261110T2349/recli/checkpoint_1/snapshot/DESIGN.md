# appctl — design by information hiding

Each entry below is a design decision that is hard to make or likely to
change. Each one lives in exactly one module (under `appctl_core/`), and that
module's *secret* is the decision. Other modules depend only on the module's
interface, which stays valid if the secret changes. No module hands its
internal data structures to another: interfaces exchange strings, numbers,
plain lists/dicts built fresh for the caller, or opaque objects with methods.

| # | Decision (likely to change) | Module | Secret (one sentence) | Interface |
|---|-----------------------------|--------|-----------------------|-----------|
| 1 | Lexical syntax of a command line | `tokens.py` | How raw argv strings are split into option tokens (`--k=v`, `--flag`) and positional words, including the `--` terminator. | `lex(argv)`, `positional(text)`, `Token.is_option() / .name / .value / .text` |
| 2 | Convenience argv rewrites | `rewrites.py` | Which shortcut spellings (`<cmd> --help`, `--version`) are rewritten into canonical commands, and how. | `apply(tokens) -> tokens` |
| 3 | Global runtime parameters and strict mode | `runtime_config.py` | Which global parameters exist, which env var turns on strict mode, and which argv positions may supply globals. | `extract(tokens, env) -> (RuntimeConfig, tokens)`; `RuntimeConfig` getters |
| 4 | Synopsis grammar | `synopsis.py` | The textual grammar of synopsis strings and how each part is classified (positional, keyed, flag, negatable flag, generic, malformed, optional, repeating). | `Synopsis(text)` query methods + `interpret(name, value)` |
| 5 | Validation policy and default application | `binding.py` | The order in which argument checks run, which conditions are errors, how errors are batched, and when defaults are filled in. | `bind(path, synopsis, defaults, words, options) -> BoundArguments`; raises `MissingPositional` / `CliError` |
| 6 | Similarity algorithm for suggestions | `suggest.py` | The distance metric, threshold and tie-breaking that pick a single deterministic "Did you mean" candidate. | `suggest(target, candidates) -> str or None` |
| 7 | Curated synonym table | `synonyms.py` | Which common command-name variants map to which canonical names. | `synonym_for(word) -> str or None` |
| 8 | Command storage, alias lookup and ordering | `command_tree.py` | How commands are stored as a tree, how names and aliases are matched, and how children are ordered. | `CommandTree.register/find/root`, `CommandNode` query methods |
| 9 | Command resolution algorithm | `dispatch.py` | How positional words are walked down the tree and when leftover words become arguments rather than unknown subcommands. | `resolve(tree, words) -> (node, remaining_words)` |
| 10 | User-facing message wording | `messages.py` | The exact text of every error/notice and the program's display name. | One function per message |
| 11 | Help and usage layout | `help_text.py` | How help listings, command help pages and usage lines are laid out (ordering, column alignment, sections). | `top_level_help`, `command_help`, `usage_line`, `composite_usage` |
| 12 | Output streams and prefixes | `output.py` | Which stream each kind of output goes to, its prefix, and how `--quiet` / `--debug` affect it. | `Output.error/warning/success/log/line/usage/debug` |
| 13 | Record rendering formats | `formatter.py` | How lists of records are rendered as table/json/csv/yaml/ids/count. | `render(records, fields, fmt) -> str`, `supported_formats()` |
| 14 | Which commands exist and what they do | `catalog.py` | The set of built-in commands, their synopses, aliases, defaults, descriptions and handler behavior. | `register_all(tree)` |
| 15 | Wiring of the pipeline | `app.py` | The order the stages run in (lex → rewrite → globals → resolve → bind → run) and how failures map to exit codes. | `run(argv, env, stdout, stderr) -> int` |

`errors.py` holds the shared exception types (`CliError`, `MissingPositional`)
that make up part of several interfaces. It has no secret of its own.

`appctl.py` is the executable entry point and just calls `app.run`.
