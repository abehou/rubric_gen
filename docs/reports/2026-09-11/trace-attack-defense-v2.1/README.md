# attack_defense_v2.1 — complete developmental Result20 evaluation

**The bundle does not pass the prospective joint point thresholds in both arms.** This is one 20-task developmental bundle evaluation with three replicates per feedback arm. It neither identifies individual component effects nor establishes a final paper method; Result20 was previously used for development. No second variant or scale-up was launched.

Scientific execution snapshot: `f403b4c4a14eca1e9d61ddfc8c6aa323fda02abc`; v2.1 guard commit: `621fb7c`; consumer/recovery commit: `c43a921f9f187cda8659304547ec8849a5f5ba7c`. Experiment: `biomnibench-da-factorial-r10-5115fffdd1c0`. Full input/prompt/schema/source hashes are in [execution-freeze.json](../../../../experiments/trace-attack-defense-v21/execution-freeze.json). The reference checkpoint is `60bae25c3d39d8feaec1848cc757969935dd62e1`; [implementation and readiness](implementation.md) records the bounded changes and the validated public-witness operational package. [Execution provenance](execution-provenance.md) lists the exact prompt hashes and source/consumer boundary.

The two original v2 assignment failures were generation-6 `ADD` candidates whose
normalized titles collided with already-active learned criteria. They were neither
base-rubric nor same-update collisions and declared no replacement. v2.1 rejects
such a candidate locally as `duplicate_criterion_title`, preserves the prior
criteria, and continues the assignment. [collision-diagnosis.json](collision-diagnosis.json)
contains the sealed paths and hashes. Provider-free replay found 118/118 completed
v2 assignments unchanged; only the two failed assignments were recovered.

The local Codex controller later reported `memory allocation of 8292352 bytes
failed`. That is recorded as a control-plane incident in
[runtime-control-plane-incident.md](runtime-control-plane-incident.md); it did not
invalidate the independent Slurm scientific job. Direct RH recovery job **10398066**
completed successfully, and [audit-coverage.json](audit-coverage.json) verifies all
four windows.

## Outcomes and fixed decision

RH is the equal-weight Sol + Opus confirmed-positive full-trajectory rate, using all auditor rows as the denominator. Abstentions remain unresolved in the separately reported bounds. W is weak selected-base score; W_train includes active learned penalties; S is strong selected; A is rubric-free holistic quality. H uses only the canonical V2 zero-fallback heldouts for the current/static comparison.

| Arm | Assignments | RH % | W | W_train | S | H (V2) | A | W−S | W−A | S−H | H−A |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Full static | 60 | 20.83 | 96.72 | 96.72 | 89.02 | 87.54 | 67.46 | 7.70 | 29.26 | 1.47 | 20.09 |
| Full attack_defense_v2.1 | 60 | 14.17 | 95.83 | 95.83 | 89.72 | 88.97 | 71.15 | 6.12 | 24.68 | 0.74 | 17.82 |
| User static | 60 | 20.00 | 89.58 | 89.58 | 82.24 | 80.88 | 70.48 | 7.34 | 19.11 | 1.36 | 10.40 |
| User attack_defense_v2.1 | 60 | 10.00 | 90.82 | 90.73 | 81.63 | 80.34 | 72.48 | 9.19 | 18.33 | 1.28 | 7.86 |

Paired differences are candidate minus its own static arm. Intervals resample 20 task clusters 10,000 times with seed 20260910, retaining replicates and auditors within each task. Point-effect thresholds and statistical support are distinct.

| Arm | Endpoint | Paired Δ | Task-cluster 95% interval | Upper bound < 0 |
| --- | --- | --- | --- | --- |
| full | RH (pp) | -6.67 | [-15.00, 2.50] | no |
| full | W−S | -1.58 | [-3.80, 0.53] | no |
| full | W−A | -4.57 | [-9.05, -0.28] | yes |
| full | A | 3.69 | [0.80, 6.65] | no |
| full | S | 0.70 | [-2.11, 3.46] | no |
| user | RH (pp) | -10.00 | [-18.33, -2.50] | yes |
| user | W−S | 1.85 | [-0.91, 4.95] | no |
| user | W−A | -0.77 | [-5.13, 3.45] | no |
| user | A | 2.01 | [-1.22, 5.73] | no |
| user | S | -0.62 | [-4.37, 3.58] | no |

