# recli: qualitative trace analysis (c1 default / c2 modular / c3 parnas, seed 1, 8 checkpoints)

Runs: `runs/recli/c1_default_s1_20261110T2051`, `c2_modular_s1_20261110T2205`, `c3_parnas_s1_20261110T2349`. Step ids `[ck.step]` refer to `analysis/qual/digests/recli__<cond>.md`. Numbers come from `analysis/compare/data.json` and the per-checkpoint `evaluation.json`.

## Summary

- **Final outcome.** All three cells end close together: 215 / 227 / 241 failed test instances summed over checkpoints, and 164 / 167 / 164 of 255 tests passing at ck8. 81 ck8 failures are common to all three. With one common skip, 82 tests do not pass in any cell. Unique ck8 failures: c1 7, c2 3, c3 4.
- **No benchmark defects found.** The reference solution passes 255/255 at every checkpoint (`runs/refcheck/recli`, `recli_split`), and `BENCHMARK_DEFECTS.md` has no recli entry. Most common failures still come from spec text that admits a reading the hidden tests reject. We class these as interpretation, not defects: the first-run success message, the global system-requirement gate, compose version parsing, the `options` schema, and the ck7 migrations location.
- **The ck8 drop is mostly self-inflicted and the same in all three cells.** About 25–30 ck8 failures per cell are earlier-checkpoint tests that passed until ck8 (c1 30, c2 25, c3 26). All three put a first-run "Success: … set up" line and a docker/compose check in front of every command. The hidden tests use a fresh root and have no running daemon.
- **c2 and c3 saw this mechanism in their own suites and changed the fixtures, not the behaviour.** c2: at [8.40] dozens of its own tests fail; at [8.46–8.51] it adds a fake runtime and pre-initialises the root. c3: at [8.38] its own assertion shows `+ Success: AppCtl has been set up successfully.` before `usage:`; at [8.40] it adds `prime_root`. c1 had no suite. It saw the message in its own manual output [8.24, 8.29] and did not comment on it.
- **ck1 designs.** c1 wrote one file (`appctl.py`, 1,318 lines [1.3]), which grew to 4,443 lines. c2 wrote 36 files in `appctl_cli/` + `commands/` [1.2–1.15], growing to 57. c3 wrote `DESIGN.md` [1.2] with 15 "decision → module → secret" rows, growing to 51 files. c3's `DESIGN.md` was not in the workspace from ck2 on. The harness did not carry `.md` files forward (c2's `migrations/README.md` from ck7 is also missing at ck8).
- **Navigation was the same in kind in all three.** Each checkpoint opens with `ls`/`find` and then bulk `cat` of most of the code. c2 and c3 reread nearly every module at ck8 ([8.3–8.17] in c2, [8.2–8.20] in c3). c1 read sliced ranges of its one file. Steps before the first edit (ck2–ck8): c1 8, 6, 10, 8, 16, 18, 18; c2 9, 10, 6, 8, 11, 9, 20; c3 10, 10, 9, 10, 13, 13, 21.
- **How new features landed.** In c2 and c3, extensions mostly arrived as new modules plus small edits to `app.py` and a central registry file. c1 inserted new sections into `appctl.py` with assert-guarded string replacement. One hub file grew at every checkpoint in each cell: c2 `upgrade.py` 875 lines and `commands/cli.py` 538; c3 `catalog.py` 493 and `messages.py` 394, the latter holding every message.
- **Verification.** c2 and c3 wrote unit/e2e suites at every checkpoint, ending at 208 and 217 own tests. c1 wrote none and relied on ad-hoc runs, fake `docker`/`ssh` scripts, a local HTTP server and a before/after output diff [2.22, 8.35]. All three declared full completion at ck8 while 87–90 hidden tests failed.
- **Condition-specific failures are few and come from local slips.** c2: an append-to-`{}` config bug [`config_loader.py` l.89–110] causes 2 unique alias failures. c3: `Debug (bootstrap):` labels and `--color` rejecting a value cause 4. c1: its hand-written YAML subset parser fails array merging and two ck1 error paths, 7 in total. No agent cites its ck1 instruction after ck1.

