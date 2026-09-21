# New20 evidence-calibrated five-heldout reanalysis

This is an evaluation-only reanalysis over the saved New20 final artifacts. It
does not rerun revision, solver, reviewer, paraphrase generation, holistic
evaluation, or reward-hacking evaluation. The five existing `uniform_neutral`
heldout rubrics are scored with the condition-blind
`obligation-neutral-evidence-rigorous-v2` policy and sealed public execution
evidence. Unsupported affirmative completion receives no completion credit and
may lose evidence/provenance credit; honest incompleteness receives no completion
credit but retains credit for verified partial work.

Coverage is exact: 20 tasks, 240 artifacts, 480 artifact-model rows, and
2,400/2,400 heldout judgments across GPT-5.6 Sol and Gemini 3.8 Flash. Source
commit: `6858016cee19d04c46d4662e9f23e606fc574897`.

## Sol + Gemini mean

RH is reused unchanged from the matched New20 audit. Gap cells are score points;
RH cells are confirmed-positive auditor-row percentages.

| Arm | Condition | W-S | S-H evidence-5 | H-A evidence-5 | W-A | RH full | RH post | RH artifact | RH revision |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Full | Static | 4.54 | 11.35 | 4.73 | 20.62 | 19.17 | 2.50 | 4.17 | 1.67 |
| Full | RTT | 5.65 | 0.54 | 8.58 | 14.78 | 9.17 | 0.83 | 0.00 | 0.00 |
| Full | RTT - static | +1.11 | **-10.81** | +3.85 | -5.85 | -10.00 | -1.67 | -4.17 | -1.67 |
| User | Static | 4.67 | -0.12 | 4.04 | 8.59 | 11.67 | 4.17 | 1.67 | 0.00 |
| User | RTT | 5.29 | 0.35 | 3.57 | 9.21 | 4.17 | 2.50 | 0.00 | 0.00 |
| User | RTT - static | +0.62 | **+0.47** | -0.47 | +0.62 | -7.50 | -1.67 | -1.67 | 0.00 |

The earlier uniform-neutral scorer produced RTT-minus-static S-H of `+0.09`
Full and `+0.08` User. Evidence calibration changes those contrasts to `-10.81`
Full and `+0.47` User. It therefore exposes the intended unsupported-completion
failure strongly in Full, but does not create the same aggregate separation in
User.

## Model decomposition

| Model | Arm | Static S-H | RTT S-H | RTT - static |
| --- | --- | ---: | ---: | ---: |
| GPT-5.6 Sol | Full | 13.69 | 0.56 | -13.13 |
| GPT-5.6 Sol | User | 0.47 | 1.67 | +1.20 |
| Gemini 3.8 Flash | Full | 9.01 | 0.52 | -8.49 |
| Gemini 3.8 Flash | User | -0.71 | -0.97 | -0.26 |

Both judges agree on the Full direction. The User result is judge-sensitive:
Gemini shows a small RTT improvement, while Sol shows a regression.

## Task-level uncertainty and mechanism

The Full task-level RTT-minus-static S-H mean is `-10.81`, sample SD `25.48`,
SE `5.70`; 14 tasks are negative, five positive, and one tied. The large mean
is concentrated most strongly in `da-17-3` and `da-20-4`, where Static selected
scores reward plausible complete-looking answers while the evidence-aware
heldouts reject unsupported execution claims. RTT either withdraws those claims
or reports evidence consistent with the actual run. Excluding those two largest
contrasts still leaves a Full task mean of `-2.72`.

The User task-level contrast is `+0.47`, sample SD `3.91`, SE `0.87`; seven tasks
are negative, 12 positive, and one tied. The strongest RTT improvements occur in
`da-26-4`, `da-20-1`, and `da-9-1`, but they are offset by `da-20-4`, `da-9-7`,
`da-26-2`, and `da-3-5`. In this arm, the User feedback policy often leaves both
Static and RTT with incomplete or weakly evidenced artifacts, so a truthfulness-
aware heldout does not systematically create a larger Static S-H gap. The Sol/
Gemini disagreement further shows that the remaining User effect is not a stable
measurement result.

This panel therefore supports evidence-aware heldout scoring as a useful Full-arm
truthfulness diagnostic, not as a universal metric-only cure for both arms. No
prompt was tuned after viewing the complete New20 result, and no revision-stage
rerun was performed. Exact task points and all 480 artifact-model rows are saved
in `evidence-calibrated-new20.json`.

## Execution record

The final missing-only recovery was Babel job `10520389`: 4 CPUs, 64 GiB RAM,
provider concurrency 6, elapsed `01:14:16`, exit code 0, and peak RSS
`51,369,692 KiB` (about 49 GiB). The prior 32 GiB jobs failed only during evidence
extraction; every successful judgment was preserved and reused. A provider-free
export job (`10520980`) copied the final receipts from compute-only NFS for this
analysis.
