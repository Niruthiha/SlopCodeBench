#!/usr/bin/env python3
"""Mechanical check of every evidence quote: is it verbatim (whitespace-normalised) in the cited place?
trace: inside the [ck.step] block of trace_digest.md (the call line, its results, SAY lines up to the next step;
also the SAY lines just before). file: within +-3 lines of the cited line (or anywhere in the file if line is null).
Writes evidence_check.json and evidence_all.jsonl (one row per quote, for sampling). Usage: check_evidence.py A|B"""
import json, glob, re, sys, os
V2 = os.path.dirname(os.path.abspath(__file__)); arm = sys.argv[1] if len(sys.argv) > 1 else 'A'
norm = lambda s: re.sub(r'\s+', ' ', s).strip()
def blocks(pid):
    s = open(f'{V2}/packets/{pid}/trace_digest.md', errors='replace').read().split('\n'); B = {}; cur = None; pre = []
    ck = None
    for ln in s:
        m = re.match(r'# CHECKPOINT (\d+)', ln)
        if m: ck = int(m.group(1)); cur = None; continue
        m = re.match(r'\[(\d+)\.(\d+)\]', ln)
        if m: cur = (int(m.group(1)), int(m.group(2))); B[cur] = pre[-3:] + [ln]; pre = []; continue
        if cur: B[cur].append(ln)
        if ln.strip().startswith('SAY:'): pre.append(ln)
        if ln.startswith('RESULT:') and ck: B[(ck, 'RESULT')] = [ln]
    return {k: norm(' '.join(v)) for k, v in B.items()}
def evs(o, path=''):
    if isinstance(o, dict):
        if 'quote' in o and 'src' in o: yield path, o
        else:
            for k, v in o.items(): yield from evs(v, f'{path}/{k}')
    elif isinstance(o, list):
        for i, v in enumerate(o): yield from evs(v, f'{path}[{i}]')
rows = []; summ = {}
for f in sorted(glob.glob(f'{V2}/coding/{arm}/P*.json')):
    pid = os.path.basename(f)[:-5]; d = json.load(open(f)); B = blocks(pid); ok = n = 0
    for path, e in evs(d):
        q = norm(e.get('quote', '')).rstrip('…').replace('…(+', ''); n += 1; hit = False
        if not q: res = 'empty'
        elif e['src'] == 'trace':
            st = e.get('step')
            if isinstance(st, str) and '.' in st:  # coder wrote "ck.step"; normalise, ck must match
                c_, s_ = st.split('.', 1); st = int(s_) if c_ == str(e.get('ck')) and s_.isdigit() else st
            blk = B.get((e.get('ck'), st), '')
            hit = q in blk or any(q in v for (c, _), v in B.items() if c == e.get('ck') and q in v and False)
            near = [k for k, v in B.items() if q in v and k[0] == e.get('ck')]
            res = 'ok' if hit else ('ok_step_null_unique' if (st is None and near and len({str(k[1]) for k in near}) <= 2 and (len(near) == 1 or not all(isinstance(k[1], int) for k in near) or max(k[1] for k in near) - min(k[1] for k in near) <= 1)) else ('wrong_step' if near else 'not_found'))
            ok += res == 'ok_step_null_unique'
        else:
            p = f'{V2}/packets/{pid}/{e["src"]}'
            if not os.path.exists(p): res = 'no_file'
            else:
                L = open(p, errors='replace').read().split('\n'); ln = e.get('line')
                win = L[max(0, ln - 4): ln + 3] if isinstance(ln, int) else L
                hit = q in norm(' '.join(win)); res = 'ok' if hit else ('wrong_line' if q in norm(' '.join(L)) else 'not_found')
        ok += res == 'ok'
        rows.append(dict(pid=pid, path=path, res=res, **e))
    summ[pid] = dict(n=n, ok=ok, bad={r: sum(1 for x in rows if x['pid'] == pid and x['res'] == r) for r in ('ok_step_null_unique', 'wrong_step', 'wrong_line', 'not_found', 'no_file', 'empty')})
json.dump(summ, open(f'{V2}/coding/evidence_check_{arm}.json', 'w'), indent=1)
with open(f'{V2}/coding/evidence_all_{arm}.jsonl', 'w') as w:
    for r in rows: w.write(json.dumps(r) + '\n')
for k, v in summ.items(): print(k, v)
print('TOTAL', sum(v['n'] for v in summ.values()), 'ok', sum(v['ok'] for v in summ.values()))