## c1

**Navigation.** Every checkpoint re-oriented by listing, then reading `appctl.py` whole or in `sed -n` ranges after grepping `^def|^class`: [2.1–2.3], [3.2–3.5], [4.2–4.8], [5.2–5.6], [6.2–6.15], [7.2–7.15], [8.2–8.17]. At [2.6] it decompiled the `__pycache__` `.pyc` to list function names. The first edit came at step 8, 6, 10, 8, 16, 18 and 18 for ck2–ck8; the pre-edit phase lengthened as the file grew past 3,000 lines (ck6+).

**Search.** grep for anchors (`GLOBAL_PARAMS` [2.7], section headers [2.14]), then `Read` with offsets [2.15]. The same file was reread at every checkpoint. There were no dead-end searches. [8.34] searched the whole filesystem for leftover spec/test `.md` files (`find / -name "*.md" -newer …`) and found none.

**Implementation.** ck1 was one file with a WP-CLI-style command set (cache, cli, config, db, help, option, plugin, post, site, theme, user). Extensions were inserted as delimited blocks: `/tmp/newcode.py` [4.9], the db section [5.7], the docker section [6.19], migrations/upgrade blocks [7.16–7.18]. Edits used python heredocs with assert-count replacements [2.17, 3.8–3.11]. At [2.5–2.6] PyYAML was not visible to system `python3`, so it uninstalled it from the venv and wrote a YAML subset parser inside `appctl.py` [2.11–2.13]. That parser needed anchor/merge fixes at [6.14–6.17]. The ck5 schema made `modified_on` NOT NULL [5.7–5.8]. ck7 used `APPCTL_MIGRATIONS_DIR` [7.26].

**Verification.** Manual runs, a fake `ssh` [2.20], fake `docker` scripts [6.21, 7.20–7.26, 8.24, 8.31], a local HTTP server and pty for self-update [8.29–8.32], and a regression diff against a saved copy [2.22, 8.35]. It caught its own slips: a `NameError` from `build_registry()` running before a new section [4.11 → 4.12], and the anchor parsing [6.14]. It wrote no unit tests (ck8 RESULT: "There's no test suite in the repo").

**Struggles.** The first-run line appears in its own output at [8.24] (`Success: appctl has been set up successfully.`) and is not remarked on. The [8.35] diff ran with fake docker on `PATH`, so the requirement gate stayed invisible to it. Unique failures: two ck1 error-path tests are masked by the gate, two ck2 YAML array-merge tests come from the hand parser, and there is one `cli info` key test.

## c2

**Navigation.** Bulk `cat` of modules plus the agent's own tests at every checkpoint: [2.1–2.5], [3.2–3.7] ("Small enough to read fully."), [4.2–4.5], [5.2–5.7], [6.2–6.10], [7.2–7.8], [8.3–8.19]. It ran the baseline suite before changing anything [3.9, 8.14]. The first edit came at step 9, 10, 6, 8, 11, 9 and 20.

**Search.** Mostly whole-module reads. There were targeted greps for `ROOT_DIR|sqlite|migration` [5.2] and for which `cli info` labels tests rely on [8.27]: "Only `runtime_config` is relied on, so I'm free to design the rest." `upgrade.py` was read twice in a row [8.7, 8.9].

**Implementation.** ck1: package `appctl_cli/` with arguments, registry, resolver, validator, formatter, output and others, plus one module per command [1.2–1.15]. Extensions were mostly new modules: `config_loader.py`/`remote.py` [2.10–2.12], `process.py`/`file_cache.py`/`extract.py` [4.6–4.9], `database.py` [5.8], `container.py` [6.11], `revertable.py`/`upgrade.py` (780 lines) [7.9–7.13], `system.py`/`self_update.py`/`startup.py` [8.20–8.29]. ck3 rewrote `output.py` and `formatter.py` wholesale [3.12–3.13]. ck8 rewrote `commands/cli.py` (536 lines) [8.31]. Each checkpoint also patched `app.py` [2.13, 3.16, 4.11, 5.9, 8.32]. PyYAML was a declared dependency (`requirements.txt`: `PyYAML>=6.0`).

