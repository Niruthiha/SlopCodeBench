#!/usr/bin/env python3
"""Compact, readable action log per cell/checkpoint from agent/stdout.jsonl.
One line per step: [ck.step] TOOL args (truncated) -> result head (errors flagged). Assistant text kept (truncated).
Usage: digest.py <run_dir> <task> <out.md>"""
import json, sys, glob, os, re
run, task, out = sys.argv[1:4]
dec = json.JSONDecoder()
def objs(p):
    for x in open(p):
        s = x.strip(); q = 0
        while q < len(s) and s[q] == '{':
            o, q = dec.raw_decode(s, q); yield o
            while q < len(s) and s[q].isspace(): q += 1
def short(v, n):
    v = re.sub(r'\s+', ' ', str(v)); return v if len(v) <= n else v[:n] + f'…(+{len(v)-n})'
def targs(name, a):
    if name in ('Read',): return a.get('file_path', '') + (f" off={a.get('offset')}" if a.get('offset') else '')
    if name in ('Write',): return f"{a.get('file_path')} ({len(a.get('content',''))} chars, {a.get('content','').count(chr(10))+1} lines)"
    if name in ('Edit', 'MultiEdit'): return f"{a.get('file_path')} old={short(a.get('old_string',''),100)!r} new={short(a.get('new_string',''),160)!r}"
    if name == 'Bash': return short(a.get('command', ''), 300)
    if name in ('Grep', 'Glob'): return short(json.dumps(a), 200)
    if name in ('TodoWrite',): return short(' | '.join(f"[{t.get('status','')[:4]}] {t.get('content','')}" for t in a.get('todos', [])), 400)
    return short(json.dumps(a), 200)
W = open(out, 'w')
cks = sorted(glob.glob(f'{run}/{task}/checkpoint_*'), key=lambda p: int(p.rsplit('_', 1)[1]))
for ck in cks:
    k = ck.rsplit('_', 1)[1]; p = f'{ck}/agent/stdout.jsonl'
    W.write(f'\n\n# CHECKPOINT {k}\n')
    pr = f'{ck}/prompt.txt'
    if os.path.exists(pr): W.write(f'PROMPT (first 600 chars): {short(open(pr).read(), 600)}\n')
    step = 0; pend = {}
    for m in objs(p):
        t = m.get('type')
        if t == 'assistant':
            for c in m['message'].get('content', []):
                if c.get('type') == 'text' and c['text'].strip():
                    W.write(f'  SAY: {short(c["text"], 700)}\n')
                elif c.get('type') == 'tool_use':
                    step += 1; pend[c['id']] = step
                    W.write(f'[{k}.{step}] {c["name"]} {targs(c["name"], c.get("input", {}))}\n')
        elif t == 'user':
            cont = m.get('message', {}).get('content', [])
            if isinstance(cont, list):
                for c in cont:
                    if c.get('type') == 'tool_result':
                        r = c.get('content'); r = ' '.join(x.get('text', '') for x in r if isinstance(x, dict)) if isinstance(r, list) else str(r)
                        err = c.get('is_error')
                        W.write(f'    -> {"ERROR " if err else ""}{short(r, 400 if err or "Traceback" in r or "FAIL" in r or "Error" in r else 160)}\n')
        elif t == 'result':
            W.write(f'RESULT: turns={m.get("num_turns")} dur={m.get("duration_ms",0)//60000}min final="{short(m.get("result",""), 900)}"\n')
    ev = f'{ck}/evaluation.json'
    if os.path.exists(ev):
        try:
            d = json.load(open(ev)); W.write(f'EVAL: {short(json.dumps({k2: v for k2, v in d.items() if k2 not in ("tests","results")}), 400)}\n')
        except Exception as e: W.write(f'EVAL unreadable {e}\n')
W.close()
