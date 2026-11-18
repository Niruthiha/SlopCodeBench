#!/usr/bin/env python3
"""Per cell x checkpoint: steps before first file edit, Read/Grep/Glob/Bash-search counts, distinct files edited, re-reads."""
import json, glob, re, sys, csv
dec = json.JSONDecoder()
def objs(p):
    for x in open(p):
        s = x.strip(); q = 0
        while q < len(s) and s[q] == '{':
            o, q = dec.raw_decode(s, q); yield o
            while q < len(s) and s[q].isspace(): q += 1
RUNS = {t: sorted(glob.glob(f'runs/{t}/c[123]_*_s1_*')) for t in ['sith', 'eve_industry', 'recli', 'metric_transform_lang']}
SRCH = re.compile(r'(^|[;&|]\s*|\s)(grep|rg|find|ls|tree|cat|head|sed -n|wc)\b')
rows = []
for t, runs in RUNS.items():
    for r in runs:
        c = r.split('/')[-1][:2]
        for ck in sorted(glob.glob(f'{r}/{t}/checkpoint_*'), key=lambda p: int(p.rsplit('_', 1)[1])):
            k = int(ck.rsplit('_', 1)[1]); calls = []
            for m in objs(f'{ck}/agent/stdout.jsonl'):
                if m.get('type') == 'assistant':
                    calls += [(x['name'], x.get('input', {})) for x in m['message'].get('content', []) if x.get('type') == 'tool_use']
            first = next((i for i, (n, a) in enumerate(calls) if n in ('Edit', 'Write', 'MultiEdit')), None)
            reads = [a.get('file_path') for n, a in calls if n == 'Read']
            edited = {a.get('file_path') for n, a in calls if n in ('Edit', 'Write', 'MultiEdit')}
            bsearch = sum(1 for n, a in calls if n == 'Bash' and SRCH.search(a.get('command', '')))
            rows.append(dict(task=t, cond=c, ck=k, calls=len(calls), pre_edit=first if first is not None else len(calls),
                             reads=len(reads), reread=len(reads) - len(set(reads)), grep_glob=sum(n in ('Grep', 'Glob') for n, a in calls),
                             bash_search=bsearch, files_edited=len(edited), edits=sum(n in ('Edit', 'MultiEdit') for n, a in calls),
                             writes=sum(n == 'Write' for n, a in calls), todo=sum(n == 'TodoWrite' for n, a in calls)))
w = csv.DictWriter(open('analysis/qual/navstats.csv', 'w'), fieldnames=rows[0].keys()); w.writeheader(); w.writerows(rows)
import collections
agg = collections.defaultdict(lambda: collections.Counter())
for x in rows:
    if x['ck'] >= 2:
        for f in ('calls', 'pre_edit', 'reads', 'reread', 'grep_glob', 'bash_search', 'files_edited', 'edits', 'writes'): agg[(x['task'], x['cond'])][f] += x[f]
        agg[(x['task'], x['cond'])]['n'] += 1
print('ck2..N totals (pre_edit = calls before first edit, summed over checkpoints)')
print(f"{'task':22s}{'c':4s}" + ''.join(f'{f:>13s}' for f in ('pre_edit', 'reads', 'reread', 'grep_glob', 'bash_search', 'files_edited', 'edits', 'writes')))
for (t, c), a in agg.items():
    print(f'{t:22s}{c:4s}' + ''.join(f'{a[f]:13d}' for f in ('pre_edit', 'reads', 'reread', 'grep_glob', 'bash_search', 'files_edited', 'edits', 'writes')))