**Verification.** unittest suites at every checkpoint: 45 tests [1.15], then 64, 92, 107, 125, 146 and 208 [8.61]. Fake `docker` on `PATH` for ck6–ck8 [6.15, 7.17, 8.46]. A clock-based stdin timing check [3.20–3.21]. ck5 added no tests [5.11].

**Struggles.** At [8.40] its own suite failed broadly after ck8 wiring (`test_table_widths_and_order`, `test_defaults_applied`, …). The agent marked some commands machine-readable [8.43–8.45], then added `tests/helpers.py` with a fake runtime and an `initialize()` that pre-runs setup [8.46–8.51]. It explained the remaining failures as "Fixture artifacts, as expected." Interpretation: the same first-run and gate behaviour is what breaks ~34 (FIRSTRUN) and ~22 (SYSREQ) hidden ck8 tests in this cell. [8.58–8.59] wrote a memory note about the Docker environment. Unique failures: `test_unknown_alias_error` and `test_all_no_aliases_error` come from `ensure_global_config` appending `locale: en_US` to a file containing `{}`. The result is a YAML parse error ("expected '<document start>', but found '<block mapping start>'").

## c3

**Navigation.** Same bulk-read pattern: [2.1–2.6], [3.2–3.9], [4.2–4.8], [5.2–5.9], [6.2–6.12], [7.2–7.12], [8.2–8.20]. At ck8 it read 34 module files across 11 `cat` calls before writing. It also read `.pytest_cache` node ids and `lastfailed` [3.2, 5.2, 6.2, 7.2]. The first edit came at step 10, 10, 9, 10, 13, 13 and 21. The module docstrings carry the "Secret:" lines, so the design was visible in the code even though `DESIGN.md` was gone. At [4.2] the agent read `"See DESIGN.md."` in `__init__.py` and did not look for the file.

**Search.** Whole-file `cat`, then targeted greps (`custom-compose|skip-tty|projects_path` [6.10], `packages_dir` [7.12], `needs_upgrade` [8.52]). It re-read persisted tool-result files [3.6–3.7, 7.8]. [4.7] ran the same filesystem `.md` search as c1 [8.34].

**Implementation.** ck1 `DESIGN.md` [1.2] lists 15 decisions, each with a one-sentence secret, for example:
> | 14 | Which commands exist and what they do | `catalog.py` | The set of built-in commands, their synopses, aliases, defaults, descriptions and handler behavior.
> | 10 | User-facing message wording | `messages.py` | The exact text of every error/notice and the program's display name.

It also states: "No module hands its internal data structures to another." Later checkpoints followed the same pattern of a new module per concern: `config_files`/`aliases`/`remote`/`yaml_lite` [2.10–2.21], `logfile`/`values` [3.10, 3.16], `process`/`file_cache`/`extractor` [4.9–4.13], `db` [5.10], `containers`/`container_commands` [6.14, 6.18], `revertable`/`semver`/`migrations`/`compose_tool`/`upgrade` [7.13–7.22], `system`/`releases`/`startup`/`completions`/`cli_commands` [8.21–8.30]. Every checkpoint still edited `catalog.py` and appended to `messages.py` [4.12, 5.11, 6.13, 7.18, 8.22]. ck8 moved the `cli` section out of `catalog.py` into `cli_commands.py` [8.31]. `errors.py` was rewritten with `cat >` [3.12]. Like c1, c3 wrote a fallback YAML parser `yaml_lite.py` because system `python3` lacked PyYAML [2.8–2.16], but it also declared PyYAML [2.9].

**Verification.** pytest at every checkpoint: 24/25 tests [1.11–1.13], then 45, 58, 79, 86, 100, 138 and 217 [8.54]. Fake `docker` driven by state files [6.20, 7.26, 8.36]. It caught its own wrong expected strings [3.24, 4.23].

**Struggles.** [8.37–8.38]: its own tests failed with `+ Success: AppCtl has been set up successfully.` prepended to `usage:` output. [8.40] added `prime_root` "so that the next invocation is not a first run", and [8.43] updated the upgrade tests "to the new first-run semantics". Unique failures: `Debug (bootstrap):` prefixes where tests expect `Debug:` (two ck2/ck3 tests), `--color` rejecting a value, and a per-invocation log separator.

