#!/usr/bin/env bash
# Resume ONE existing cell from its first invalid checkpoint (harness --resume). Old invalid checkpoint dirs and
# reset records are MOVED to <run>/_invalid_attempt/ first (the harness would otherwise delete them).
set -euo pipefail
HERE=$(realpath "$(dirname "$0")"); H="$HERE/slop-code-bench"; RUN=$(realpath "$1"); CK=$2   # e.g. checkpoint_5
export SCB_CLAUDE_CREDS=${SCB_CLAUDE_CREDS:-/home/niruthi/.claude/.credentials.json}     # read-only mount; never read here
export SCB_EVAL_ENV="$H/configs/environments/docker-python3.12-uv-parnas-eval.yaml"
export SCBENCH_PROBLEMS_PATH="$HERE/scb-problems"
export SCB_PARNAS_RESET=1
unset ANTHROPIC_API_KEY CLAUDE_CODE_OAUTH_TOKEN ANTHROPIC_AUTH_TOKEN
P=$(dirname $(ls -d "$RUN"/*/checkpoint_1)); N=${CK#checkpoint_}; PREV=checkpoint_$((N-1))
mkdir -p "$RUN/_invalid_attempt"
[ -d "$P/$CK" ] && mv "$P/$CK" "$RUN/_invalid_attempt/"
[ -f "$P/parnas_reset_$CK.json" ] && mv "$P/parnas_reset_$CK.json" "$RUN/_invalid_attempt/"
cp "$RUN/checkpoint_results.jsonl" "$RUN/_invalid_attempt/" 2>/dev/null || true
python3 - "$P" "$CK" "$PREV" <<'PY'
import json,os,sys,datetime
P,CK,PREV=sys.argv[1:]; root=f'{P}/{PREV}/snapshot'; ls=[]
for d,ds,fs in os.walk(root):
    for x in fs: ls.append(os.path.relpath(os.path.join(d,x),root))
docs=[f for f in ls if f.lower().endswith(('.md','.rst','.markdown'))]
json.dump({'mode':'harness --resume (new process: new container, new temp agent home with settings.json only)',
  'resumed_checkpoint':CK,'restored_from':f'{PREV}/snapshot','snapshot_files':sorted(ls),'agent_docs_in_snapshot':docs,
  'time':datetime.datetime.now().isoformat()}, open(f'{P}/parnas_resume_{CK}.json','w'), indent=1)
PY
"$HERE/net_up.sh"
cd "$H"
echo "resume start $(date -Iseconds) run=$RUN from=$CK harness=$(git rev-parse --short HEAD) dirty=$(git status --porcelain | wc -l)"
set +e
uv run slop-code run --resume "$RUN" --no-live-progress --no-concurrent-evaluation
RC=$?; echo "resume end $(date -Iseconds) rc=$RC"; exit $RC
