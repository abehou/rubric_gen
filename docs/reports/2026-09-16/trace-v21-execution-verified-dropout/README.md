# Execution-verified v2.1 with RTT-adapted Rubric Dropout

## Scope

- Starting branch: `codex/trace-task-paraphrase-local-mac`
- Starting commit: `2367337d26a79fa7d7a0e4f572d9855843a5c0bb`
- Frozen predecessor execution commit: `2768c070c0dc1bb9e5892a67254dde93bd1cf318`
- Scientific identity under development: `attack_defense_v2.1_execution_verified`
- Conditions: repaired 0%, 30%, and 50% dropout; Full and User feedback in each condition
- Canonical scope after saved-case checks: `da-3-4`, `da-11-1`, `da-18-1`; three replicates; seed `20260806`; 54 assignments
- Final audit: unchanged Sol+Opus definitions

## Starting evidence

The completed durable-delivery Dev3 delivered all 89 correct execution reminders, but the User `da-11-1` trajectories still converted failed, stale, or absent executions into confident result claims. The repair therefore targets execution truthfulness rather than the numerical gaps directly. The Full `da-11-1` rep-001 trajectory is the required counterexample: retracting unsupported significance and explicitly reporting non-execution is a legitimate repair and must remain acceptable.

## Status

### 22:37 JST implementation checkpoint

The new `attack_defense_v2.1_execution_verified` identity now preserves the
v2.1 learner, attacker, pair selector, admission, penalties, simulator, solver,
and outcome definitions while changing two scientific behaviors established by
the saved trajectories:

- one complete execution issue is delivered with its requirement, concrete
  defect, public evidence, feasible repair, supported work to preserve, and an
  honest-downgrade alternative;
- a host-produced post-feedback command/file delta keeps that same issue active
  until fresh consistent execution or an explicit withdrawal resolves it.

An honest downgrade consumes that review opportunity and is not immediately
followed by another learned reminder. This preserves the Full `da-11-1`
rep-001 counterexample instead of pressuring it back into a completion claim.

RTT-adapted dropout is implemented only on the solver-facing revision signal.
It uses deterministic fixed-count masks, nests 30% within 50% when the active
set is identical, retains at least three positive base criteria, includes active
learned penalties/reminders in the eligible set, and never masks the one active
execution contradiction. Canonical scoring and final evaluation remain full.

The canonical config resolves to 54 assignments under experiment identity
`biomnibench-da-factorial-r10-2f8f9cee1a53` and reuses the exact local Dev3
seeds, paraphrases, task data, and compatible generation-1 pool.

Provider-free status:

- 16 new execution/dropout tests and the directly affected suite pass;
- 122/122 focused execution/config tests pass;
- the broad relevant suite has 381 passes and two passing subtests;
- three unrelated existing assertions fail: two expect obsolete Results20
  paraphrase paths in untouched configs, and one compares untouched
  `feedback.py` with old commit `c866831` rather than current HEAD.

### 23:22 JST route and saved-case checkpoint

The local route smoke passed through the actual Codex/Luna provider path with
persisted output, session state, and local runtime coordination. Its estimated
usage cost was `$0.004147`; no Slurm state or alternate API route was used.

All four bounded saved cases now pass:

| Case | Outcome | New execution | Truthfulness result |
|---|---|---|---|
| User `da-11-1` rep-001 | coherent rerun | `run_authoritative.py`; exit 0; 26 LR rows | final counts and p-values match the fresh output; unsupported HVG/PC/cluster/bootstrap claims removed |
| User `da-11-1` rep-002 | honest downgrade | no fake rerun | retained-zero QC and observed 10/12 permutation result disclosed; 67,184-cell and 12/12 claims withdrawn |
| User `da-11-1` rep-003 | coherent rerun and persistent closure | fresh genome-wide run plus two same-session checks | converged in three turns to 67,286 final-QC cells, 18,540 genes, 4,000 graph cells, finite coordinates, and one component; stale 14-community and embedded NetworkX claims removed |
| Full `da-11-1` rep-001 | honest downgrade preserved | corrected code added but explicitly not executed | no p/q/significance result claimed; supported descriptive results and limitations preserved |