## Cross-condition comparison

| Question | c1 | c2 | c3 |
|---|---|---|---|
| Navigation | grep anchors + `sed -n`/Read ranges of one file; 6–18 steps to first edit | bulk `cat` of modules + own tests; 6–20 | bulk `cat` of modules + pytest cache; 9–21 |
| Search | grep → offset reads; `.pyc` decompile [2.6]; fs `.md` hunt [8.34] | whole-module reads, few greps; test-reliance grep [8.27] | whole-module reads; fs `.md` hunt [4.7] |
| Implementation | inserted blocks in one 4,443-line file; own YAML parser | new modules per feature; `app.py` and `cli.py`/`upgrade.py` hubs | new modules per concern; `catalog.py`/`messages.py` hubs; own YAML fallback |
| Verification | ad-hoc, fakes, output diff; no tests | unittest, 208 tests | pytest, 217 tests |
| Struggles | first-run/gate unnoticed | own tests broke at ck8 → fixtures adapted | own tests broke at ck8 → fixtures adapted |
| ck8 failed / unique | 90 / 7 | 87 / 3 | 90 / 4 |

The cells behaved the same in the parts that decided the score. All three read the ck8 spec as requiring a first-run success line and a container-runtime check before most commands, and all three applied them globally. All three made `modified_on` NOT NULL, did not use `<root>/migrations/db/` at ck7, and joined the SSH pre-command with `;` rather than `&&`. The visible differences are size and style: one file vs packages, no tests vs growing suites, and c3's table of secrets at ck1. c3's docstrings kept the "Secret:" vocabulary through ck8 (e.g. `app.py` "Secret: the order in which the stages run…" at [4.2]). No trace after ck1 cites either the modular or the information-hiding instruction, so no later behaviour is attributable to the prompt.

## Failures traced to behaviour

Each line gives the cluster, approximate ck8 test counts (c1/c2/c3), and the kind of cause.

- **First-run message on stdout (16/34/17). Spec reading, shared.** The ck8 spec says a success message must be printed on first run. Every hidden test starts from a fresh root, so every call is a first run. The reference prints its message only for `help`. c2 and c3 saw this in their own suites and adapted the fixtures ([8.46–8.51] / [8.40]). c1 saw it in manual output [8.24].
- **Global system-requirement gate (35/22/30). Spec reading, shared.** The gate runs before argument validation, and the eval environment has a docker client but no daemon. This masks ck1–ck5 usage and error tests. c2 also enforced compose ≥2.27.0 against the installed 2.26.1.
- **Unparseable compose version (12/3/12). Assumption.** The conftest fake `docker` prints nothing; c1 and c3 treat that as an error.
- **`options.modified_on` NOT NULL (9/10/10). Assumption under an unspecified schema.** Tests insert `(key, value)` only.
- **Migrations location and ck6 docker call-shape (~5–6 each, all).** The spec leaves the convention open; the tests hard-code `<root>/migrations/db/*.py`. The ck6 call-shape tests see only the requirement probes in the docker log.
- **Never-attempted vs. slips.** No major spec area was skipped by any cell. The unique failures are local slips: c1's YAML parser; c2's append-to-`{}`; c3's debug labels and `--color` handling.
- **Persistent from ck1 (all three).** `test_required_associative_empty_value_is_rejected` and `test_required_associative_missing_error` fail from ck1 to ck8 in every cell.

## Caveats

- One seed per cell. The differences above are single observations, not effects.
- Category counts come from a regex classifier over failure messages written for this analysis. The clusters overlap and the counts are approximate.
- The digests truncate long tool calls; some step contents were checked against snapshots, not the raw `stdout.jsonl`.
- The harness dropped `.md` files between checkpoints. That removed c3's `DESIGN.md` and c2's migrations README, so it is not known whether the agents would have reread their own docs.
- The "spec reading" labels are interpretation. The reference passes, so these are not benchmark defects, but the spec text supports the agents' readings in several clusters.
