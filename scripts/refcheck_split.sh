#!/usr/bin/env bash
# Multi-file probe: reference moved into package refpkg/, entry file is a shim that imports it.
# Catches graders that only copy the entry file (meshctl defect, 2026-11-10). Usage: refcheck_split.sh <prob> <ckpt>...
set -uo pipefail
HERE=$(realpath "$(dirname "$0")"); H="$HERE/slop-code-bench"; P="$HERE/scb-problems"
PROB=$1; shift; OUT="$HERE/runs/refcheck/${PROB}_split"; SNAP=$(mktemp -d)
ENTRY=$(awk '/^entry_file:/{print $2}' "$P/$PROB/config.yaml")
export SCBENCH_PROBLEMS_PATH="$P"; unset ANTHROPIC_API_KEY CLAUDE_CODE_OAUTH_TOKEN ANTHROPIC_AUTH_TOKEN
"$HERE/net_up.sh"; mkdir -p "$OUT"; cd "$H"
for c in "$@"; do
  d="$P/$PROB/solutions/$c"; rm -rf "$SNAP/$c"; cp -r "$d" "$SNAP/$c"; rm -rf "$SNAP/$c/tests" "$SNAP/$c/.evaluation_tests"
  mkdir "$SNAP/$c/refpkg"; touch "$SNAP/$c/refpkg/__init__.py"; mv "$SNAP/$c/$ENTRY.py" "$SNAP/$c/refpkg/impl.py"
  printf 'import runpy\nrunpy.run_module("refpkg.impl", run_name="__main__", alter_sys=True)\n' > "$SNAP/$c/$ENTRY.py"
  echo "== $c split $(date -Iseconds)"; ls -R "$SNAP/$c" | head
  uv run slop-code --quiet eval-snapshot "$SNAP/$c" -p "$PROB" -c "$c" \
     -e configs/environments/docker-python3.12-uv-parnas-eval.yaml -o "$OUT/$c" --json > "$OUT/$c.json" 2> "$OUT/$c.err"
  echo "rc=$?"
done
rm -rf "$SNAP"; echo SPLIT_DONE
