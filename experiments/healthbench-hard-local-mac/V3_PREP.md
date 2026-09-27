# HealthBench Hard Dev3 v3 — prepared, not launched

The matched 3-task × 3-replicate × 4-condition study remains at three revision
turns. Solver, seeds, online W judge, simulated user, and RTT proposer use
`gpt-5.6-luna`; the solver/seed/W/simulator run at low effort. RTT's three
pair-assessment stages and criterion induction, plus the red-team generator,
run at high effort. Independent S/H/A and RH audit use `gpt-6-luna` at high
effort. The selected and development paraphrases are variants 0 and 1; variants
2–4 are three heldouts. This is the generic RTT, not BioMNI's execution-verified
research-trace defense.

The new task pool is `data/healthbench-hard/live-dev3-20260925-v3/`. Dev-001
replaces the internally contradictory car-seat rubric with source ID
`b947fc6f-1d50-4e3f-b679-8484529b787b`, the first reviewed nonconflicting
task after the disjoint Result20 reserve in the fixed metadata-stratified order.
Dev-002/003 and their source IDs are unchanged. The original v2 pool and results
are preserved.

After an approved run, `analyze_dev3_v3.py` will report the W/S/H/A and signed
W−S/S−H/H−A endpoint table, full-trajectory and final-artifact RH, and the raw
W score at initial, post-turn 1, 2, and 3. A turn that saves no new answer carries
forward its prior W; improved/regressed/unchanged assignment counts accompany
each step. S/H/A are independent audits at initial and final only; no intermediate
S/H/A curve is implied. Scores are not forced to improve every revision.

Cost estimate from the saved v2 Dev3 usage (6.45M input/0.243M output tokens,
$1.024 at all-5.6-Luna rates): about **7–9M input and 0.4–0.9M output tokens**,
or **$1.3–$2.3** at the configured mixed-model rates. We request approval for
up to **$3** and will pause at a safe stage boundary for renewed approval if
saved usage projects beyond it; high-effort RTT token usage, retries, and cache
behavior are the main uncertainty. The v2 audit portion was $0.349 with
5.6-Luna; its same-token price would be about $0.17 on 6-Luna, before added
heldout calls or high-effort output. These are saved-usage estimates, not billing
guarantees. Expected Mac wall time is 30–75 minutes versus 15m48s for v2.

The launcher `run_dev3_v3.py` uses one outer study queue, six assignment workers,
an aggregate provider cap of 12, internal fanout 4, and audit concurrency 12 on
the existing 12-core/24-GiB Mac. It uses only the confirmed OpenAI key; no paid
experiment has been started under v3. The stronger model and sign-aware prompts
target observed grade/feedback errors, but they do not guarantee semantic
validity, monotonic revisions, or a non-ceiling A score. Review saved criterion
reasons and answer changes before treating the table as a policy result.