Rep-003 exposed one additional concrete defect before the full batch: a solver
could synchronize headline values while leaving a superseded embedded program
labelled as the current implementation. The delivery block now explicitly
requires synchronization of executable code, embedded excerpts, generated
output, trace, and answer. The same protected issue remained active through the
third and final bounded revision, where the contradiction was removed. The
focused provider-free suite is now 17/17 for this behavior.

Saved-case session costs are not additive by turn within a resumed session.
Using each session's final cumulative estimate, the four behavior cases cost an
estimated `$0.235934`: `$0.032535`, `$0.028298`, `$0.133133`, and `$0.041968`.
The canonical 54-assignment Dev3 and its audits remain unlaunched pending the
final focused-suite rerun and local missing-only runner validation.

### 23:29 JST canonical Dev3 launch

The final direct suite passed 42/42 and the broad affected suite passed 481
tests plus two subtests. Its only three failures are the already-recorded
unrelated assertions over untouched historical Results20 Babel paths and an
old-commit byte comparison for unchanged shared `feedback.py`.

Canonical Dev3 launched under invocation
`execution-verified-dev3-20260916T142838Z-2f10a4a4` with 15 stage assignment
workers, aggregate provider capacity 8, and one serialized audit-study slot.
The 24-GB Mac reported 50% free memory before launch and 44% after all 15
assignment workers entered the study. Initial status is 15 running, 39 pending,
zero completed, and zero failed.

- experiment: `biomnibench-da-factorial-r10-2f8f9cee1a53`
- config SHA-256: `a203853d60313da0704537cd80f25a5ea05773d7fd04edb08ab4a4d1c2380889`
- Git HEAD: `2367337d26a79fa7d7a0e4f572d9855843a5c0bb`
- tracked dirty diff SHA-256: `76793de91934bc340df19ffe86860d233acd3973adfe25e9ccbf10e5f9ce991f`
- complete scientific source manifest SHA-256: `29d8129615ec2992b5d76dc30020e629b0270a648b13002a384d1d6947adf7f3`
- seed/paraphrase/generation-1 tree SHA-256: `89df333c…`, `58050f4b…`, `dbd8fd80…`
- resume mode: native missing-only; initial launch created a new study

Sol+Opus audit remains gated on all 54 completed revisions.

### 23:42 JST reviewer-route recovery

The initial owner was stopped after zero assignments completed: 17 assignments
failed at their first execution-enforcement request, 11 were interrupted, and
26 had never started. Every failed request contained four zero-duration,
zero-response attempts with the same local configuration error:
`OPENAI_API_KEY must be set`. This was not a model, schema, memory, or scientific
failure. The first Mac runner had omitted the credential injection present in
the historical v2.1/Babel runners for the canonical direct structured reviewer.

No alternate provider was introduced. The existing v2.1 route remains Codex
sessions for solver/attacker/simulator and direct OpenAI structured
`gpt-5.6-luna` for the rubric learner and execution reviewer. All 17 failed
request directories were moved intact to assignment execution archives, with
zero provider responses to preserve, then rearmed for native missing-only
resume. Two provider-free recovery checks pass and refuse to touch any other
failure class or a request containing a response.

One archived enforcement request was reconstructed byte-for-byte: public-source
hashes, prompt hash, evidence hash, schema order, and final request key
`43059992ca97…` all match the original. The exact real reviewer smoke passed on
its first response with valid schema/evidence binding, effective model
`gpt-5.6-luna`, decision `pass`, and estimated cost `$0.004575`.

Resume invocation `execution-verified-dev3-20260916T144029Z-0ca08697` now uses
source manifest `6f738c2e92dddbc7ee7b59105d64497df62528df3f1cec2250a2035a7ea88e84`.
The 13 ledger rows still labelled failed immediately after resume are rearmed
old/interrupted rows waiting behind the 15 active workers, not new failures.
