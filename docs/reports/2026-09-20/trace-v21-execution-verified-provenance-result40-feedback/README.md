# BioMNIBench Results40 Semi/Score-only expansion

Status: **208/240 revisions preserved; exact runtime-residue reconciliation ready**.

This run extends the completed Results20 Semi/Score-only comparison to the same precommitted additional twenty tasks used by the completed Full/User Results40 experiment. It preserves the promoted `attack_defense_v2.1_execution_verified_proactive_provenance` treatment and matched static definitions. The user selected GPT-5.6 Sol and Gemini 3.8 Flash for this expansion audit; the separate incomplete Results20 Opus recovery is not part of the completion gate.

## Frozen scope

- New block: 20 tasks × 3 replicates × 4 conditions = 240 assignments.
- Conditions: Semi static/RTT and Score-only static/RTT.
- Native layout: one static and one trace shard per task, six assignments per shard.
- Frozen inputs: the exact Results40 new20 seeds and five paraphrase variants.
- Trace pretreatment: single-layer native reuse from the nine original compatible producers where recorded, and from the completed Full/User Results40 trace studies for the other eleven tasks; no g1 regeneration.
- Revision profile: three shards × six assignment workers = at most 18 assignment workers, aggregate provider cap 60, internal RTT fanout 4. The earlier four-shard recovery reached the 256-GiB memory ceiling, so this execution-only reduction preserves the scientific requests while avoiding another OOM.
- Audit: Sol and Gemini run concurrently as independent provider tracks; Sol uses at most 60 workers and Gemini uses three workers under their existing provider partitions.
- Persistent root: `/data/user_data/aydanh/rubric_gen/runs/rtt-result40-feedback-policies-20260920`.
- Bundle: `experiments/trace-v21-execution-verified-provenance-result40-feedback/`.

The final report will show new20 and cumulative40 separately for Sol, Gemini, and their equal-weight panel. Original20 assignments and judgments are reused read-only and are not rerun.

## Provider-free gate

Slurm job `10516052` completed in nine seconds with zero provider calls. It validated exactly 240 assignments, the disjoint precommitted new20 membership, all frozen seed/paraphrase roots, 20/20 native pretreatment sources, diagnosis-only high proposer reasoning, the absence of dropout/alternate candidates, writable experiment-owned NAS8 roots, and the exact Sol+Gemini audit panel. The durable receipt is `experiments/trace-v21-execution-verified-provenance-result40-feedback/receipts/input-validation.json`.

Initial revision owner `10516093` was stopped after the first static shards consistently failed before a remote judgment because the private runner had not loaded the existing `OPENAI_API_KEY` needed by the unchanged semi/score-only optimizer judge. Exact stdout reported `OPENAI_API_KEY must be set`; the failed judge attempts contain no provider result. The execution-only repair loads OpenAI for revision and OpenAI+Gemini for audit, matching the completed Results20 feedback runner while excluding Anthropic from this run. Native resume removes invalid response-free evaluation trees and preserves any completed state.

Recovery owner `10516159` then reached the native studies but NAS1 home was at its byte quota, so the shared runtime journal could not persist events. The owner was stopped before allowing this operational failure to multiply. Provider-free inspections `10516389`, `10516448`, and `10516459` found 108 failed, 12 interrupted, and 6 pending records across the 21 shards that had started. All 192 saved RTT attempts have `provider_failure` status, no saved provider output, and no `result.json`: 182 carry the exact home-quota `OSError`, while ten retain the earlier exact missing-credential `RuntimeError`. The first recovery attempt `10516432` rejected those ten distinct signatures without changing state or launching a provider call. The corrected recovery archives only these two verified response-free classes before native missing-only resume and adds a tiny runtime-directory write probe before any later provider work. Seven focused tests pass. No scientific prompt, model, condition, input, or scoring behavior changed.

Missing-only owners subsequently brought the durable cohort to **208/240**. Job `10517651` completed every long-running tail it could and exited with 32 runtime failures: 28 app-server startup failures before any model turn, three reconstructible `workspace-restore` directories left by preemption, and one ordinary timed-out solver turn retained for the existing native failed-turn recovery. The scoped reconciliation restores only dead job-local Codex `tmp` links, archives only the three named restore directories, and rearms only the 28 exact pre-turn failures. It does not clear any provider response, trajectory, completed assignment, or scientific artifact; 10 focused tests pass.
