#!/usr/bin/env python3
"""Collect per-checkpoint metrics for the 3 tasks x 3 conditions into data.json (no cost/token fields: deferred by user)."""
import json, glob, os, re
from collections import Counter
B = '/home/niruthi/features/scbench'
TASKS = {'metric_transform_lang': ['c1_planning', 'c2_modular', 'c3_parnas'],
         'sith': ['c1_default', 'c2_modular', 'c3_parnas'],
         'eve_industry': ['c1_default', 'c2_modular', 'c3_parnas'],
         'recli': ['c1_default', 'c2_modular', 'c3_parnas']}
_dec = json.JSONDecoder()
def objs(path):
    """Every JSON object in a jsonl trace, incl. lines where two objects share a line (dropped newline at 4096 bytes)."""
    bad = 0; out = []
    for x in open(path):
        s = x.strip(); p = 0
        while p < len(s):
            if s[p] != '{': bad += 1; break
            try: o, p = _dec.raw_decode(s, p)
            except json.JSONDecodeError: bad += 1; break
            out.append(o)
            while p < len(s) and s[p].isspace(): p += 1
    return out, bad
KEEP = ['checkpoint', 'duration', 'steps', 'total_tests', 'passed_tests', 'core_total', 'core_passed', 'functionality_total',
        'functionality_passed', 'error_total', 'error_passed', 'regression_total', 'regression_passed', 'loc', 'sloc', 'files',
        'functions', 'methods', 'classes', 'cc_max', 'cc_mean', 'cc_high_count', 'max_nesting_depth', 'lint_errors', 'lint_per_loc',
        'lines_added', 'lines_removed', 'cloned_pct', 'verbosity', 'erosion', 'graph_propagation_cost', 'graph_cyclic_dependency_mass', 'input', 'output', 'cache_read', 'cache_write', 'started', 'ended']
out = {'tasks': {}}
for task, conds in TASKS.items():
    T = out['tasks'][task] = {'cells': {}}
    for c in conds:
        run = sorted(d for d in glob.glob(f'{B}/runs/{task}/{c}_s1_*') if os.path.isdir(d))[-1]
        P = f'{run}/{task}'
        rows = [json.loads(l) for l in open(f'{run}/checkpoint_results.jsonl')]
        fs = json.load(open(f'{run}/failure_summary.json'))['checkpoints']
        cks = []
        for r in rows:
            ck = r['checkpoint']; d = {k: r.get(k) for k in KEEP}
            tools = Counter(); nturn = 0
            sp = f'{P}/{ck}/agent/stdout.jsonl'
            ms, bad = objs(sp) if os.path.exists(sp) else ([], 0)
            assert bad == 0, (sp, bad)
            for m in ms:
                if m.get('type') == 'assistant':
                    nturn += 1
                    for x in m['message'].get('content', []):
                        if x.get('type') == 'tool_use': tools[x['name']] += 1
            d['tools'] = dict(tools); d['tool_calls'] = sum(tools.values())
            d['failed'] = sorted({g.replace('-', ' ').split()[0] + '::' + (x['test'] if isinstance(x, dict) else x) for g, l in fs.get(ck, {}).get('failed', {}).items() for x in l})
            d['skipped_nonpass'] = (r['total_tests'] - r['passed_tests']) - len(d['failed'])
            snap = f'{P}/{ck}/snapshot'
            d['agent_docs'] = sorted(os.path.relpath(f, snap) for f in glob.glob(f'{snap}/**/*', recursive=True)
                                     if f.lower().endswith(('.md', '.rst')) and '/.venv/' not in f and '/venv/' not in f)
            d['failed_by_group'] = {g: sorted({(x['test'] if isinstance(x, dict) else x) for x in l}) for g, l in fs.get(ck, {}).get('failed', {}).items() if l}
            pt = open(f'{P}/{ck}/prompt.txt').read().splitlines()
            i = pt.index('Your task is:') if 'Your task is:' in pt else 3
            d['prompt_head'] = pt[:i]; d['task_line'] = next((x for x in pt[i+1:] if x.strip()), '')[:400]
            d['resumed'] = os.path.exists(f'{P}/parnas_resume_{ck}.json')
            d['cost'] = r.get('cost')
            cks.append(d)
        T['cells'][c] = {'run_dir': os.path.relpath(run, B), 'checkpoints': cks,
                         'check_cell': open(f'{run}/check_cell.txt').read().strip().splitlines()[-1],
                         'prompt_ckpt1': os.path.relpath(f'{P}/checkpoint_1/prompt.txt', B),
                         'prompt_ckpt2': os.path.relpath(f'{P}/checkpoint_2/prompt.txt', B),
                         'resume_logs': sorted(os.path.relpath(f, B) for f in glob.glob(f'{P}/parnas_resume_*.json')),
                         'invalid_attempt': os.path.relpath(f'{run}/_invalid_attempt', B) if os.path.isdir(f'{run}/_invalid_attempt') else None}
    T['refcheck'] = f'runs/refcheck/{task}'
    T['refcheck_split'] = f'runs/refcheck/{task}_split' if os.path.isdir(f'{B}/runs/refcheck/{task}_split') else None
    T['spec_dir'] = f'scb-problems/{task}'
    T['n_ck'] = len(cks)
json.dump(out, open(f'{B}/analysis/compare/data.json', 'w'), indent=1)
for t, T in out['tasks'].items():
    for c, C in T['cells'].items():
        print(t, c, len(C['checkpoints']), C['check_cell'], [x['tool_calls'] for x in C['checkpoints']])
