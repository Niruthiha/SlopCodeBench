#!/usr/bin/env bash
# Rerun ("same instruction at every checkpoint"): PROBS x CONDS, seed 1, one Docker job at a time.
# Before each cell: verify_setup.sh (must pass). After each cell: failure_summary, check_cell (isolation), trace_summary.
# Stops on the first failed verifier or isolation check. Cells with a finished run dir (result.json) are skipped,
# so the script can be relaunched after an interruption. Launch detached:
#   setsid nohup ./rerun_every.sh > runs/logs/rerun_every.log 2>&1 < /dev/null &
cd "$(dirname "$0")"
export PATH=$HOME/.local/bin:$PATH
PROBS=${PROBS:-eve_industry metric_transform_lang recli sith}
CONDS=${CONDS:-c2_modular_every c3_parnas_every c4_performance_every}
mkdir -p runs/logs
for PROB in $PROBS; do
  export PROB
  for C in $CONDS; do
    done_dir=$(ls -d runs/$PROB/${C}_s1_* 2>/dev/null | while read d; do [ -f "$d/result.json" ] && echo "$d"; done | tail -1)
    [ -n "$done_dir" ] && { echo "$(date -Iseconds) SKIP $PROB $C (finished: $done_dir)"; continue; }
    TS=$(date +%Y%m%dT%H%M)
    V=runs/logs/verify_before_${PROB}_${C}_$TS.log
    ./verify_setup.sh > $V 2>&1 || { echo "$(date -Iseconds) VERIFIER FAIL before $PROB $C (see $V)"; exit 1; }
    L=runs/logs/cell_${PROB}_${C}_$TS.log
    echo "$(date -Iseconds) START $PROB $C"
    ./run_cell.sh $PROB $C 1 > $L 2>&1; crc=$?
    R=$(ls -d runs/$PROB/${C}_s1_* | tail -1)
    cp $V "$R/verify_before.log"; cp $L "$R/run_cell.log"
    git -C slop-code-bench rev-parse HEAD > "$R/harness_commit.txt"
    python3 failure_summary.py "$R" > /dev/null 2>&1 || echo "failure_summary failed for $R"
    python3 trace_summary.py "$R" > /dev/null 2>&1 || echo "trace_summary failed for $R"
    python3 check_cell.py "$R" > "$R/check_cell.txt" 2>&1; rc=$?
    echo "$(date -Iseconds) END $PROB $C $R run rc=$crc check rc=$rc $(python3 -c "import json;t=json.load(open('$R/trace_summary.json'))['total'];print(t)" 2>/dev/null)"
    [ $rc = 0 ] || { echo "STOP: $PROB $C failed isolation check (run rc=$crc), see $R/check_cell.txt"; exit 1; }
  done
done
echo "$(date -Iseconds) RERUN DONE"
