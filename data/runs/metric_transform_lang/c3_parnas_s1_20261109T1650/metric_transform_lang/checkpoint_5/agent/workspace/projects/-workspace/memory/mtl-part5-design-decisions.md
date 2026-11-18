---
name: mtl-part5-design-decisions
description: "Non-obvious interpretation choices made when implementing MTL Part 5 (versioning, resume, metadata, UDFs) in /workspace"
metadata:
  node_type: memory
  type: project
  originSessionId: 16849361-554b-49cf-979c-3ff609b2ae86
  modified: 2026-11-10T01:15:08.098Z
---

MTL CLI (/workspace/mtl.py + mtl_core/) is a multi-part spec series; Part 5 was implemented 2026-11-10.

Spec ambiguities resolved (keep consistent in later parts):
- Missing `mtl_version` header → exit 6; malformed header → exit 1; major ≠ 1 → exit 6.
- Declared minor < 1.5 → one `WARNING:version:...` line on stderr, printed only on success.
- Resume is snapshot-based: each consumed file is copied (content-addressed) to `<state-dir>/<pipeline>.snapshots/`; unchanged files are read from the snapshot, so output is byte-identical. Files no longer discovered are dropped from state.
- UDFs were never specified to me (Part 4 text unavailable); invented `--udf file.py` conventions: @udf decorator, UDFS table, register(registry), or annotated functions. Unreadable UDF file → exit 3, registration problems → exit 5.
- Metadata `inputs.sources` sorted by source name; bare programs use pipeline/source name "default".

**Why:** these were judgment calls on contradictory/vague spec text, not derivable from code.
**How to apply:** if a later part's spec clarifies any of these, revisit; otherwise preserve.
