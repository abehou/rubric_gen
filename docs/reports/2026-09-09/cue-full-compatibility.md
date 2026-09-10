# Full-feedback reuse decision for the frozen rubric-cue Result20

2026-09-09 20:10 EDT. Provider-free provenance job10379227 completed; job10379209 failed only because this diagnostic initially looked for master rubric at task/rubric.txt instead of the canonical task/tests/rubric.txt. Historical data and outputs were never changed.

## Decision

**Reuse the completed earlier full-feedback static arm. Do not reuse the earlier full-feedback trace arm as an exact cue-policy counterpart. Run only the missing full-feedback trace arm (60 assignments).** Retain the earlier trace as historical policy evidence, with its original identity.

Scientific equivalence of the static execution path is established below; whole-repository hashes are not identical and are not being represented as identical. No historical resume metadata is fabricated or outputs relabeled. A combined analysis will reference the original static producer directly.

## Inputs and configuration

All four arms have the same20tasks×3replicates, randomization seed20260820, selected variant0, development variant1, heldout variants2–4, and master task/tests/rubric.txt. Every assignment manifest was compared field by field; actual instruction/master/variant file hashes were rechecked. Saved initial-artifact/data hashes are compared to native-validated completed analysis and manifest records; the large task dataset is not redownloaded or independently rehashed by this metadata check.

| Item | Comparison |
|---|---|
| Task/replicate inventory | All60keys identical; aggregate SHA below |
| Selected/master/development/heldout | All hashes identical for every task/replicate; all100paraphrase files and20master rubrics verified (repeated across replicates) |
| Seeds and initial artifacts | All60seed and initial-rendered-submission hashes identical |
| Task instruction/data identity | All60manifest identities identical; instruction bytes verified |
| Solver/seed/red-team generator | gpt-5.6-luna, codex, low reasoning, unchanged retry/timeout/service settings |
| Weak judge/proposer | gpt-5.6-luna; proposer max_retries5 |
| Outcome judge/auditors | GPT-5.6 Sol and Claude Opus5, same provider implementation/settings; Gemini configured but not executed |
| Scoring identity | Full-rubric-structured, selected rubric, trace review, unlimited max_review_chars; all initial scoring identity objects equal |
| Solver prompt implementation | e3f0c1ad59899ab81252d03aef3984e93c69c535a1f3f0aa066078e97e53e788 in every assignment manifest |
| Full-feedback projection | feedback.py identical SHA65f9f5bf177b5732f79d62c0abf3e3994232d552d18c17fcc8bf2052ad817324 |
| Solver prompt module | prompts.py identical SHA3864e1b0fdf011fd34dc53615f4747b2efcb486b48336ab7e08e9bfaa35074ff |
| Provider request/model settings | runtime/llm.py identical SHAefcd6677718bfe5c90f35fc12f7fc32764c9d7b80acf049964d5645b19d800e5 |
| Revision limits | min5/max10; same base profile, selected-base-plus-active-penalties-v1 feedback reference |
| Policy enum | fixed for both static arms; red_team_trace for both trace arms, but implementation differs |
| Simulator | Earlier full arms have no simulator invocation; cue disclosure cannot alter their full-feedback branch |

Aggregate hashes use sorted task/replicate records and canonical JSON; raw receipt provides per-cell hashes and every manifest difference.

- inventory_sha256: `c357a4ba431735bae8754bc84fa08f9fb6973d4341d3382a0763fe222aad38fc`
- rubrics_sha256: `42bf5bec9a8b71f10e85fc31a22b14c4549d2311b7f7af7e779aeed68d9b7df6`
- initial_inputs_sha256: `81dd379ffd1f4629fd58dd74c1846b694c14258f149952fee4ea6137309e3b69`

## Every archived source difference

All launch source/config seals pass, including initial and recovery invocations. Earlier full arms used409104f initially,6535840for static recovery, and1f995df for final trace recovery, with b4d751d among earlier trace attempts; cue uses0fbe0bb. Operational recovery versions remain explicit. Full source hashes and invocation-specific differences are in the JSON receipt; the accompanying patch contains the complete original409104f→cue0fbe0bb src diff.

