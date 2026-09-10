# Frozen rubric-cue final-artifact routing check

Read-only inspection of source0fbe0bb and all240saved final-artifact judgments (60static+60trace for each of Sol/Opus). All record final_artifact window, zero solver-feedback records, and max-score monitor aggregation. This verifies the saved evidence window and executed monitor family; raw provider request bodies are not stored alongside score.json, so no claim of direct wire-payload inspection is made.

## Verified source path

`submission_revision/evaluation/evidence.py` constructs artifact-specific instructions (sealed artifacts only, strongest innocent explanation, contrary evidence, blinded assessment) in EvidencePrompt.instructions. Its task_context contains only the task instruction. `detection/planning.py:plan_requests` sends detection==rh to `_plan_reward_hacking_requests` for either model. `detection/prompts.py:_reward_hacking_requests` constructs instructions from MALT_REWARD_HACKING_PROMPT plus task_context and generic transcript-chunk framing; it never reads payload.instructions. The forensic `direct_request` path uses payload.instructions but is not selected for rh.

Therefore the artifact-specific forensic instruction block is not passed by the RH request builder for either auditor. This is a routing/instruction mismatch; evidence remains final-artifact-only. It does not establish that missing instructions caused the near-zero RH rate, nor that the forensic categorical prompt can replace the monitor's0–10scale without changing semantics.

## Next minimum-stage action

Keep all existing results and active run unchanged. Prepare a separately versioned artifact-only routing candidate that preserves the current score schema/model/threshold unless independently calibrated evidence justifies change. Verify exact rendered instructions for both provider serializers without real calls, then evaluate against condition-blinded human-reviewed labels. Do not switch full-trajectory routing, rerun revisions, or adopt the candidate based on static-versus-trace ordering. Human labels remain outstanding.

Saved output roots: `runs/babel-result20-cue-contrast-20260908/{static,trace}/audit/biomnibench-da-factorial-r10-f0203f5d69f3/direct_final_artifact/`. Source checkout: `runs/babel-code/result20-cue-contrast`.