![Paired primary effects and task-cluster intervals](paired-primary-differences.png)

For quality, positive Δ is favorable; the upper-bound column is an improvement test only for RH and the two gaps. The one-sided 95% lower bound for ΔA is used for the prespecified noninferiority condition.

| Arm | RH ≤ −5 pp | W−S ≤ −1 | W−A ≤ −2 | Mean ΔA ≥ 0 | Mean ΔS ≥ 0 | ΔA one-sided lower95 | Lower95 > −2 | Joint point result |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| full | pass | pass | pass | pass | pass | 1.22 | pass | pass |
| user | pass | FAIL | FAIL | pass | FAIL | -0.76 | pass | FAIL |

The two feedback arms are evaluated independently; pooling does not rescue a miss. A supported noninferiority claim requires its own lower-bound condition. Statistically supported primary superiority requires negative upper bounds for each primary endpoint; passing practical thresholds alone does not establish that claim.

Secondary calibration diagnostics use the mean of the absolute per-auditor case gaps, not the absolute aggregate mean:

| Arm | Mean absolute W−S | Mean absolute W−A |
| --- | --- | --- |
| Full static | 8.10 | 31.53 |
| Full attack_defense_v2.1 | 6.83 | 25.93 |
| User static | 9.78 | 23.46 |
| User attack_defense_v2.1 | 10.48 | 22.33 |

## Frozen RH windows and auditors

Every official window is retained. In particular, post_update still uses baseline/first-affected indices **2/3**, despite earlier intervention in this method. Individual rates below each use 60 assignments; equal-weight rates use 120 auditor rows; union rates use 60 native two-auditor panels. [RH-all-windows.csv](RH-all-windows.csv) contains exact positive/negative/abstention counts, nonabstaining denominators and identification bounds.

| Arm | Window | Sol static % | Sol new % | Opus static % | Opus new % | Equal static % | Equal new % | Union static % | Union new % |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| full | full_trajectory | 20.00 | 15.00 | 21.67 | 13.33 | 20.83 | 14.17 | 25.00 | 15.00 |
| full | post_update | 1.67 | 6.67 | 1.67 | 6.67 | 1.67 | 6.67 | 3.33 | 6.67 |
| full | final_artifact | 1.67 | 3.33 | 5.00 | 5.00 | 3.33 | 4.17 | 6.67 | 5.00 |
| full | final_revision | 0.00 | 3.33 | 1.67 | 5.00 | 0.83 | 4.17 | 1.67 | 6.67 |
| user | full_trajectory | 18.33 | 10.00 | 21.67 | 10.00 | 20.00 | 10.00 | 28.33 | 11.67 |
| user | post_update | 11.67 | 5.00 | 11.67 | 6.67 | 11.67 | 5.83 | 15.00 | 8.33 |
| user | final_artifact | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 |
| user | final_revision | 3.33 | 3.33 | 6.67 | 6.67 | 5.00 | 5.00 | 6.67 | 6.67 |

Both auditors, ambiguous official verdicts and native panel union remain in [results.json](results.json). Abstention-sensitive paired bounds/intervals and individual-auditor paired intervals are reported there. Final-artifact RH is a separate evaluation stage. Gemini has no role in this authoritative panel and was not probed or substituted.

## Cohort and provenance accounting

The complete coverage gate verifies **120/120 fresh trace assignments** and **3668 required/completed semantic judgments**, derived from the sealed cohort. The 120 frozen static assignments and their existing compatible outcome evidence are comparison inputs; no static revisions, seeds, offline rubrics or paraphrases were generated. All 720 existing V2 static heldout judgments were matched to actual public inputs, rubric bytes and grading identities in [frozen-source-receipts.json](frozen-source-receipts.json).

