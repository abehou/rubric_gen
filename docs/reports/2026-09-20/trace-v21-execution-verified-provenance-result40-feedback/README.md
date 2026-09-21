# BioMNIBench Results40 Semi/Score-only expansion

Status: **232/240 revisions preserved; execution blocked by confirmed external OpenAI credit exhaustion**.

This run extends the completed Results20 Semi/Score-only comparison to the same precommitted additional twenty tasks used by the completed Full/User Results40 experiment. It preserves the promoted `attack_defense_v2.1_execution_verified_proactive_provenance` treatment and matched static definitions. The user selected GPT-5.6 Sol and Gemini 3.8 Flash for this expansion audit; the separate incomplete Results20 Opus recovery is not part of the completion gate.

## Frozen scope

- New block: 20 tasks × 3 replicates × 4 conditions = 240 assignments.
- Conditions: Semi static/RTT and Score-only static/RTT.
- Native layout: one static and one trace shard per task, six assignments per shard.
- Frozen inputs: the exact Results40 new20 seeds and five paraphrase variants.
- Trace pretreatment: single-layer native reuse from the nine original compatible producers where recorded, and from the completed Full/User Results40 trace studies for the other eleven tasks; no g1 regeneration.
- Revision profile through job `10520270`: three shards × six assignment workers, at most 18 assignment workers, aggregate provider cap 60, and internal RTT fanout 4. That owner advanced coverage from 208 to 232 before one remaining assignment's two analysis processes exceeded the 256-GiB allocation by themselves. The bounded tail recovery therefore uses one shard at a time, 512 GiB, and up to three missing-only passes in one allocation; scientific requests are unchanged.
- Audit: Sol and Gemini run concurrently as independent provider tracks; Sol uses at most 60 workers and Gemini uses three workers under their existing provider partitions.
- Persistent root: `/data/user_data/aydanh/rubric_gen/runs/rtt-result40-feedback-policies-20260920`.
- Bundle: `experiments/trace-v21-execution-verified-provenance-result40-feedback/`.

The final report will show new20 and cumulative40 separately for Sol, Gemini, and their equal-weight panel. Original20 assignments and judgments are reused read-only and are not rerun.

## Provider-free gate

Slurm job `10516052` completed in nine seconds with zero provider calls. It validated exactly 240 assignments, the disjoint precommitted new20 membership, all frozen seed/paraphrase roots, 20/20 native pretreatment sources, diagnosis-only high proposer reasoning, the absence of dropout/alternate candidates, writable experiment-owned NAS8 roots, and the exact Sol+Gemini audit panel. The durable receipt is `experiments/trace-v21-execution-verified-provenance-result40-feedback/receipts/input-validation.json`.

Initial revision owner `10516093` was stopped after the first static shards consistently failed before a remote judgment because the private runner had not loaded the existing `OPENAI_API_KEY` needed by the unchanged semi/score-only optimizer judge. Exact stdout reported `OPENAI_API_KEY must be set`; the failed judge attempts contain no provider result. The execution-only repair loads OpenAI for revision and OpenAI+Gemini for audit, matching the completed Results20 feedback runner while excluding Anthropic from this run. Native resume removes invalid response-free evaluation trees and preserves any completed state.

Recovery owner `10516159` then reached the native studies but NAS1 home was at its byte quota, so the shared runtime journal could not persist events. The owner was stopped before allowing this operational failure to multiply. Provider-free inspections `10516389`, `10516448`, and `10516459` found 108 failed, 12 interrupted, and 6 pending records across the 21 shards that had started. All 192 saved RTT attempts have `provider_failure` status, no saved provider output, and no `result.json`: 182 carry the exact home-quota `OSError`, while ten retain the earlier exact missing-credential `RuntimeError`. The first recovery attempt `10516432` rejected those ten distinct signatures without changing state or launching a provider call. The corrected recovery archives only these two verified response-free classes before native missing-only resume and adds a tiny runtime-directory write probe before any later provider work. Seven focused tests pass. No scientific prompt, model, condition, input, or scoring behavior changed.

Missing-only owners subsequently brought the durable cohort to **208/240**. Job `10517651` completed every long-running tail it could and exited with 32 runtime failures: 28 app-server startup failures before any model turn, three reconstructible `workspace-restore` directories left by preemption, and one ordinary timed-out solver turn retained for the existing native failed-turn recovery. The scoped reconciliation restores only dead job-local Codex `tmp` links, archives only the three named restore directories, and rearms only the 28 exact pre-turn failures. It does not clear any provider response, trajectory, completed assignment, or scientific artifact; 10 focused tests pass.

Recovery `10520270` preserved those 208 assignments and completed 24 more. Before its final OOM, the remaining tail comprised three Codex app-server startup failures before a model turn, one native timeout, two transient NAS8 reads, one transient malformed-reminder read, and the then-running heavy cell. The malformed reminder file was subsequently readable as valid JSON, so it was not rewritten. The execution-only tail fix reconciles only a dead link made by this exclusive Codex home, relocates reconstructible Codex cache writes to node-local storage, performs at most three native missing-only passes, and raises the one-shard allocation to 512 GiB. Twenty-four focused tests pass; prompts, models, condition identity, retries, and all completed artifacts remain unchanged.

High-memory owner `10522419` confirmed that the resource change works: the allocation received 512 GiB and peaked at 117.8 GiB before it was deliberately canceled, rather than being OOM-killed. Its first `da-20-4` trace pass then returned three byte-preserved `RateLimitError` receipts with `insufficient_quota` / `credit_balance_exhausted`; all three have no output or result. The same external blocker appears in the pending `da-20-1` static optimizer-judge receipt. Repeating the remaining recovery passes could not succeed and was stopped; dependent audit `10522421` never started and made no judgment call.

The exact durable revision state is 232 completed, six failed, and two interrupted-running records that native resume will reclaim. The eight missing assignments occupy four shards: `da-20-1/static`, `da-20-4/static`, `da-20-4/trace`, and `da-4-1/trace`. Two failed solver checkpoints record the exact `[Errno 4] Interrupted system call` boundary before top-level trajectory publication. The tested recovery archives the private attempt evidence, restores the last scored workspace, discards the uncertain session, and retries only that assignment. Three exhausted response-free proposer requests can be rearmed by `rearm_operational.sbatch` only after the existing OpenAI route has credits again.

Resume after credit restoration:

```bash
sbatch experiments/trace-v21-execution-verified-provenance-result40-feedback/rearm_operational.sbatch
sbatch --cpus-per-task=16 --mem=512G \
  --export=ALL,RESULT40_EXPECTED_CPUS=16,RESULT40_SHARD_WORKERS=1,RESULT40_ASSIGNMENT_WORKERS=6,RESULT40_RECOVERY_PASSES=3 \
  experiments/trace-v21-execution-verified-provenance-result40-feedback/revise.sbatch
```

After revision reaches 240/240, submit the existing audit launcher with 16 CPUs and `RESULT40_EXPECTED_CPUS=16`. It runs the requested Sol and Gemini tracks missing-only; no Opus work is part of this completion gate.
