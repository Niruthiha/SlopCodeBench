#!/usr/bin/env python3
"""Per-checkpoint trace summary for one cell: wall time, cost, tokens (uncached / cache read / cache write / output),
agent turns, and tool calls by name (from the stream-json trace). Writes <run>/trace_summary.json and .md.
Usage: trace_summary.py <run_dir>"""
import glob, json, os, sys

run = sys.argv[1]
_dec = json.JSONDecoder()


def objs(txt):
    for line in txt.splitlines():
        s = line.strip(); p = 0
        while p < len(s) and s[p] == '{':
            try:
                o, p = _dec.raw_decode(s, p)
            except json.JSONDecodeError:
                break
            yield o
            while p < len(s) and s[p].isspace():
                p += 1


results = {}
crf = os.path.join(run, 'checkpoint_results.jsonl')
if os.path.exists(crf):
    for l in open(crf):
        r = json.loads(l); results[r['checkpoint']] = r

rows = []
for f in sorted(glob.glob(os.path.join(run, '*', 'checkpoint_*', 'agent', 'stdout.jsonl')),
                key=lambda x: int(x.split('checkpoint_')[1].split(os.sep)[0].split('/')[0])):
    ck = 'checkpoint_' + f.split('checkpoint_')[1].split(os.sep)[0].split('/')[0]
    tools, assistant_msgs, results_n, dur_ms, api_ms = {}, 0, 0, 0, 0
    usage = dict(input=0, output=0, cache_read=0, cache_write=0, thinking=0, cost=0.0)
    for m in objs(open(f, encoding='utf-8', errors='replace').read()):
        t = m.get('type')
        if t == 'assistant':
            assistant_msgs += 1
            for c in m.get('message', {}).get('content', []):
                if c.get('type') == 'tool_use':
                    tools[c['name']] = tools.get(c['name'], 0) + 1
        elif t == 'result':
            results_n += 1
            dur_ms += m.get('duration_ms') or 0
            api_ms += m.get('duration_api_ms') or 0
            for mu in (m.get('model_usage_since_last_result') or m.get('modelUsage') or {}).values():
                usage['input'] += mu.get('inputTokens', 0); usage['output'] += mu.get('outputTokens', 0)
                usage['cache_read'] += mu.get('cacheReadInputTokens', 0)
                usage['cache_write'] += mu.get('cacheCreationInputTokens', 0)
                usage['thinking'] += mu.get('thinkingTokens', 0) or 0
                usage['cost'] += mu.get('costUSD', 0.0)
    r = results.get(ck, {})
    read_tools = sum(v for k, v in tools.items() if k in ('Read', 'Grep', 'Glob', 'LS'))
    edit_tools = sum(v for k, v in tools.items() if k in ('Edit', 'Write', 'MultiEdit', 'NotebookEdit'))
    rows.append(dict(
        checkpoint=ck,
        harness_duration_s=r.get('duration'), agent_duration_s=dur_ms / 1000, api_duration_s=api_ms / 1000,
        harness_cost=r.get('cost'), trace_cost=round(usage['cost'], 4), steps=r.get('steps'),
        assistant_messages=assistant_msgs, cli_results=results_n,
        tokens=dict(input_uncached=usage['input'], cache_read=usage['cache_read'], cache_write=usage['cache_write'],
                    output=usage['output'], thinking=usage['thinking']),
        tool_calls_total=sum(tools.values()), tool_calls_read=read_tools, tool_calls_edit=edit_tools,
        tool_calls_bash=tools.get('Bash', 0), tool_calls=dict(sorted(tools.items(), key=lambda kv: -kv[1])),
        tests=dict(passed=r.get('passed_tests'), total=r.get('total_tests'),
                   core=f"{r.get('core_passed')}/{r.get('core_total')}",
                   regression=f"{r.get('regression_passed')}/{r.get('regression_total')}"),
        loc=r.get('loc'),
    ))

tot = dict(checkpoints=len(rows),
           harness_duration_h=round(sum(x['harness_duration_s'] or 0 for x in rows) / 3600, 2),
           cost=round(sum(x['harness_cost'] or x['trace_cost'] for x in rows), 2),
           steps=sum(x['steps'] or 0 for x in rows), tool_calls=sum(x['tool_calls_total'] for x in rows))
json.dump(dict(run=os.path.abspath(run), total=tot, checkpoints=rows), open(os.path.join(run, 'trace_summary.json'), 'w'), indent=1)

md = [f"# Trace summary: {os.path.basename(os.path.abspath(run))}", "",
      "| ckpt | time (min) | cost $ | steps | tools | read | edit | bash | in (uncached) | cache read | cache write | out | tests | core | reg |",
      "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
for x in rows:
    t = x['tokens']; d = x['harness_duration_s'] or x['agent_duration_s']
    md.append(f"| {x['checkpoint'][11:]} | {d/60:.1f} | {(x['harness_cost'] or x['trace_cost']):.2f} | {x['steps']} | "
              f"{x['tool_calls_total']} | {x['tool_calls_read']} | {x['tool_calls_edit']} | {x['tool_calls_bash']} | "
              f"{t['input_uncached']:,} | {t['cache_read']:,} | {t['cache_write']:,} | {t['output']:,} | "
              f"{x['tests']['passed']}/{x['tests']['total']} | {x['tests']['core']} | {x['tests']['regression']} |")
md += ["", f"**Total:** {tot['checkpoints']} checkpoints, {tot['harness_duration_h']} h, ${tot['cost']}, "
           f"{tot['steps']} steps, {tot['tool_calls']} tool calls"]
open(os.path.join(run, 'trace_summary.md'), 'w').write("\n".join(md) + "\n")
print("\n".join(md))
