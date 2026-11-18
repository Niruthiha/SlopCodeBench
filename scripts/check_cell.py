#!/usr/bin/env python3
"""Per-cell isolation + leakage check. PASS only if every checkpoint's startup record has the identical skill list,
no anthropic-skills:*, no MCP servers/tools, and 0 Skill/MCP calls; also counts leakage mentions. Usage: check_cell.py <run_dir>"""
import json, sys, glob, os, re
run = sys.argv[1]; prob = next(d for d in sorted(glob.glob(os.path.join(run, '*/'))) if not os.path.basename(d.rstrip('/')).startswith('_') and glob.glob(os.path.join(d, 'checkpoint_*'))).rstrip('/')  # skip _invalid_attempt/
_dec = json.JSONDecoder()
def objs(txt):
    """Every JSON object in a jsonl trace, incl. lines where the writer dropped a newline between two objects (seen at 4096-byte boundaries, recli c3 ck8). Unparseable lines are counted, never silently skipped."""
    global unparsed
    for x in txt.splitlines():
        s = x.strip(); p = 0
        while p < len(s):
            if s[p] != '{': unparsed += 1; break
            try: o, p = _dec.raw_decode(s, p)
            except json.JSONDecodeError: unparsed += 1; break
            yield o
            while p < len(s) and s[p].isspace(): p += 1
unparsed = 0
ok = True; lists = {}
for res in (json.loads(l) for l in open(os.path.join(run, 'checkpoint_results.jsonl'))):
    k = res['checkpoint'][-1]
    print(f"ckpt{k} core {res['core_passed']}/{res['core_total']} func {res['functionality_passed']}/{res['functionality_total']} "
          f"err {res['error_passed']}/{res['error_total']} reg {res['regression_passed']}/{res['regression_total']} steps {res['steps']} cost ${res['cost']:.2f}")
for f in sorted(glob.glob(os.path.join(prob, 'checkpoint_*/agent/stdout.jsonl'))):
    k = f.split('checkpoint_')[1][0]; txt = open(f).read(); inits = []; tu = {}
    unparsed = 0; allm = list(objs(txt))
    for m in allm:
        if m.get('type') == 'system' and m.get('subtype') == 'init': inits.append(m)
        if m.get('type') == 'assistant':
            for c in m['message'].get('content', []):
                if c.get('type') == 'tool_use': tu[c['name']] = tu.get(c['name'], 0) + 1
    sk = tuple(sorted(inits[0]['skills'])) if inits else ()
    lists[k] = sk
    acct = sum(s.startswith('anthropic-skills') for s in sk)
    mcp = inits[0].get('mcp_servers') if inits else None
    mtools = [t for t in (inits[0]['tools'] if inits else []) if t.startswith('mcp__') or 'Mcp' in t]
    calls_mcp = sum(v for n, v in tu.items() if n.startswith('mcp__') or 'Mcp' in n)
    leak = {w: txt.count(w) for w in ('.evaluation_tests', 'scb-problems', 'solutions/')}
    autherr = [m for m in allm if m.get('type') == 'result' and m.get('is_error')]
    if autherr: print(f"ckpt{k} FAIL agent result is_error x{len(autherr)}: {str(autherr[0].get('result'))[:120]}")
    if unparsed: print(f"ckpt{k} FAIL unparseable trace fragments: {unparsed}")
    bad = unparsed or autherr or not inits or len(sk) != 17 or acct or mcp or mtools or tu.get('Skill', 0) or calls_mcp or any(leak.values())
    ok &= not bad
    print(f"ckpt{k} {'PASS' if not bad else 'FAIL'} inits={len(inits)} skills={len(sk)} anthropic-skills={acct} mcp_servers={mcp} "
          f"mcp_tools={len(mtools)} Skill_calls={tu.get('Skill',0)} mcp_calls={calls_mcp} tools_used={tu} leak={leak} DESIGN.md={txt.count('DESIGN.md')}")
