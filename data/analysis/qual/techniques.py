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
 ('own_test_run', re.compile(r'-m (pytest|unittest)\b|(^|[;&|\n(]\s*|time\s+)([\w./-]*bin/)?pytest\b')),
 ('install_or_ref_lib', re.compile(r'\b(pip|uv pip|uv add|pip3)\b.*\binstall\b|site-packages|import (jedi|parso)\b')),
 ('static_check', re.compile(r'py_compile|compileall|ast\.parse\(open|\bruff\b|\bmypy\b|pyflakes|flake8|\bradon\b')),
 ('git', re.compile(r'(^|[;&|]\s*)git\b')),
]
PY = re.compile(r'(^|[;&|(]\s*|\s)([\w./-]*bin/)?(python3?|uv run)\b')
TMP = re.compile(r'/tmp/')
SRCH = re.compile(r'(^|[;&|]\s*)(grep|rg|find|ls|tree|wc)\b')
READ = re.compile(r'(^|[;&|]\s*)(cat|head|tail|sed -n|nl|awk)\b')
ENVCHK = re.compile(r'which python3?|[\w./-]*python3? --version|-V\b|[\w./-]*python3? -m venv\b[^;&\n]*|[\w./-]*python3? -c "import \w+; ?print\(\w+\.__version__\)"|[\w./-]*python3? -c "import ast; ?ast\.parse[^"]*"|[\w./-]*(python3? -m )?pip3? (list|freeze|show)\b[^;&\n]*')
TESTCMD = re.compile(r'[^;&\n]*-m (pytest|unittest)[^;&\n]*')
def labels(name, a):
    """Multi-label: one call can be an edit AND a test run AND a probe. Table rows count calls carrying the label."""
    if name in ('Edit', 'MultiEdit', 'Write', 'NotebookEdit'): return {'edit_tool'}
    if name == 'Read': return {'read'}
    if name in ('Grep', 'Glob'): return {'locate'}
    if name == 'TodoWrite': return {'todo'}
    if name != 'Bash': return {'other:' + name}
    c = a.get('command', ''); L = set()
    noheredoc = re.sub(r"<<\s*'?(\w+)'?.*?\n\1\b", '', c, flags=re.S)
    for k, rx in RULES:
        if rx.search(noheredoc if k == 'own_test_run' else c) or (k == 'own_test_run' and re.search(r'unittest\.(TestLoader|main)\(', c)): L.add(k)
    scratch = re.match(r'\s*(mkdir[^&;]*&&\s*)?cd /tmp', c) or re.search(r"open\([^)]*/tmp", c)
    if (WRITE.search(c) or re.search(r'>>?\s*(?!/tmp|/dev)[\w./-]*requirements\.txt', c)) and not scratch: L.add('edit_script')
    if scratch or re.search(r'(^|[;&]|\n)\s*(cd /tmp|/tmp/\S+\.sh\b)', c) or (TMP.search(c) and re.search(r'cat\s*>|<<', c) and not WRITE.search(c)): L.add('probe_tmp')
    c2 = TESTCMD.sub('', ENVCHK.sub('', c))
    # python run that is not just the edit heredoc / test command
    body = re.sub(r"(cd \S+\s*(&&|;)\s*)?([\w./-]*bin/)?(python3?|uv run python3?)\s+-\s*<<\s*'?(\w+)'?.*?\n\5\b", '', c2, flags=re.S) if 'edit_script' in L else c2
    for fn, _, txt in re.findall(r"cat\s*>+\s*(\S+\.py)\s*<<\s*'?(\w+)'?(.*?)\n\2\b", body, flags=re.S):
        if WRITE.search(txt): body = re.sub(r'([\w./-]*bin/)?python3?\s+' + re.escape(fn), '', body)  # running an edit script
    body = re.sub(r"cat\s*>+\s*\S+\s*<<\s*'?(\w+)'?.*?\n\1\b", '', body, flags=re.S)
    if not L & {'probe_tmp'} and (PY.search(body) or re.search(r'(^|[;&|]\s*)(\./|\$\w+ )', body)):
        L.add('probe_run')
    if not L:
        L.add('read' if READ.search(c) else 'locate' if SRCH.search(c) else 'bash_other')
    return L
def classify(name, a): return labels(name, a)
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
                    ks = labels(x['name'], x.get('input', {}))
                    for k in ks: cnt[k] += 1
                    k = '+'.join(sorted(ks))
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
