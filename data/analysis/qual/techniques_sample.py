#!/usr/bin/env python3
"""Draw a fixed random sample of Bash calls for hand-checking techniques.py: 30 assigned to a table category
(probe_tmp, probe_run, own_test_run, edit_script) and 30 assigned to any other category."""
import json, glob, random, sys
sys.path.insert(0, 'analysis/qual')
import importlib.util
spec = importlib.util.spec_from_file_location('tq', 'analysis/qual/techniques.py')
src = open('analysis/qual/techniques.py').read().split('RUNS = ')[0]
ns = {}; exec(src, ns)
TABLE = {'probe_tmp', 'probe_run', 'own_test_run', 'edit_script'}
calls = []
for t in ['sith', 'eve_industry', 'recli', 'metric_transform_lang']:
    for r in sorted(glob.glob(f'runs/{t}/c[123]_*_s1_*')):
        c = r.split('/')[-1][:2]
        for ck in sorted(glob.glob(f'{r}/{t}/checkpoint_*')):
            for m in ns['objs'](f'{ck}/agent/stdout.jsonl'):
                if m.get('type') != 'assistant': continue
                for x in m['message'].get('content', []):
                    if x.get('type') == 'tool_use' and x['name'] == 'Bash':
                        calls.append(dict(task=t, cond=c, ck=ck.rsplit('_', 1)[1], cls=sorted(ns['labels']('Bash', x['input'])), cmd=x['input'].get('command', '')))
rng = random.Random(int(sys.argv[1]) if len(sys.argv)>1 else 202611112)
inn = [x for x in calls if TABLE & set(x['cls'])]; out = [x for x in calls if not TABLE & set(x['cls'])]
sample = rng.sample(inn, 30) + rng.sample(out, 30)
for i, x in enumerate(sample): x['id'] = i + 1
json.dump(sample, open((sys.argv[2] if len(sys.argv)>2 else 'analysis/qual/techniques_sample.json'), 'w'), indent=1)
print(len(calls), 'bash calls;', len(inn), 'in table categories;', len(out), 'other')
for x in sample:
    print(f"\n#{x['id']} [{x['cls']}] {x['task']} {x['cond']} ck{x['ck']}\n  " + (x['cmd'] if len(x['cmd']) < 520 else x['cmd'][:300] + ' [...] ' + x['cmd'][-200:]).replace('\n', ' ⏎ '))
