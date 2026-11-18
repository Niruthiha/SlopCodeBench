#!/usr/bin/env python3
"""Per-cell failure summary, written BEFORE any trace deletion. Usage: failure_summary.py <run_dir>
Writes <run_dir>/failure_summary.json + .md: per checkpoint the failed tests by group (Core/Functionality/Error/Regression),
the first line of each failure reason, and the agent's final message."""
import json, sys, os, glob
run = sys.argv[1].rstrip('/'); prob = glob.glob(os.path.join(run, '*/checkpoint_1'))[0].rsplit('/', 1)[0]
out = {'run': run, 'checkpoints': {}}
for cdir in sorted(glob.glob(os.path.join(prob, 'checkpoint_*'))):
    ck = os.path.basename(cdir); evp = os.path.join(cdir, 'evaluation.json')
    if not os.path.exists(evp): out['checkpoints'][ck] = {'pass_counts': None, 'total_counts': None, 'failed': {}, 'agent_final_message': '(no evaluation: run stopped)'}; continue
    ev = json.load(open(evp))
    reasons = {}
    rp = os.path.join(cdir, 'evaluation/report.json')
    if os.path.exists(rp):
        for t in json.load(open(rp)).get('tests', []):
            if t.get('outcome') != 'passed':
                lr = (t.get('call') or t.get('setup') or {}).get('longrepr') or (t.get('call') or {}).get('crash', {}).get('message') or ''
                lines = [l.strip() for l in str(lr).splitlines() if l.strip().startswith('E ')] or [str(lr).strip().splitlines()[-1] if lr else '']
                reasons[t['nodeid'].split('::')[-1]] = lines[0][:300]
    final = ''
    so = os.path.join(cdir, 'agent/stdout.jsonl')
    if os.path.exists(so):
        for x in open(so):
            try: m = json.loads(x)
            except Exception: continue
            if m.get('type') == 'result': final = str(m.get('result') or '')
    out['checkpoints'][ck] = {
        'pass_counts': ev.get('pass_counts'), 'total_counts': ev.get('total_counts'),
        'failed': {g: [{'test': n, 'reason': reasons.get(n, '')} for n in v['failed']] for g, v in ev['tests'].items() if v['failed']},
        'agent_final_message': final}
json.dump(out, open(os.path.join(run, 'failure_summary.json'), 'w'), indent=1)
with open(os.path.join(run, 'failure_summary.md'), 'w') as f:
    f.write(f'# Failure summary: {run}\n')
    for ck, c in out['checkpoints'].items():
        f.write(f'\n## {ck}\npass {c["pass_counts"]} / total {c["total_counts"]}\n')
        for g, L in c['failed'].items():
            f.write(f'\n**{g}** ({len(L)} failed)\n'); [f.write(f'- `{t["test"]}`: {t["reason"]}\n') for t in L]
        f.write(f'\n**Agent final message:** {c["agent_final_message"][:1500]}\n')
print('wrote', os.path.join(run, 'failure_summary.md'))
