#!/usr/bin/env python3
"""Inter-coder agreement, coder A vs coder B, on the re-coded packets. Percent agreement and Cohen's kappa per
dimension. Writes coding/agreement.json + prints a table."""
import json, glob, os, collections
V2 = os.path.dirname(os.path.abspath(__file__))
def kappa(pairs):
    n = len(pairs)
    if not n: return None, None
    po = sum(a == b for a, b in pairs) / n
    ca = collections.Counter(a for a, _ in pairs); cb = collections.Counter(b for _, b in pairs)
    pe = sum(ca[k] * cb[k] for k in set(ca) | set(cb)) / n / n
    return round(po, 3), (round((po - pe) / (1 - pe), 3) if pe < 1 else None)
VC = [f'V{i}' for i in range(1, 9)]
def units(d):
    u = {}
    for c in d['checkpoints']:
        k = c['ck']; V = c.get('V', {}) or {}
        u[('V_primary', k)] = V.get('primary')
        for v in VC: u[(f'V_present', k, v)] = v in (V.get('present') or [])
        if k >= 2:
            u[('L_primary', k)] = (c.get('L') or {}).get('primary')
            I = c.get('I') or {}
            u[('I_primary', k)] = I.get('primary')
            for fl in ('cross_internal', 'interface_change', 'read_internals'): u[(f'I_{fl}', k)] = I.get(fl)
            R = (c.get('R') or {}).get('instances') or []
            u[('R_copy_any', k)] = any(x.get('code') == 'R2' for x in R)
            u[('R_reuse_any', k)] = any(x.get('code') == 'R1' for x in R)
    for f in d.get('failures', []):
        for t in f.get('tests', []): u[('F', t)] = f.get('code')
    return u
out = {}; pooled = collections.defaultdict(list)
for fb in sorted(glob.glob(f'{V2}/coding/B/P*.json')):
    pid = os.path.basename(fb)[:-5]; fa = f'{V2}/coding/A/{pid}.json'
    if not os.path.exists(fa): continue
    A, B = units(json.load(open(fa))), units(json.load(open(fb)))
    dims = collections.defaultdict(list); miss = 0
    for key in set(A) | set(B):
        if key not in A or key not in B: miss += 1; continue
        dims[key[0]].append((str(A[key]), str(B[key]))); pooled[key[0]].append((str(A[key]), str(B[key])))
    out[pid] = {k: dict(n=len(v), pct_kappa=kappa(v)) for k, v in sorted(dims.items())}; out[pid]['unmatched_units'] = miss
out['POOLED'] = {k: dict(n=len(v), pct_kappa=kappa(v)) for k, v in sorted(pooled.items())}
json.dump(out, open(f'{V2}/coding/agreement.json', 'w'), indent=1)
for pid, v in out.items():
    print(pid, {k: (x['n'], x['pct_kappa']) if isinstance(x, dict) else x for k, x in v.items()})