The first two da-10-1/rep-001 assignments were counted production-identity execution smoke tests. Their scientific outputs were retained. [pipeline-lifecycle.csv](pipeline-lifecycle.csv) lists every assignment, terminal stopping reason, retained revisions, actual solver turns and manifest/state hashes. Revisions followed the frozen minimum 5/maximum 10 rule; retained changed submissions can be fewer than attempted turns because an unchanged-output turn ends the run.

| Stage | Required/completed judgments |
| --- | --- |
| direct_full_trajectory | 240 |
| direct_post_update | 240 |
| direct_final_artifact | 240 |
| direct_final_revision | 240 |
| rubric_score | 2108 |
| absolute_score | 360 |
| pairwise_preference | 240 |

Assignment and judgment accounting, with per-arm counts including shared semantic keys:

| Arm | Expected/completed assignments | Required/completed unique judgments (including shared) | Shared with other arm | Abstaining cells | Missing/failed cells |
| --- | --- | --- | --- | --- | --- |
| full | 60/60 | 2202/2202 | 744 | 1 | 0/0 |
| user | 60/60 | 2210/2210 | 744 | 2 | 0/0 |

Do not sum per-arm unique counts without removing shared keys. [assignment-accounting.csv](assignment-accounting.csv) binds every case to its input, manifest, scored-submission bindings and actual prompt hashes; [accounting.json](accounting.json) contains producing jobs, recovery receipts, exact freeze inventory and native judgment plans.


Preparation/readiness job: 10394078; its provider-free input receipts are in [the execution package](../../../../experiments/trace-attack-defense-v21/execution-freeze.json). [report-job.json](report-job.json) identifies the separate provider-free coverage and reporting jobs.

| Producing job | Mode | Snapshot | CPUs / workers |
| --- | --- | --- | --- |
| 10397947 | audit | fda2a7e2fced74954b99c06e2109893c90223353 | 32 / 32 |
| 10397968 | audit | fda2a7e2fced74954b99c06e2109893c90223353 | 32 / 32 |
| 10397985 | audit | fda2a7e2fced74954b99c06e2109893c90223353 | 32 / 32 |
| 10398066 | direct-RH recovery | c43a921f9f187cda8659304547ec8849a5f5ba7c | 32 / 32 |

The exact scientific execution source remained frozen while revisions and audits ran. Source hashes, producing jobs, recovery attempts and sealed coverage receipts reside under the run root. Exact native audit imports are enforced: the schedule metadata changes the coarse native outcome implementation identity, so old records with incompatible keys are not given fabricated replacement hashes. Existing completed judgments were preserved; the direct-RH recovery accepted the producer experiment ID for 118 imported manifests and evaluated only the missing direct-window work. The frozen static comparison panel is reused separately. Reused/fresh counts and cost limitations are reported explicitly. The common simulator implementation/model/settings match exactly; its history fingerprint differs only for the authorized trace reminder message component, with both hashes recorded in results.json.

Run root: `/data/user_data/aydanh/rubric_gen/runs/trace-attack-defense-v21-20260911/result20`. Study and audit roots are respectively `study/biomnibench-da-factorial-r10-5115fffdd1c0` and `audit/biomnibench-da-factorial-r10-5115fffdd1c0` beneath it. Large request, trajectory and response payloads stay on compute storage; [raw-table-receipts.json](raw-table-receipts.json) binds large supporting tables by path, rows, size and SHA256.

## Attack, diagnosis and admission pipeline

Counts distinguish executed/inspectable public artifacts from scientifically valid contrasts. A quote match or attacker success claim is not scientific validation. Quality-order gaps count pair-update appearances; cached repeated evidence is not a fresh independent discovery. Offline g1 is frozen input with zero new induction calls.

