#!/usr/bin/env bash
# One Parnas-pilot cell: ONE problem x ONE condition x ONE seed, all checkpoints. Launch detached:
#   setsid nohup ./run_cell.sh file_backup c1_default 1 > runs/<log> 2>&1 < /dev/null &
set -euo pipefail
HERE=$(realpath "$(dirname "$0")"); H="$HERE/slop-code-bench"
PROBLEM=$1; COND=$2; SEED=${3:-1}
export SCB_CLAUDE_CREDS=${SCB_CLAUDE_CREDS:-/home/niruthi/.claude/.credentials.json}     # read-only mount; never read here
export SCB_EVAL_ENV="$H/configs/environments/docker-python3.12-uv-parnas-eval.yaml"
export SCBENCH_PROBLEMS_PATH="$HERE/scb-problems"
export SCB_PARNAS_RESET=1
unset ANTHROPIC_API_KEY CLAUDE_CODE_OAUTH_TOKEN ANTHROPIC_AUTH_TOKEN
"$HERE/net_up.sh"
cd "$H"
echo "cell start $(date -Iseconds) problem=$PROBLEM cond=$COND seed=$SEED harness=$(git rev-parse --short HEAD) dirty=$(git status --porcelain | wc -l)"
set +e
uv run slop-code run \
  --agent configs/agents/claude_code_parnas.yaml \
  --model anthropic/opus-5.5 \
  --environment configs/environments/docker-python3.12-uv-parnas-agent.yaml \
  --prompt "configs/prompts/parnas/$COND.jinja" \
  --problem "$PROBLEM" --no-live-progress --no-concurrent-evaluation \
  thinking=high "save_dir=$HERE/runs" \
  "save_template=$PROBLEM/${COND}_s${SEED}_\${now:%Y%m%dT%H%M}"
RC=$?
echo "cell end $(date -Iseconds) rc=$RC"
exit $RC
