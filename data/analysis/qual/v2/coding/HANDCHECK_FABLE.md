# Hand-check (Fable) of the 185-quote evidence sample

Question per item: does the quote, at the cited place, SUPPORT the code it is attached to (CODEBOOK.md)? Verbatim status was already machine-checked; this judges meaning only.
Verdicts: Y = supports; P = partial/weak (consistent with the code but would not establish it alone); N = does not support or contradicts.
Per-item verdicts: `coding/handcheck_fable.jsonl`.

## Counts

| group | Y | P | N | total |
|---|---|---|---|---|
| all | 154 | 31 | 0 | 185 |
| dim L | 29 | 3 | 0 | 32 |
| dim I | 23 | 12 | 0 | 35 |
| dim R | 15 | 6 | 0 | 21 |
| dim V | 38 | 6 | 0 | 44 |
| dim F | 49 | 4 | 0 | 53 |
| coder A | 124 | 22 | 0 | 146 |
| coder B | 30 | 9 | 0 | 39 |

## N items

(none)

## P items

- 2. P15 coder A `/checkpoints[2]/I/evidence/cross_internal[0]` (cross_internal=no): public `from . import inputs` is consistent with cross_internal=no but does not establish it alone
- 6. P15 coder A `/checkpoints[4]/R/instances[0]/evidence[0]` (R1): R1 claimed but quote shows new helper P.walk, not the reused code
- 7. P15 coder A `/failures[1]/evidence[4]` (F2): spec gives `recursive: true` only in an example; consistent with spec silence but weak alone
- 27. P24 coder A `/checkpoints[5]/V/evidence/V1[0]` (V1): V1 claimed but /tmp/ct probe exercises docker compose, closer to V4 reference
- 52. P33 coder A `/checkpoints[1]/I/evidence/read_internals[0]` (read_internals=yes): single-file whole Read; read_internals needs bodies far from the edit, quote is generic
- 53. P33 coder A `/checkpoints[1]/I/evidence/read_internals[1]` (read_internals=yes): same: whole-file Read does not show bodies far from edit
- 59. P33 coder A `/checkpoints[3]/I/evidence/read_internals[0]` (read_internals=yes): same whole-file Read; generic for read_internals
- 61. P33 coder A `/checkpoints[3]/R/instances[0]/evidence[0]` (R2): R2 copy must name both places; quote shows only add_dir os.walk
- 66. P44 coder A `/checkpoints[1]/I/evidence/read_internals[0]` (read_internals=yes): read of scopes.py+parsing.py; scopes.py edited in ck2, only parsing.py fits read_internals
- 67. P44 coder A `/checkpoints[2]/V/evidence/V7[0]` (V7): '51 tests pass' follows [3.32] altering existing test expectations; weak regression check
- 77. P50 coder A `/checkpoints[2]/R/instances[0]/evidence[0]` (R1): adding show_waste param to an existing ReportInput call is weak evidence of R1 reuse
- 81. P50 coder A `/checkpoints[5]/I/evidence/primary[0]` (I2): I2 modify evidenced only by a new `plan` def line
- 95. P54 coder A `/checkpoints[5]/I/evidence/read_internals[1]` (read_internals=yes): navigation.py and inference.py read were edited in ck6; only symbols.py fits read_internals
- 114. P68 coder A `/checkpoints[4]/V/evidence/V5[1]` (V5): 'o1 OK o2 OK o3 OK' after edit; comparison against spec examples not visible in quote
- 119. P84 coder A `/checkpoints[2]/I/evidence/primary` (I2): whole-file Write of existing output.py does not distinguish extend from modify
- 125. P84 coder A `/checkpoints[7]/V/evidence/V7[1]` (V7): V7 quote is a comment about rewriting test_cli setup, not a regression run
- 126. P84 coder A `/failures[0]/evidence[2]` (F2): spec line is the general required-assoc rule, not about site create synopsis
- 128. P84 coder A `/failures[4]/evidence[0]` (F2): Write of process.py does not show spec silence or test expectation
- 129. P84 coder A `/failures[6]/evidence[0]` (F2): `from .. import container` only partially supports the claim
- 130. P93 coder A `/checkpoints[1]/L/places[0]/evidence[1]` (L3): Edit quote is the edit itself; locating is shown by the [2.3] Read, not this step
- 131. P93 coder A `/checkpoints[1]/L/places[2]/evidence[1]` (L3): [2.17] heredoc replaces class Runtime body: an edit, not a locating step
- 140. P93 coder A `/checkpoints[7]/I/evidence/interface_change[2]` (interface_change=yes): interface_change evidence is the render_items call line; shows caller use only
- 147. P30 coder B `/checkpoints[1]/I/evidence/read_internals[0]` (read_internals=yes): whole-file cat of single-file industry.py; generic for read_internals
- 149. P30 coder B `/checkpoints[3]/R/instances[2]/evidence[0]` (R2): R2 copy needs both places; quote shows only one
- 150. P30 coder B `/checkpoints[4]/R/instances[2]/evidence[1]` (R2): R2 quote shows only render's loop, not SDE.output_quantity source
- 158. P44 coder B `/checkpoints[2]/V/evidence/V7[1]` (V7): '51 tests pass' after [3.32] sed changed existing expectations; weak regression check
- 163. P44 coder B `/checkpoints[5]/I/evidence/read_internals[1]` (read_internals=yes): cat navigation.py+locate.py; navigation.py edited in ck6, only locate.py fits read_internals
- 167. P44 coder B `/checkpoints[5]/R/instances[0]/evidence[1]` (R1): quote shows the new _namespace_entries helper, not the reused code
- 171. P93 coder B `/checkpoints[2]/L/places[1]/evidence[0]` (L4): Read at offset 600 after outline grep; paged reading, weak as L4 follow
- 175. P93 coder B `/checkpoints[4]/V/evidence/V1[0]` (V1): step is an edit plus inline probe using /tmp/t1 roots; V1 only partly shown
- 177. P93 coder B `/checkpoints[7]/I/evidence/interface_change[0]` (interface_change=yes): adds assoc_list field to Runtime; extension more than interface change

## Recurring P patterns

- read_internals supported by a whole-file read of a single-file project, or by a read batch where one of the files was later edited in the same checkpoint (52, 53, 59, 66, 95, 147, 163).
- R1/R2 quotes that show only the new or copied-to side, not the reused/copied-from code (6, 61, 77, 149, 150, 167).
- Locating (L) quotes that are the edit itself rather than the step that found the place (130, 131, 171).
- V7 'all tests pass' immediately after the agent changed existing test expectations (67, 158).
- Interface codes (I2, interface_change) evidenced by a def line, call line or added field that does not show an existing interface being changed (81, 119, 140, 177).