| Pipeline quantity | Full | User |
| --- | --- | --- |
| Assignments | 60 | 60 |
| Sidecar checkpoints attempted | 314 | 441 |
| Sidecars passing native execution/output checks | 314 | 441 |
| Nonidentical public sidecars | 314 | 441 |
| Narrated attack_created | 314 | 441 |
| Sidecars with a quote-membership failure | 0 | 0 |
| Quality-order gap pair/update appearances | 1496 | 3097 |
| Quality source-binding failures, pair/update appearances | 0 | 0 |
| Valid null quality orderings, pair/update appearances | 128 | 292 |
| Diagnosis source/scope-validation failures | 0 | 0 |
| Valid empty criterion compilations | 0 | 7 |
| Supported source-verified diagnoses | 236 | 402 |
| Diagnosis preference conflicts | 0 | 0 |
| Assignments with an online proposal | 58 | 59 |
| Assignments with an online admission | 38 | 48 |
| Online proposed criteria | 236 | 395 |
| Online admission events | 76 | 95 |

Frozen offline g1: Full 60 proposed / 24 admitted assignment copies across 20 unique generation hashes; User 60 / 24 across 20. These are reused historical inputs, not new provider calls.

Raw independent candidate-witness application levels (separate from compiler predictions), including structurally ineligible applications. These labels are not verified scientific orderings; source-error and eligibility flags remain in the row-level records.

| Preferred/rejected levels | Full | User |
| --- | --- | --- |
| A/A | 22 | 41 |
| A/B | 28 | 57 |
| A/C | 88 | 158 |
| A/None | 0 | 4 |
| B/A | 1 | 9 |
| B/B | 9 | 25 |
| B/C | 40 | 51 |
| B/None | 3 | 0 |
| C/A | 0 | 6 |
| C/B | 9 | 10 |
| C/C | 34 | 31 |
| None/A | 0 | 1 |
| None/B | 2 | 0 |
| None/C | 0 | 2 |

Native semantic/support/margin decisions:

| Decision | Full | User |
| --- | --- | --- |
| accepted | 76 | 95 |
| aggregate_margin_failed | 57 | 136 |
| criterion_support_failed | 79 | 129 |
| semantic_validation_failed | 17 | 10 |

Semantic flags are also reported before structural application blockers: a criterion can have both kinds of failure. Native decision counts describe only candidates eligible to reach the mathematical gates.

| Independent review quantity | Full | User |
| --- | --- | --- |
| Semantic reviews | 236 | 395 |
| Unobservable flags | 7 | 3 |
| Redundant flags | 10 | 8 |
| Required candidate/artifact applications | 1947 | 4633 |

Independent-application/semantic structural blockers (candidate-artifact or semantic records):

| Blocker | Full | User |
| --- | --- | --- |
| application_undecidable | 19 | 79 |

Source failures, undecidable/missing applications and other structural ineligibility are separate from native rejection mathematics. [pipeline-failures.csv](pipeline-failures.csv), [pipeline-relations.csv](pipeline-relations.csv), [pipeline-generations.csv](pipeline-generations.csv) and [pipeline-summary.json](pipeline-summary.json) retain those decompositions and raw evidence pointers; no failed application is dropped or turned into A. Empty/no-supported proposals are scientific outcomes, not provider failures.

## Delivery and timing

A reminder is observed exposure, not proof of compliance. It is a separate trace-specific message after ordinary feedback, not a fourth simulator-authored concern. Only admitted requirements appear verbatim; the length and delivery-only numeric restrictions can make a scored criterion ineligible for this reminder.

| Quantity | Full | User |
| --- | --- | --- |
| Assignments with online admission before turn 1 | 21 | 16 |
| Assignments with actual reminder before turn 1 | 34 | 34 |
| Proactive/offline reminder deliveries | 63 | 85 |
| Corrective reminder deliveries | 27 | 38 |
| Total solver turns | 314 | 441 |

Subsequent optimizer-scored observations, using explicit bindings and reminder receipts:

| Quantity | Full | User |
| --- | --- | --- |
| Rule/submission observations after a reminder | 254 | 538 |
| Later optimizer-scored violations | 6 | 18 |
| Later violations with another solver opportunity | 6 | 18 |

These repeated rule/submission observations are not independent cases or verified RH events. [timing-rule-lineage.csv](timing-rule-lineage.csv) and [timing-summary.json](timing-summary.json) give availability-to-reminder lags and first later levels. No-change turns may have no subsequent sealed score.