NCK = len(glob.glob(os.path.join(prob, 'checkpoint_*')))
same = len(set(lists.values())) == 1 and len(lists) == NCK and NCK >= 2
ok &= same
if not same: print('FAIL: skill lists differ or checkpoint count mismatch', {k: len(v) for k, v in lists.items()})
print(f'identical skill list across {NCK} checkpoints:', same, '|', list(next(iter(lists.values()))) if lists else [])
fresh_lists = {}; resumed = []
_cfg = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'scb-problems', os.path.basename(prob), 'config.yaml')
HAS_ASSETS = os.path.exists(_cfg) and re.search(r'^static_assets:', open(_cfg).read(), re.M) is not None
print(f'problem static_assets declared: {HAS_ASSETS}')
for k in range(2, NCK + 1):
    p = os.path.join(prob, f'parnas_reset_checkpoint_{k}.json')
    if os.path.exists(p):
        r = json.load(open(p)); print(f"reset{k}: removed={[x for x in r['removed'] if not x.startswith('~')]} ws {len(r['before']['workspace'])}->{len(r['after']['workspace'])} home {len(r['before'].get('claude_home',[]))}->{r['after'].get('claude_home')}")
        c = r.get('container', {}); newl = tuple(c.get('new', {}).get('listing', []))
        okc = bool(c.get('respawned')) and c['old'].get('id') != c['new'].get('id') and 'error' not in c['new']
        init = set(r.get('initial_workspace', [])); docs = [f for f in r['after']['workspace'] if f.lower().endswith(('.md', '.rst', '.markdown')) and f not in init]
        home_left = [f for f in r['after'].get('claude_home', []) if f != 'settings.json']
        fresh_lists[k] = newl
        init_ok = 'initial_workspace' in r and (bool(init) or not HAS_ASSETS)
        if not init_ok: print(f'reset{k}: FAIL initial_workspace missing, or empty while the problem declares static assets')
        ok &= okc and not docs and not home_left and init_ok
        print(f"reset{k}: container {c.get('old',{}).get('id')}->{c.get('new',{}).get('id')} respawned={okc} old_nonmount={len(c.get('old',{}).get('listing',[]))} new_nonmount={len(newl)} agent_docs_left={docs} home_left={home_left}")
    elif os.path.exists(rp := os.path.join(prob, f'parnas_resume_checkpoint_{k}.json')):
        r = json.load(open(rp)); init = set(r.get('initial_workspace', []))
        docs = [f for f in r['agent_docs_in_snapshot'] if f not in init]; resumed.append(k)
        ok &= not docs
        print(f"reset{k}: RESUMED ({r['mode']}) from {r['restored_from']} files={len(r['snapshot_files'])} agent_docs_in_snapshot={docs} "
              f"[no container listing for this checkpoint; invalid attempt kept in _invalid_attempt/]")
    else: ok = False; print(f"reset{k}: MISSING")
same_fresh = len(set(fresh_lists.values())) == 1 and len(fresh_lists) == NCK - 1 - len(resumed)
ok &= same_fresh
if not same_fresh: print('FAIL: fresh container listings differ or a reset is missing')
print(f'fresh container state identical at ckpt 2-{NCK}:', same_fresh, '|', list(next(iter(fresh_lists.values()))) if fresh_lists else [])
creds = [p for p in glob.glob(os.path.join(run, '**/.credentials.json'), recursive=True)]
tok = sum(1 for p in glob.glob(os.path.join(run, '**/*'), recursive=True) if os.path.isfile(p) and re.search(rb'sk-ant-[A-Za-z0-9_-]{8}', open(p, 'rb').read()))
ok &= not creds and not tok
print(f"credentials files={len(creds)} token-shaped files={tok}")
print('CELL', 'PASS' if ok else 'FAIL'); sys.exit(0 if ok else 1)
