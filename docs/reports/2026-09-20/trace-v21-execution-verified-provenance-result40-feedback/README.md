# BioMNIBench Results40 Semi/Score-only expansion

Status: **provider-free preparation; no new assignment call has started**.

This run extends the completed Results20 Semi/Score-only comparison to the same precommitted additional twenty tasks used by the completed Full/User Results40 experiment. It preserves the promoted `attack_defense_v2.1_execution_verified_proactive_provenance` treatment and matched static definitions. The user selected GPT-5.6 Sol and Gemini 3.8 Flash for this expansion audit; the separate incomplete Results20 Opus recovery is not part of the completion gate.

## Frozen scope

- New block: 20 tasks × 3 replicates × 4 conditions = 240 assignments.
- Conditions: Semi static/RTT and Score-only static/RTT.
- Native layout: one static and one trace shard per task, six assignments per shard.
- Frozen inputs: the exact Results40 new20 seeds and five paraphrase variants.
- Trace pretreatment: single-layer native reuse from the nine original compatible producers where recorded, and from the completed Full/User Results40 trace studies for the other eleven tasks; no g1 regeneration.
- Revision profile: four shards × six assignment workers = at most 24 assignment workers, aggregate provider cap 60, internal RTT fanout 4.
- Audit: Sol and Gemini run concurrently as independent provider tracks; Sol uses at most 60 workers and Gemini uses three workers under their existing provider partitions.
- Persistent root: `/data/user_data/aydanh/rubric_gen/runs/rtt-result40-feedback-policies-20260920`.
- Bundle: `experiments/trace-v21-execution-verified-provenance-result40-feedback/`.

The final report will show new20 and cumulative40 separately for Sol, Gemini, and their equal-weight panel. Original20 assignments and judgments are reused read-only and are not rerun.