First-admission generation and first-reminder turn distributions are in [pipeline-summary.json](pipeline-summary.json); each actual prompt hash and selection is in [pipeline-deliveries.csv](pipeline-deliveries.csv). Online accepted criteria are proposed and admitted in one update; reminder selection can delay that channel or leave an admitted rule unreminded. Ordinary feedback and the focused reminder component are tracked separately in the delivery and lineage tables. [pipeline-rules.csv](pipeline-rules.csv) preserves admitted lineage, including frozen offline copies.

## Gap decomposition and case evidence

The paired arithmetic is Δ(W−S)=ΔW−ΔS and Δ(W−A)=ΔW−ΔA. These post-treatment components describe the observed difference and do not identify causal mediation by admission or delivery.

| Arm | ΔW | ΔS | ΔA | Δ(W−S) | Δ(W−A) |
| --- | --- | --- | --- | --- | --- |
| full | -0.88 | 0.70 | 3.69 | -1.58 | -4.57 |
| user | 1.23 | -0.62 | 2.01 | 1.85 | -0.77 |

[task-gap-contributors.csv](task-gap-contributors.csv) lists all task contributions; [case-differences-vs-static.csv](case-differences-vs-static.csv) lists every matched replicate and flags narrower-gap cases with ΔA≤−5. [RH-discordant-cases.csv](RH-discordant-cases.csv) preserves all changed full-trajectory verdicts and original auditor rationales.

## Historical original/public-witness context

These are historical developmental comparisons with freshly sampled continuations, not untouched confirmation or evidence that original User RH=7.5% is a policy constant. Original Full has 59 cases (da-16-1/rep-001 missing); its matched59 task-equal and row-equal contrasts are both retained. Historical H/S−H/H−A use a different pool and are excluded from paired V2 effects.

| Historical arm | RH % | W−S | W−A | A |
| --- | --- | --- | --- | --- |
| Original Full (59) | 26.27 | 7.98 | 30.14 | 65.40 |
| Public-witness Full | 20.00 | 6.39 | 27.98 | 68.84 |
| Original User | 7.50 | 9.27 | 20.99 | 70.98 |
| Public-witness User | 17.50 | 6.33 | 19.73 | 70.31 |

Paired historical deltas and task-cluster intervals are in [results.json](results.json). These comparisons do not isolate the attack-first prompt, early schedule, blinding, diagnosis, application or reminder component.

## Calls, tokens and elapsed time

The bundle has additional early-update, independent-application and reminder overhead. No compute-parity claim is made. Each update uses the recorded P+2N+3D+DN logical ceiling times the native bounded attempt allowance; frozen g1 retains its historical budget. The exact cross-generation learning cache is assignment-local.

| Overhead quantity | Full | User |
| --- | --- | --- |
| Structured learning attempts before turn 1 | 1228 | 1220 |
| Exact learning-cache hits across updates | 5435 | 12327 |
| Delivered reminder component bytes | 56013 | 75738 |

Marginal reminder tokens are not separately exposed by the provider; total solver token/cost receipts include this channel. Every early checkpoint also has its own sidecar attempt.

| Stage | Model | Fresh saved responses | Reused historical | Input tokens | Output tokens | Usage-based USD |
| --- | --- | --- | --- | --- | --- | --- |
| audit_absolute_score | claude-opus-5 | 180 | 0 | 1555899 | 147274 | 10.99 |
| audit_absolute_score | gpt-5.6-sol | 180 | 0 | 979646 | 34569 | 5.94 |
| audit_direct_final_artifact | claude-opus-5 | 120 | 0 | 1116372 | 16792 | 4.45 |
| audit_direct_final_artifact | gpt-5.6-sol | 120 | 0 | 704464 | 10405 | 2.91 |
| audit_direct_final_revision | claude-opus-5 | 123 | 0 | 5408955 | 15181 | 25.84 |
| audit_direct_final_revision | gpt-5.6-sol | 123 | 0 | 3598628 | 9143 | 17.32 |
| audit_direct_full_trajectory | claude-opus-5 | 452 | 0 | 53791192 | 64383 | 264.69 |
| audit_direct_full_trajectory | gpt-5.6-sol | 430 | 0 | 36520245 | 35077 | 180.35 |
| audit_direct_post_update | claude-opus-5 | 211 | 0 | 20703772 | 29445 | 101.78 |
| audit_direct_post_update | gpt-5.6-sol | 206 | 0 | 14192468 | 16611 | 69.84 |
| audit_pairwise_preference | claude-opus-5 | 120 | 0 | 1639256 | 69502 | 9.61 |
| audit_pairwise_preference | gpt-5.6-sol | 120 | 0 | 1036792 | 12362 | 5.55 |
| audit_rubric | claude-opus-5 | 1054 | 0 | 10976452 | 954236 | 78.74 |
| audit_rubric | gpt-5.6-sol | 1054 | 0 | 6702725 | 348268 | 52.34 |
| common_simulator | gpt-5.6-luna | 441 | 0 | 8744640 | 74605 | 1.84 |
| optimizer_judge | gpt-5.6-luna | 1531 | 0 | 10307510 | 525183 | 3.21 |

