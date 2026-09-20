# BioMNIBench Results20 feedback-policy comparison

Status: **audit recovery in progress; scientific tables are not final**.

This run adds the two remaining feedback policies to the completed original20 Full/User comparison. It evaluates matched static and promoted RTT conditions for Semi and Score-only on the canonical twenty tasks, three replicates each. Scientific behavior is frozen at `attack_defense_v2.1_execution_verified_proactive_provenance`.

## Durable scope

- Experiment: `biomnibench-da-factorial-r10-2e389d4e31bb`
- Config: `experiments/trace-v21-execution-verified-provenance-result20-feedback/result20.yaml`
- Study: `/data/user_data/aydanh/rubric_gen/runs/rtt-result20-feedback-policies-20260920/study/biomnibench-da-factorial-r10-2e389d4e31bb`
- Sol/Opus audit: `/data/user_data/aydanh/rubric_gen/runs/rtt-result20-feedback-policies-20260920/audit/biomnibench-da-factorial-r10-2e389d4e31bb`
- Gemini audit: `/data/user_data/aydanh/rubric_gen/runs/rtt-result20-feedback-policies-20260920/audit-gemini/biomnibench-da-factorial-r10-2e389d4e31bb`
- Revision job `10510934`: 240/240 assignments complete, with 60 assignments in each of Semi static, Semi RTT, Score-only static, and Score-only RTT.

## Audit status at 2026-09-20 19:37 EDT

Gemini is complete after exact missing-only recovery:

- rubric: 1,657/1,657;
- absolute: 299/299;
- pairwise: 239/239;
- each RH window: 240/240;
- missing/invalid: zero.

The first Gemini-60 pass preserved partial results but hit the provider's input-token quota. Provider-free job `10514839` archived only 1,386 exact HTTP 429 failure receipts, preserving every successful judgment. Missing-only job `10514868` then completed at 12 workers in 15:16. This changed no judge request or scoring definition.

Sol/Opus recovery has preserved all successful records. Absolute (598/598) and pairwise (478/478) are complete. Provider-free replay recovered 184 previously paid Opus rubric responses, bringing rubric coverage to 2,952/3,314 and leaving 362 genuinely missing rubric judgments. The four RH windows still have 146, 113, 140, and 108 failed rows respectively; these are Opus-side missing work, while saved Sol judgments remain intact.

The remaining Opus requests are externally blocked by fresh Anthropic `credit balance is too low` responses. The audit will not repeatedly retry this permanent failure. When Anthropic access is restored, resume only the archived/failed Opus work, then run `report.sbatch`; the analysis refuses incomplete native audit coverage.

No scientific result is reported from a surviving-provider subset. Final outputs will include Sol+Opus, Sol, Opus, Gemini, and equal-weight three-model tables with W/S/H/A, all four gaps, all four RH windows, abstentions, paired deltas, and artifact/task-level exports.
