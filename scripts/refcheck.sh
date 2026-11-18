#!/usr/bin/env bash
# Reference-solution sanity: the grader (PyPI-only eval env, hidden tests) must pass each checkpoint's reference.
set -uo pipefail
HERE=$(realpath "$(dirname "$0")"); H="$HERE/slop-code-bench"; P="$HERE/scb-problems"
PROB=${1:-file_backup}; OUT="$HERE/runs/refcheck/$PROB"; SNAP=$(mktemp -d)
export SCBENCH_PROBLEMS_PATH="$P"; unset ANTHROPIC_API_KEY CLAUDE_CODE_OAUTH_TOKEN ANTHROPIC_AUTH_TOKEN
"$HERE/net_up.sh"; mkdir -p "$OUT"; cd "$H"
for d in "$P/$PROB"/solutions/checkpoint_*; do
  c=$(basename "$d"); rm -rf "$SNAP/$c"; cp -r "$d" "$SNAP/$c"; rm -rf "$SNAP/$c/tests" "$SNAP/$c/.evaluation_tests"
  echo "== $c $(date -Iseconds)"
  uv run slop-code --quiet eval-snapshot "$SNAP/$c" -p "$PROB" -c "$c" \
     -e configs/environments/docker-python3.12-uv-parnas-eval.yaml -o "$OUT/$c" --json > "$OUT/$c.json" 2> "$OUT/$c.err"
  echo "rc=$?"
done
rm -rf "$SNAP"; echo REFCHECK_DONE
