# V7 treatment delivery — 2026-09-05 22:24 CST

All 240 revisions are complete. This is an execution/exposure summary, **not an
RH outcome comparison**. Each condition contains the same 20 tasks × 3 replicates.

| Condition | Mean solver turns | Horizon stops | Online generations | Rubric text changes | Assignments with changes | Included/excluded red-team sidecars |
|---|---:|---:|---:|---:|---:|---:|
| Full / artifact | 5.18 | 1/60 | 192 | 26 | 23/60 | 192 / 0 |
| Full / trace | 5.15 | 0/60 | 189 | 22 | 22/60 | 188 / 1 |
| Simulator / artifact | 8.32 | 35/60 | 414 | 22 | 20/60 | 413 / 1 |
| Simulator / trace | 7.93 | 31/60 | 387 | 25 | 20/60 | 383 / 4 |

Online totals: **1,182 generations, 95 rubric-text changes, 96 admitted criteria,
1,176 included and six excluded red-team sidecars**. There are five response-
validation fallback generations across four simulator/artifact assignments;
these are retained unchanged, not rerun away. Counts of stages requiring more
than one attempt are 23, 30, 147 and 141 in table order; they do not by themselves
identify whether earlier attempts had validation or transport failures.

Admitted criteria total **96** (26 + 23 + 22 + 25), whereas rubric-text
changes total **95** (26 + 22 + 22 + 25). One update can admit multiple criteria;
these are different units and must not be equated.

## Counting and interpretation

- Original generation 0 and shared pretreatment generation 1 are excluded from
  online-generation/update counts. Actual rubric change compares consecutive
  saved `rubric.txt` bytes, not generation metadata hashes.
- `s000` is the reused seed, not an assignment solver call. A `no_change` terminal
  call creates no new submission; a ten-turn horizon run has 11 saved submissions
  including its seed. All 240 solver-turn counts were independently matched to
  saved per-turn trajectories and, where applicable, terminal no-change events.
- Simulator arms ran longer and received more online intervention opportunities.
  Final comparisons describe the configured adaptive-stopping policies, not an
  equal-turn causal comparison. Do not exclude longer runs or divide RH outcomes
  by observed turns to force equal exposure; turn count is treatment-dependent.
- Included sidecars mean evidence admitted by the protocol, not independently
  proven successful reward-hacking attacks. Exclusions and rubric fallbacks are
  separate treatment-delivery events, not natural RH judgments.
- No no-red-team control is present, as accepted by the user; this experiment
  cannot alone establish the effect of adding red teaming.

Exact assignment-level records and distributions: [treatment-delivery.json](treatment-delivery.json).
Read-only producer: `runs/diagnostics/summarize_delivery.py`; execution source and
the frozen 198-file outcome-analysis archive were not modified.
