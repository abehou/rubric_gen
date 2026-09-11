# attack_defense_v2 Result20 execution report

The one authorized production execution is incomplete. Job `10394194` used the frozen `attack_defense_v2` snapshot at commit `bbf109a9839beda05865c4967040497ed8fcb35e` and ran the complete declared scope of 120 trace assignments. The final ledger contains 118 completed assignments and two failed assignments, with no pending work. The compact machine-readable accounting is in [execution-status.json](execution-status.json) and the two retained failures are in [failures.csv](failures.csv).

## Coverage and outcome stage

| quantity | result |
|---|---:|
| scoped assignments | 120 |
| completed assignments | 118 |
| failed assignments | 2 |
| pending assignments | 0 |
| Full/User counted smoke assignments | 2, both passed execution-integrity checks |
| static/common preparation rerun | no |
| outcome-audit assignments started | 0 |
| v2 W, W_train, S, V2 H, A, gaps, RH | unavailable |

The smoke cases were `da-10-1/rep-001` in Full and User. They passed the execution-only smoke checks and were retained in the same production cohort. The run did not start the audit stage because the runner requires a complete, failure-free 120-assignment cohort before dispatching the authoritative Sol+Opus panel. Therefore no RH, W/S/H/A, gap, confidence interval, or threshold decision can be computed for v2 from this run. The v1 values remain historical context only and are not a v2 endpoint estimate.

The frozen audit panel would have been OpenAI `gpt-5.6-sol` plus Anthropic `claude-opus-5`; Gemini was not attempted and is outside any authoritative result. No outcome calls, audit recovery, or partial auditor substitution occurred.

## The two failures

Both failures are the same deterministic structural exception:

```text
ValueError: elicited criteria contain duplicate criterion titles
```

It escaped from `validated_induction_response` during candidate generation, through `elicit_rubric` and the v2 trace-defense path, while rendering a new active rubric. The failed cases were:

| task | replicate | arm | stage symptom |
|---|---|---|---|
| `da-15-2` | `rep-002` | Full | a compiled title duplicated an active criterion title |
| `da-14-8` | `rep-003` | User simulator | a compiled title duplicated an active criterion title |

The production log contains no provider timeout, transport failure, or API error for either case. Each assignment had already produced and persisted substantial solver/generation state before the next learning update failed. Read-only inspection of the sealed request ledger shows the corresponding compilation records are cache-valid under the frozen v2 contract and can contain a title already present in the active learned criteria. That makes a same-identity retry a replay of the same structural defect rather than compatible provider recovery.

The correct future handling is candidate-local: detect duplicate titles before active-rubric rendering, persist a structural/native candidate rejection, and allow the assignment to continue with its prior active rubric. This report does not apply that fix retroactively, alter the frozen recipe, or rewrite the two failed assignments.

## Preservation and recovery decision

The production snapshot, canonical V2 paraphrase pool, frozen seeds, offline g1 inputs, static outputs, common Full/User simulator and scoring settings, and all 118 successful trajectories remain unchanged. The two failed records and their partial saved state are retained on the compute run root:

`/data/user_data/aydanh/rubric_gen/runs/trace-attack-defense-v2-20260910/result20/`

No duplicate production job or recovery job was launched. The failures are non-retryable `ValueError` exceptions, and the frozen runner's provider retry contract does not classify them as operational provider failures. The detailed decision is in [recovery-decision.json](recovery-decision.json).

## Fixed-snapshot provenance

- experiment: `biomnibench-da-factorial-r10-d2237f051bbf`
- execution commit: `bbf109a9839beda05865c4967040497ed8fcb35e`
- production owner: `10394194`
- frozen execution manifest: `experiments/trace-attack-defense-v2/execution-freeze.json`
- readiness receipt: `experiments/trace-attack-defense-v2/receipts/readiness.json`
- production log: `experiments/trace-attack-defense-v2/production-10394194.log`

This is an incomplete developmental execution and has no efficacy pass/fail result. A new mechanical robustness snapshot would require separate authorization; it must preserve this cohort and distinguish any repaired run from it.