| Changed module | Relevance |
|---|---|
| runtime/capacity.py | Operational: nonblocking observational sampling, event journaling, shared Anthropic input-token pacing; provider ceiling remains60 |
| runtime/agents/codex_app_server.py | Operational: relocate CLI temporary locks from NFS; later earlier-arm recoveries already use this. Task temporary/session semantics preserved |
| controller.py | Recovery bookkeeping: refresh submission count after a sealed final turn |
| controller_recovery.py | Recover effective model only from matching completed provider receipt; refresh counts |
| controller_scoring.py | Remove unused early-red-team branch; remove optional user-simulator execution-context wrapper. Full fixed and ordinary trace projection logic unchanged |
| experiment.py | Remove unused optional simulator flags/online-contrast/early policy interfaces; active YAML does not select them |
| rubric_generation.py | Remove unused policy enum variants; fixed and ordinary trace behavior unchanged |
| pretreatment_rubrics.py | Remove unused online-contrast supported enum |
| evolution_request.py | Remove unused policy enum alternatives |
| study_validation_artifacts.py | Corresponding unused early-policy validation removal |
| contrasts.py | Remove unused online-contrast branch |
| evolution.py | Remove unused contrast-induction selection; adjust bounded provider-failure budget accounting |
| evolution_protocol.py | Scientific trace difference: additional contrast-specific observable-defect induction instructions; deduplicate artifact evidence into a referenced table |
| evolution_assessment.py | Trace input presentation difference: complete artifacts supplied once in a table with pair references rather than repeated per pair |
| red_team.py | Scientific trace difference: replace mutually consistent analytical-error sidecars with judge-visible evidence-support mismatch sidecars; remove unused initial/early API |
| evolution_provider.py | Proposer output cap32768→65536 tokens, request cap1→4MiB |
| evolution_stage.py | Separate transport failures from valid-response repair attempts; bounded backoff and permanent-error stop |
| evolution_validation.py | Four parallel independent artifact validations; preserved combination order and global provider limiter |
| user_simulator.py | Scientific user-only cue disclosure plus removal of unused optional execution-context/single-issue/package flags |

These changes do not induce, generate or apply extra criteria in fixed-policy full feedback. Static generation-implementation fingerprints differ because that fingerprint includes unused policy code; selected generation bytes, selected scoring identity and full-feedback prompt are unchanged. This is sufficient for scientific static reuse, not byte-identical repository claims. Trace invokes the changed sidecar, induction and assessment path; same enum name is insufficient for reuse.

## Minimum missing-arm decision note

1. **Verified mismatch:** earlier trace uses different sidecar/proposer scientific inputs. This is a provenance mismatch, not a newly inferred behavioral mechanism.
2. **Exact change:** evaluate the already frozen0fbe0bb cue trace policy with feedback_policy=full. No new red-team policy or simulator prompt. The other three existing cells remain untouched.
3. **Reuse:** existing full-static outcomes; cue user-static/user-trace outcomes; exact60seeds,100paraphrases and canonical task files. Native pretreatment_source reuses all20sealed cue-trace starting rubrics and cached judgments with provenance validation, not a new induction stage.
4. **Why revisions:** full feedback changes information shown to the solver at each turn; existing user trajectories cannot be relabeled as full feedback and old full-trace used a different policy. Revise/detect only this60-assignment arm; no seed/paraphrase regeneration.
5. **Success/report criteria:** complete60assignments and120Sol/Opus audit rows with matched initial inputs and frozen evaluators; report all outcomes regardless of direction. Policy goals remain RH reduction plus nonworsening W−S/W−A and no material holistic loss; completion of this counterpart is not itself policy success. S−H is secondary, not a simulator-tuning target.
6. **Stop rule:** fail before providers on any incompatible input/source. Preserve successful cells; bounded native recovery only for verified transport failures. No automatic new policy or simulator iteration if outcomes are adverse.

## Baseline freeze and measurement boundary

The cue user static baseline is provisionally accepted and frozen: trajectory RH20%, W−S7.34, H−A11.65, W−A19.11, A70.48. S−H0.12 is compatible with wording-only paraphrase generalization; do not alter disclosure to inflate it. Retain original trace's20%→7.5% trajectory reduction while eliminating W−S/W−A regressions as the remaining primary policy objective.

Final-artifact calibration remains an independent blinded human-review audit-only task. Existing artifacts will be reused uniformly; no revision rerun is justified by audit changes. No calibrated final-artifact mitigation claim is made here.

## Files and execution

Machine-readable evidence: cue-full-compatibility.json (local-only: `docs/reports/2026-09-09/cue-full-compatibility.json`; hash recorded in the local-evidence manifest). Full source diff: [archived source differences](../../../investigation/cue-full-compatibility-20260909/archived-source.diff). Configuration and native input gate: investigation/cue-full-compatibility-20260909. New large artifacts go only to /data/user_data/aydanh/rubric_gen/runs/result20-cue-full-trace-20260909; compute-only access through Slurm. Static reuse retains its home historical output paths unchanged.

### Scoped reuse execution fix

Native validation10379233 rejected the unchanged source ledger status completed_scope. Separate frozen branch `babel-cue-full-counterpart-20260909`, commit `314ea3d`, backports only the existing scoped-completion ledger check from7567750 and its focused tests onto0fbe0bb. All14tests pass; the sole src difference is pretreatment_reuse.py. No prompt, scoring, policy, identity or historical metadata changes. Validation10379252 checks real pool reuse with providers forbidden.

Native input validation10379252 passed60seeds, sealed paraphrases and20cached starting rubrics with providers forbidden. Missing full-trace job**10379267** submitted with4CPU128GiB48h, account-free preempt/preempt_cpu_qos, stage workers60 under shared aggregate60. Frozen scientific source0fbe0bb plus reuse-only fix314ea3d; no experimental implementation from the dirty main worktree is used.