Agent runs have cumulative thread usage and may include many internal model/tool steps. Their internal model-call count is not exposed by the saved protocol; counting each turn as one API call would be misleading.

| Agent channel | Saved streams | Threads with usage | Input tokens | Output tokens | Native estimated lower-bound USD |
| --- | --- | --- | --- | --- | --- |
| sidecar | 755 | 755 | 116778839 | 2301435 | 8.60 |
| solver | 755 | 120 | 137137616 | 1696583 | 6.39 |

Native driver elapsed times are sums of measured calls, not elapsed cohort time. Starts combine sidecars and initial solver turns; their exact wall-time split is not instrumented.

| Driver operation | Completed/failed records | Measured call wall seconds |
| --- | --- | --- |

The cost registry is dated 2026-08-18; estimates are not provider invoices. Failed calls without returned usage have unknown token cost. Capacity-journal operation times, actual failed learning attempts, reuse and cumulative-usage deduplication are retained in [costs.json](costs.json) and [cost-stage-summary.csv](cost-stage-summary.csv). Nested operations and concurrent call durations must not be summed as elapsed cohort time.


Elapsed wall time: 0.99 hours from the available owner receipts; revision/audit stage splits are not instrumented in the saved cost registry. Shared audit-slot waiting was 0.11 seconds in the capacity journal; [capacity-wait.json](capacity-wait.json) records the provider and audit-slot waits. The local controller memory incident is excluded from scientific elapsed time.

## Interpretation and remaining uncertainty

The case-review tables are provider-free inspections of saved packets. They preserve
official labels and flag evidence limitations; they do not edit auditor rationales,
invent event timings, or change official verdicts. Numeric completion does not by
itself establish causal mediation from a learned-rule exposure.

## Supporting files

- [Complete numeric results, paired uncertainty and fixed decisions](results.json)
- [Assignment/judgment/provenance accounting](accounting.json) and [case accounting](assignment-accounting.csv)
- [All 18 positive cases: evidence and ambiguity](RH-case-review.md), [JSON](RH-positive-reviewed-cases.json), [CSV](RH-positive-reviewed-cases.csv)
- [Gap cases and all substantial quality-loss flags](gap-case-review.md), [JSON](gap-reviewed-cases.json), [CSV](gap-reviewed-cases.csv)
- [Learning failure decomposition](learning-bottlenecks.md)
- [RH-positive inspection index](RH-positive-case-index.csv) and [gap evidence index](gap-inspection-index.csv)
- [All case/auditor endpoint rows](outcomes-by-auditor.csv)
- [All RH windows and panel definitions](RH-all-windows.csv)
- [Criterion lifecycle](pipeline-lifecycle.csv) and [delivery receipts](pipeline-deliveries.csv)
- [Native frozen-source verification](frozen-source-receipts.json)
- [Prospective decision rule](preregistration.md) and [implementation](implementation.md)
- [Final audit coverage](audit-coverage.json), [execution provenance](execution-provenance.md), and [runtime incident](runtime-control-plane-incident.md)
- [Large-table source receipts](raw-table-receipts.json)
