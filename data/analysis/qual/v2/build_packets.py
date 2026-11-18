#!/usr/bin/env python3
"""Build one blinded packet per cell for independent qualitative coding (CODEBOOK.md).
Condition label hidden: packet IDs are random; the first-checkpoint design instruction is replaced by the same
placeholder in every cell; condition words are redacted from the trace digest. Code files are copied unchanged
(code comments can still reveal the design style; file layout always does). Key: _key/KEY.json (coders must not open).
Run from scbench/: python3 analysis/qual/v2/build_packets.py"""
import json, glob, os, re, random, shutil, subprocess
V2 = 'analysis/qual/v2'; P = f'{V2}/packets'
INSTR = re.compile(r'^(Decompose by information hiding\..*|Write the program in a modular way:.*|Before coding, write a brief design plan in `DESIGN\.md`, then implement\.)$', re.M)
PH = '[design instruction, if any, removed for blinding]'
RED = re.compile(r'(?i)information[ -]hiding|parnas|well[- ]organi[sz]ed modules|single responsibilit(?:y|ies)')
cells = []
for t in ['sith', 'eve_industry', 'recli', 'metric_transform_lang']:
    for r in sorted(glob.glob(f'runs/{t}/c[123]_*_s1_*')): cells.append((t, r))
ids = random.Random(20261111).sample([f'P{n:02d}' for n in range(10, 100)], len(cells))
key = {}
shutil.rmtree(P, ignore_errors=True)
for (t, r), pid in zip(cells, ids):
    key[pid] = {'task': t, 'cond': os.path.basename(r)[:2], 'run': r}
    d = f'{P}/{pid}'; os.makedirs(f'{d}/spec'); os.makedirs(f'{d}/results'); os.makedirs(f'{d}/diffs')
    cks = sorted(glob.glob(f'{r}/{t}/checkpoint_*'), key=lambda p: int(p.rsplit('_', 1)[1]))
    # trace digest, redacted
    subprocess.run(['python3', 'analysis/qual/digest.py', r, t, f'{d}/trace_digest.md'], check=True)
    s = open(f'{d}/trace_digest.md').read()
    s = re.sub(r'(?<=any dependencies you need to solve the problem\.)[^\n]*?(?=Your task is:|$)', ' ' + PH + ' ', s, count=1, flags=re.M)
    s = RED.sub('[redacted]', s)
    open(f'{d}/trace_digest.md', 'w').write(s)
    seen_fail = {}; passed_before = set()
    for ck in cks:
        k = int(ck.rsplit('_', 1)[1])
        sp = open(f'{ck}/prompt.txt').read()
        if k == 1: sp = re.sub(r'(?<=any dependencies you need to solve the problem\.\n).*?(?=Your task is:)', PH + '\n', sp, count=1, flags=re.S)
        open(f'{d}/spec/checkpoint_{k}.md', 'w').write(sp)
        shutil.copytree(f'{ck}/snapshot', f'{d}/code/checkpoint_{k}', ignore=shutil.ignore_patterns('.venv', 'venv', '__pycache__', '*.pyc', '.pytest_cache'))
        df = json.load(open(f'{ck}/diff.json')).get('file_diffs', {})
        open(f'{d}/diffs/checkpoint_{k}.patch', 'w').write(''.join(f"### {p} ({v.get('change_type')})\n" + RED.sub('[redacted]', (v.get('diff_text') or '').replace('\n\n', '\n')) + '\n' for p, v in sorted(df.items()) if not re.search(r'(^|/)(\.venv|venv|__pycache__)/', p)))
        rep = json.load(open(f'{ck}/evaluation/report.json'))['tests']
        lines = [f'# Checkpoint {k} hidden-test results', '']
        cnt = {}
        for x in rep: cnt[x['outcome']] = cnt.get(x['outcome'], 0) + 1
        lines.append(f'Outcomes: {cnt}'); lines.append('')
        lines.append('Tests listed below did not pass. FIRST = first checkpoint where this test fails in this cell. REGRESSION = the test passed at an earlier checkpoint of this cell.'); lines.append('')
        for x in rep:
            nid = x['nodeid']
            if x['outcome'] == 'passed': passed_before.add(nid); continue
            if x['outcome'] == 'skipped': continue
            first = nid not in seen_fail; seen_fail.setdefault(nid, k)
            reg = nid in passed_before
            lr = str((x.get('call') or x.get('setup') or {}).get('longrepr', ''))
            lines.append(f"## {nid}  [{'FIRST' if first else f'still failing since ck{seen_fail[nid]}'}{', REGRESSION' if reg else ''}]")
            if first: lines += ['```', lr[-2500:], '```']
            lines.append('')
        open(f'{d}/results/checkpoint_{k}.md', 'w').write('\n'.join(lines))
    for md in glob.glob(f'{d}/code/**/*.md', recursive=True): open(md, 'w').write(RED.sub('[redacted]', open(md).read()))
    shutil.copytree(f'scb-problems/{t}/tests', f'{d}/tests', ignore=shutil.ignore_patterns('__pycache__'))
    open(f'{d}/README.md', 'w').write(f'Packet {pid}. Task: {t}. Checkpoints: 1..{len(cks)}.\n'
        'trace_digest.md: every tool call as [checkpoint.step] TOOL args -> result head; SAY = agent text; RESULT = session end.\n'
        'spec/: the prompt given at each checkpoint. code/checkpoint_k/: the code after checkpoint k. diffs/checkpoint_k.patch: what checkpoint k changed.\n'
        'results/: hidden-test results per checkpoint (failing tests with assertion output). tests/: the benchmark test files.\n'
        'Each checkpoint was a fresh agent session that saw only the code left by the previous one.\n')
json.dump(key, open(f'{V2}/_key/KEY.json', 'w'), indent=1)
print({k: (v['task'], v['cond']) for k, v in key.items()})
# Post-fix (2026-11-11): two resumed checkpoints have harness diffs taken against an empty tree
# (sith c2 ck2, mtl c3 ck5). Replace them with diff -ruN between consecutive snapshots.
for pid, v in key.items():
    for (t, c, k) in [('sith', 'c2', 2), ('metric_transform_lang', 'c3', 5)]:
        if (v['task'], v['cond']) == (t, c):
            d = f'{P}/{pid}'
            out = subprocess.run(['diff', '-ruN', f'checkpoint_{k-1}', f'checkpoint_{k}'], cwd=f'{d}/code', capture_output=True, text=True).stdout
            open(f'{d}/diffs/checkpoint_{k}.patch', 'w').write(f'# Regenerated by the analyst: the harness diff for this checkpoint was taken against an empty tree (resumed checkpoint). This is diff -ruN code/checkpoint_{k-1} code/checkpoint_{k}.\n' + RED.sub('[redacted]', out))
