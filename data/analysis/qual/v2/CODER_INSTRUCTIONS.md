# Instructions for a coder (one packet)

You code ONE packet: `analysis/qual/v2/packets/<ID>/` (paths below are relative to `/home/niruthi/features/scbench/`).
Read `analysis/qual/v2/CODEBOOK.md` first and apply it exactly.

Rules
- Read ONLY your packet folder and the codebook. Do not open other packets, `analysis/qual/v2/_key/`,
  `analysis/qual/v2/coding/`, `runs/`, `scb-problems/`, other analysis files, or the web.
- The condition (which design instruction this run got, if any) is hidden. Do not try to guess it, and do not
  mention or speculate about it. Describe what the agent did.
- Evidence for every code (see the codebook's evidence rule). Quotes are copied verbatim, at most 200 characters.
  If you cannot find evidence, code `UNCLEAR` with a reason. No evidence, no claim.
- Do not change any file except your output file.
- `trace_digest.md` is large: search it (Grep for `^\[3\.` etc.) and read it in parts. Steps are tagged `[ck.step]`.
- Each checkpoint is a separate session. Earlier sessions' notes were deleted; only code carried over.

Output: write ONE JSON file to the path you are given, with this shape:

```json
{
  "packet": "P##",
  "checkpoints": [
    {
      "ck": 1,
      "V": {"present": ["V2", "V5"], "primary": "V2",
            "evidence": {"V2": [EV], "V5": [EV]}},
      "summary": "≤40 words: what this session did and how it checked it"
    },
    {
      "ck": 2,
      "L": {"primary": "L3", "places": [{"place": "pkg/x.py", "code": "L3", "evidence": [EV]}]},
      "I": {"primary": "I1", "cross_internal": "no", "interface_change": "yes", "read_internals": "yes",
            "evidence": {"primary": [EV], "cross_internal": [], "interface_change": [EV], "read_internals": [EV]}},
      "R": {"instances": [{"code": "R1", "what": "≤20 words", "evidence": [EV]}]},
      "V": {"present": [...], "primary": "...", "evidence": {...}},
      "summary": "≤40 words"
    }
  ],
  "failures": [
    {"tests": ["<full test node id>", "..."], "first_ck": 3, "regression": false, "code": "F2",
     "why": "≤40 words", "evidence": [EV, EV]}
  ],
  "observations": "≤250 words, starting 'In this run we observed'. Every claim cites a checkpoint and step."
}
```

`EV` = `{"src": "trace" | "<path relative to the packet>", "ck": k, "step": n|null, "line": n|null, "quote": "verbatim"}`.
Flags take "yes" / "no" / "NA". Every FIRST failing test id in `results/` must appear in exactly one `failures`
entry (group tests with one shared cause). Include all checkpoints. Validate that the file is valid JSON
(e.g. `python3 -m json.tool <file> >/dev/null`) before finishing. Reply with one line: the path and the number of
checkpoints and failing tests coded.
