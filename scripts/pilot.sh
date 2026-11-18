#!/usr/bin/env bash
# Pilot: <problem> (default file_backup) s1, c1..c4 sequentially (one Docker job at a time); stop on first failed isolation check.
# Harness P3b (fresh container per checkpoint + agent-doc deletion) = commit 8ed22d4.
cd "$(dirname "$0")"
PROB=${1:-file_backup}; export PROB
TS=$(date +%Y%m%dT%H%M)
for C in ${CONDS:-c1_default c2_modular c3_parnas c4_performance}; do
  V=runs/logs/verify_before_${PROB}_${C}_$TS.log
  ./verify_setup.sh > $V 2>&1 || { echo "VERIFIER FAIL before $C"; exit 1; }
  L=runs/logs/pilot_${PROB}_${C}_$TS.log
  ./run_cell.sh $PROB $C 1 > $L 2>&1; crc=$?
  R=$(ls -d runs/$PROB/${C}_s1_* | tail -1)
  cp $V "$R/verify_before.log"; cp $L "$R/run_cell.log"
  git -C slop-code-bench rev-parse HEAD > "$R/harness_commit.txt"
  python3 failure_summary.py "$R" > /dev/null 2>&1 || echo "failure_summary failed for $R"
  python3 check_cell.py "$R" > "$R/check_cell.txt" 2>&1; rc=$?; echo "$C $R run rc=$crc check rc=$rc"
  [ $rc = 0 ] || { echo "STOP: $C failed isolation check (run rc=$crc)"; exit 1; }
done
echo PILOT DONE
