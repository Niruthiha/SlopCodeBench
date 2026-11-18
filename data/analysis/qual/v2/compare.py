#!/usr/bin/env python3
"""Un-blind and tabulate coded results by condition. Uses coder A for every cell; F codes overridden by the
analyst adjudication for double-coded cells (coding/ADJUDICATION_*.md). Writes coding/compare.json."""
import json, glob, os, collections
V2 = os.path.dirname(os.path.abspath(__file__))
key = json.load(open(f'{V2}/_key/KEY.json'))
OVR = {  # (pid, test-id substring) -> adjudicated F code
 ('P30','kronos_invent'):'F2', ('P30','revelation_10_3d'):'F2', ('P30','loki_l1_1d'):'F2', ('P30','[kronos]'):'F2',
 ('P30','jackdaw-5'):'F1', ('P30','svipul_l1-1'):'F1',
 ('P44','circular_import_hides_name_not_yet_defined'):'F2', ('P44','runtime_attribute_completion_from_namespaces'):'F1',
 ('P93','check_update_last_filter_wins'):'F6', ('P93','check_update_no_updates_success'):'F6',
 ('P93','check_update_table_format_no_updates_success'):'F6', ('P93','check_update_filtered_no_updates_mentions_filter'):'F6',
 ('P93','update_requires_confirmation'):'F6', ('P93','non_writable_nested_archive_entry_warns_with_relative_path'):'F4'}
out = {}
for pid, v in sorted(key.items(), key=lambda kv: (kv[1]['task'], kv[1]['cond'])):
    d = json.load(open(f'{V2}/coding/A/{pid}.json'))
    c = dict(task=v['task'], cond=v['cond'], pid=pid, n_ck=len(d['checkpoints']))
    ck2 = [x for x in d['checkpoints'] if x['ck'] >= 2]
    c['L_primary'] = dict(collections.Counter(x.get('L', {}).get('primary') for x in ck2))
    c['L_places'] = dict(collections.Counter(p['code'] for x in ck2 for p in x.get('L', {}).get('places', [])))
    c['I_primary'] = dict(collections.Counter(x.get('I', {}).get('primary') for x in ck2))
    for f in ('cross_internal', 'interface_change', 'read_internals'):
        c[f] = dict(collections.Counter(x.get('I', {}).get(f) for x in ck2))
    c['R'] = dict(collections.Counter(r['code'] for x in ck2 for r in x.get('R', {}).get('instances', [])))
    c['V_present'] = dict(collections.Counter(p for x in d['checkpoints'] for p in x['V']['present']))
    c['V_primary'] = dict(collections.Counter(x['V']['primary'] for x in d['checkpoints']))
    F = collections.Counter(); reg = 0
    for f in d['failures']:
        for t in f['tests']:
            code = next((cc for (p, s), cc in OVR.items() if p == pid and s in t), f['code'])
            if v['task'] == 'recli' and next((cc for (p, s), cc in OVR.items() if p == 'P93' and cc == 'F6' and s in t), None): code = 'F6'  # same no-network tests in every recli run
            F[code] += 1; reg += bool(f.get('regression'))
    c['F'] = dict(F); c['n_fail'] = sum(F.values()); c['regressions'] = reg
    out[pid] = c
json.dump(out, open(f'{V2}/coding/compare.json', 'w'), indent=1)
for c in out.values():
    print(f"{c['task'][:5]:5} {c['cond']} {c['pid']} L{c['L_primary']} I{c['I_primary']} x{c['cross_internal']} if{c['interface_change']} R{c['R']}\n      Vp{c['V_present']} Vprim{c['V_primary']}\n      F{c['F']} n={c['n_fail']} reg={c['regressions']}")
