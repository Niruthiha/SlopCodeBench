#!/usr/bin/env python3
"""Per cell: classify every tool call into the technique codebook used in earlier benchmarks
(FeatureBench p1_actions, HotCRP T3 trace comparison). Regex on command text; first match wins, in PRIORITY order.
Approximate: one Bash call that both edits and runs counts once, as its highest-priority purpose."""
import json, glob, re, csv, collections
dec = json.JSONDecoder()
def objs(p):
    for x in open(p):
        s = x.strip(); q = 0
        while q < len(s) and s[q] == '{':
            o, q = dec.raw_decode(s, q); yield o
            while q < len(s) and s[q].isspace(): q += 1
WRITE = re.compile(r"open\([^)]*['\"][wa]['\"]|\.write_text\(|\bsed -i|\btee\b(?!.*?/tmp)|apply_patch|\bpatch\b -p|cat\s*>{1,2}\s*(?!/tmp|/dev)[\w./-]+")
RULES = [
 ('own_test_run', re.compile(r'\bpytest\b|-m unittest|\bunittest\b')),
 ('install_or_ref_lib', re.compile(r'\b(pip|uv pip|uv add|pip3)\b.*\binstall\b|site-packages|import (jedi|parso)\b')),
 ('static_check', re.compile(r'py_compile|compileall|\bruff\b|\bmypy\b|pyflakes|flake8|\bradon\b')),
 ('git', re.compile(r'(^|[;&|]\s*)git\b')),
]
PY = re.compile(r'(^|[;&|(]\s*|\s)([\w./-]*bin/)?(python3?|uv run)\b')
TMP = re.compile(r'/tmp/')
SRCH = re.compile(r'(^|[;&|]\s*)(grep|rg|find|ls|tree|wc)\b')
READ = re.compile(r'(^|[;&|]\s*)(cat|head|tail|sed -n|nl|awk)\b')
def classify(name, a):
    if name in ('Edit', 'MultiEdit', 'Write', 'NotebookEdit'): return 'edit_tool'
    if name == 'Read': return 'read'
    if name in ('Grep', 'Glob'): return 'locate'
    if name == 'TodoWrite': return 'todo'
    if name != 'Bash': return 'other:' + name
    c = a.get('command', '')
    for k, rx in RULES:
        if rx.search(c): return k
    scratch = re.match(r'\s*(mkdir[^&;]*&&\s*)?cd /tmp', c) or re.search(r"open\([^)]*/tmp", c)
    if WRITE.search(c) and not scratch: return 'edit_script'
    if scratch or (TMP.search(c) and re.search(r'cat\s*>|<<', c)): return 'probe_tmp'
    if PY.search(c) or re.search(r'(^|[;&|]\s*)(\./|\$\w+ )', c):
        return 'probe_tmp' if TMP.search(c) else 'probe_run'
    if READ.search(c): return 'read'
    if SRCH.search(c): return 'locate'
    return 'bash_other'
RUNS = {t: sorted(glob.glob(f'runs/{t}/c[123]_*_s1_*')) for t in ['sith', 'eve_industry', 'recli', 'metric_transform_lang']}
rows = []; ex = collections.defaultdict(list)
for t, runs in RUNS.items():
    for r in runs:
        c = r.split('/')[-1][:2]; cnt = collections.Counter(); tmpfiles = set()
        for ck in glob.glob(f'{r}/{t}/checkpoint_*'):
            for m in objs(f'{ck}/agent/stdout.jsonl'):
                if m.get('type') != 'assistant': continue
                for x in m['message'].get('content', []):
                    if x.get('type') != 'tool_use': continue
                    k = classify(x['name'], x.get('input', {})); cnt[k] += 1
                    cmd = x.get('input', {}).get('command', '') or x.get('input', {}).get('file_path', '')
                    tmpfiles |= set(re.findall(r'/tmp/[\w./-]+\.(?:py|sh|csv|json|yaml|yml|mtl|txt)', cmd))
                    if len(ex[(t, c, k)]) < 2: ex[(t, c, k)].append(cmd[:140].replace('\n', ' ⏎ '))
        cnt['tmp_files_named'] = len(tmpfiles)
        rows.append(dict(task=t, cond=c, **cnt))
keys = ['read', 'locate', 'edit_tool', 'edit_script', 'probe_run', 'probe_tmp', 'tmp_files_named', 'own_test_run', 'static_check', 'install_or_ref_lib', 'git', 'todo', 'bash_other']
w = csv.DictWriter(open('analysis/qual/techniques.csv', 'w'), fieldnames=['task', 'cond'] + keys, extrasaction='ignore', restval=0); w.writeheader(); w.writerows(rows)
print(f"{'task':22s}{'c':3s}" + ''.join(f'{k[:11]:>12s}' for k in keys))
for x in rows: print(f"{x['task']:22s}{x['cond']:3s}" + ''.join(f"{x.get(k,0):12d}" for k in keys))
json.dump({f'{a}|{b}|{k}': v for (a, b, k), v in ex.items()}, open('analysis/qual/techniques_examples.json', 'w'), indent=1)
