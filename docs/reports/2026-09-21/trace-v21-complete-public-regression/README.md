# RTT complete-public regression

## Scope

- Starting Result40 source: `7170adaba59c4d8ddfbe62342d9b727a9ae98822`
- Candidate: `attack_defense_v2.1_execution_verified_proactive_provenance_complete_public`
- The candidate inherits the promoted Result40 provenance recipe. It changes only the execution review used to keep or resolve one active public execution issue.
- Regression scope is exactly `da-26-4` rep-002 in the Full and User arms. The other Result40 outliers are not rerun because the saved evidence did not establish the same RTT mechanism.

## Mechanism and repair

The saved Full trajectory contained a fresh successful execution, while the current public `trace.md` said the analysis completed and the current public `answer.txt` still said the fresh rerun did not complete. The old reviewer cited both files but resolved the issue from the execution witness.

The repair:

1. requires the execution reviewer to interpret all public deliverables jointly;
2. surfaces exact public lines containing current/fresh execution-status language in a host-derived locator summary;
3. keeps named external-database provenance execution-dependent unless the source was supplied with the task;
4. preserves the saved active issue text across harmless model paraphrases, while retaining new evidence and references.

No attacker, pair selector, proposer allocation, admission mathematics, solver, User simulator, judge, task input, revision budget, score definition, or audit definition changes.

## Verification

- Provider-free focused suite: 51 passed, 5 dataset-dependent tests deselected because the temporary clean checkout does not contain local BioMNIBench task data.
- New focused tests: 3 passed.
- Saved Full `da-26-4` rep-002 reviewer replay:
  - model: `gpt-5.6-luna`, low reasoning;
  - one call, first response valid, zero repair calls;
  - decision: `correct`;
  - active issue: `unresolved`;
  - the response cited both the success claim and the contradictory fresh-rerun-incomplete claim;
  - 36,969 input tokens, 477 output tokens, 6.37 seconds, estimated cost `$0.007966`.

## Targeted run

- Frozen seed/paraphrase/pretreatment inputs are the exact Result40 `da-26-4` sources.
- New output root: `/data/user_data/aydanh/rubric_gen/runs/rtt-complete-public-regression-20260921/`; the two response-free attempts made without the existing Babel key remain preserved under `study/`, while the authenticated run uses `study-authenticated/`.
- Revision concurrency: 2 assignment workers, aggregate provider concurrency 6, internal stage fanout 4.
- Audit will start only after both trajectories are inspected for the intended behavior. It will contain only the missing Sol+Opus judgments for the two new candidate artifacts.

Status: implementation and saved-case behavior validation passed. The first targeted
Babel attempt preserved all successful RTT-stage calls, then failed at solver turn 1
because the job copied the revoked shared `~/.codex/auth.json`. The sbatch entry point
now binds Babel's existing authenticated Red Team Codex home; only the two private
failed-turn credential copies are refreshed before native resume, so no completed
provider result is regenerated.
