# attack_defense_v3 User calibration

**Final development result, 2026-09-12: stop without Result20.** All three
authorized stress iterations are complete. The last, v3.2, has 9/9 assignments
and 330/330 required Sol+Opus judgments, including all four RH windows. Its
W−S improves but A falls 6.33 points, S−H grows 3.13, and H−A grows 5.98 against
the matched v2.1 stress control. No candidate satisfies the joint development
objective. Canonical v3, the conditional four-feedback-policy comparison, and
Result20 were not launched. The v2.1 scientific reference remains unchanged.

Read [the final all-case review](stress-v32-manual-review.md),
[complete outcomes](stress-outcomes-v32/README.md), and
[mechanism accounting](stress-v32-mechanism-summary.json).

This directory records the provider-free forensic and the bounded development
work for the User-simulator calibration candidate. The scientific reference is
attack_defense_v2.1 Result20. The requested historical Result20 forensic informed
the initial delivery hypothesis and stress-task selection. Subsequent delivery
iteration uses the stress/canonical development traces, not another Result20 run.

## v2.1 diagnosis

The User arm reduced full-trajectory RH from 20.00% to 10.00% and improved A by
2.01 points, but W-S increased 1.85 points and S declined 0.62 points. The
saved v2.1 User traces show up to three ordinary simulated-user concerns followed
by a separate focused learned-rule block. In the requested high-contribution
cases, the automatic forensic extraction flags 54 turn records for possible work
removal, 25 for possible dynamic oversteering, 7 for method/scope drift, 2 for
limitation overuse, and 14 for weak/strong disagreement. These are heuristic
triage labels, not verified mechanism counts or causal relabelings. Positive controls improve under the same
selector, so this does not justify changing the learner or admission gates.

See [user-calibration-forensics.md](user-calibration-forensics.md) and its
machine-readable [JSON](user-calibration-forensics.json), [CSV](user-calibration-forensics.csv),
and case-summary tables for exact saved paths, hashes, feedback, reminders, and
bounded artifact diffs.

## v3 scientific change

The candidate changes only User delivery. It reuses the v2.1 attack, evidence,
diagnosis, compilation, application, admission, penalty, source-schedule, and
Full-feedback paths. The selected learned rule is passed privately to the
simulator as one focused check and competes inside the existing three-concern
budget; no fourth solver-visible message is appended. A deterministic private
summary of non-maximal original/base criteria is supplied to the simulator,
ranked by existing point loss and rubric order. Concern-origin labels are
persisted for analysis and stripped before solver rendering. Proactive learned
checks alone do not force revision, and local repair/preservation is required.

The implementation and tests are in the isolated `runs/babel-code/attack-defense-v2` worktree.
Canonical User v2.1 control input preparation and the matched v2.1/v3 stress
runner are recorded under `experiments/trace-attack-defense-v3/`. Saved inputs and
controls are complete; each scientific iteration launches only from its committed
snapshot.

## Development status

| stage | status |
|---|---|
| provider-free forensic | complete |
| v3 structural and shared regression tests | 370 pass in Slurm job 10410849 |
| canonical v2.1 User dev3 control | complete; Sol+Opus audit complete (job 10402123) |
| matched stress dev3 | 18/18 selected assignments sealed; producer recovery 10405463, consumer recovery 10405844, provider-free finalizer 10407854 |
| stress Sol+Opus audit | v2.1 control 10408028, v3 candidate 10408035 (serialized; no duplicate judgments) |
| canonical v3 input binding | complete; current producer identities recorded |
| v3.1 stress revisions | 9/9 valid; producer 10409332, finalizer 10409423 complete |
| v3.1 stress outcomes | complete: audit 10409706, report 10409709, forensic 10409710; 326/326 candidate judgments |
| v3.2 final allowed stress iteration | 9/9 complete: producer 10411526, one-CPU finalizer 10411527; unchanged execution commit d164a9a |
| v3.2 outcomes and forensic | audit 10411528, report 10411530, forensic 10411532 complete; 330/330 candidate judgments |
| canonical v3 confirmation | not launched; no satisfactory stress winner after three iterations |
| Full/Semi/Score-only/User canonical comparison | not launched; conditional on a satisfactory frozen User candidate |
| single Result20 | not launched |

The plan authorized at most one Result20 only after satisfactory stress and
canonical evidence. That condition was not met; the development loop is closed
without using another Result20 to tune this delivery family.

## Stress execution incident

The first matched stress launcher (10402416) completed eight of the nine selected
v2.1 producer assignments. Its only selected failure was
`da-15-1/rep-001--solver-luna--user-simulator-red-team-trace`, recorded as
`_SolverTurnFailure: provider exited with code 124`; the launcher stopped at its
producer completeness check before any v3 consumer assignment began. The compact
inventory is [stress-failure-inventory-10402416.json](../../../../experiments/trace-attack-defense-v3/stress-failure-inventory-10402416.json).
Completed producer outputs are retained. Job 10405463 resumed only the failed
producer assignment and completed it. Job 10405844 then resumed only the nine
never-started v3 consumer assignments; all nine completed, but its wrapper
reported failure because scoped ledgers use the native `completed_scope` status
while non-selected factorial records remain pending. Provider-free finalizer job
10407854 validated all six selected ledgers and all 18 assignment artifacts
without changing a ledger or making a provider call. No completed assignment was
resubmitted and no scientific prompt/configuration was changed. The recovery
wrapper now accepts both native `completed` and `completed_scope` statuses while
still validating selected records individually.

## v3.1 stress iteration

The first stress comparison was useful but not sufficient to freeze v3: v3 raised
selected and heldout scores on average, yet its H-A gap increased by 6.85 points
and the saved trace for `da-18-5/rep-001/s001` showed a nonviolated proactive
learned check emitted as the only concern with a `revise` decision. That is a
concrete violation of the declared delivery policy, rather than a reason to
change the learner or admission gates. The single v3.1 change is a deterministic
host-side projection after the validated simulator response: when the selected
check is proactive/nonviolated and every emitted concern is `dynamic_proactive`,
the effective delivery is `accept` with no concerns. Base, general and corrective
concerns are left unchanged. The raw simulator record remains retained for audit.

The v3.1 recipe is a separate version identity but reuses v2.1's attack and
learning modules. Dispatch, replay and study-validation checks recognize the new
version. Provider-free tests passed 11/11 in job 10409121 and the three v3.1
stress configs loaded with their v2.1 pretreatment bindings in job 10409175.
The nine-assignment User-only run completed and provider-free finalization passed.
Its Slurm allocation was preempted after the assignment subprocesses completed;
Slurm automatically requeued the same job, which reused the completed outputs and
finished validation. No manual revision resubmission was made. The launcher owner
receipt and Slurm log were overwritten on restart, an operational recording
limitation; the exit receipt and Slurm accounting retain the completion/preemption
sequence. Scientific requests were unchanged across the restart.

The complete Sol + Opus audit and downstream report are finished. See
[the manual saved-trace review](stress-v31-manual-review.md). The proactive-only
guard fired zero times in this realization; any score movement cannot be
attributed to an observed guard intervention. No canonical v3 or Result20 run has
been launched.

The stress control/candidate have matched starting submissions and selected
rubrics. Their initial submissions were newly generated for stress by job
10402280, however, and differ from historical Result20 static starts. The report
labels that static subset descriptive and records the mismatch rather than
presenting it as an exact matched-start baseline.

## Gap interpretation and ranking

Current stress results (equal-weight Sol + Opus; nine assignments per row):

| variant | W | S | H | A | W-S | S-H | H-A | W-A | full RH | post RH | online admissions | unique undecidable applications |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| v2.1 control | 95.22 | 83.78 | 83.59 | 77.61 | 11.44 | 0.19 | 5.98 | 17.61 | 0% | 0% | 20 | 2 |
| v3 iteration 1 | 96.00 | 89.56 | 90.22 | 77.39 | 6.44 | -0.67 | 12.83 | 18.61 | 0% | 0% | 16 | 12 |
| v3.1 iteration 2 | 96.00 | 83.06 | 82.02 | 74.67 | 12.94 | 1.04 | 7.35 | 21.33 | 5.56% | 11.11% | 10 | 8 |
| v3.2 iteration 3 | 92.89 | 86.56 | 83.24 | 71.28 | 6.33 | 3.31 | 11.96 | 21.61 | 0% | 0% | 14 | 0 |

All final-artifact/final-revision RH rates are zero in these stress cohorts.
The first iteration increased H-A materially; the second loses S/H/A and worsens
RH. The third retains more substantive work but loses A and increases S−H/H−A.
**None is ready for advancement.** Small-n fresh continuations limit causal
attribution, especially because the v3.1 guard did not actually fire.

The complete online funnel comparison is diagnostic, not an admission target:

| variant | attacks / nonidentical | proposals | native decisions | admissions | assignments admitted | unique undecidable applications |
|---|---:|---:|---:|---:|---:|---:|
| v2.1 control | 76 / 76 | 63 | 61 | 20 | 8/9 | 2 |
| v3 | 70 / 70 | 59 | 58 | 16 | 8/9 | 12 |
| v3.1 | 59 / 59 | 65 | 59 | 10 | 6/9 | 8 |
| v3.2 | 61 / 61 | 56 | 50 | 14 | 7/9 | 0 |

These exclude frozen g1 rules. Native support/margin/semantic rejections are
15/21/5 in the control, 25/15/2 in v3, 23/17/9 in v3.1, and 11/21/4 in v3.2.
Pre-native scientific application uncertainty blocks 2/1/6 candidates in
control/v3/v3.1; v3.2 instead has six deterministic title rejections. Source:
[first-iteration saved counts](stress-iteration1-learning-summary.json),
[v3.1 extraction](stress-v31-user-forensics.json), and
[v3.2/control counts](stress-v32-mechanism-summary.json). More admissions are
neither sufficient nor necessary for a good endpoint.

The v3.1 learning funnel has 59 online updates/nonidentical sidecars, 65 proposal
appearances, 59 complete native decisions (six blocked by application uncertainty),
and 10 admissions across six assignments. Native rejection counts are 23 support,
17 margin and nine semantic. These scientific negatives remain valid outcomes.
There are 1,346 unique valid learning requests; eight of 570 unique applications
are undecidable (13 of 770 generation appearances). No locator repair occurred.

The 116 raw User concerns comprise 74 base, 35 general and seven dynamic-corrective
tags. Thirteen focused checks were selected (nine online/four offline; four
corrective/nine proactive), with three matching tag-based emissions (one online,
two offline). Tagging does not establish exact semantic exposure or compliance.
The [manual review](stress-v31-manual-review.md) and its
[CSV](stress-v31-manual-review.csv)/[JSON](stress-v31-manual-review.json) supersede
automatic mechanism triage. The full extraction remains available in
[stress-v31-user-forensics.json](stress-v31-user-forensics.json).

The [third-iteration decision](stress-v32-decision.md) targets the largest verified
quality loss: unavailable-remedy demands followed by answer withdrawal. It changes
one User instruction paragraph; no learner or mathematical gate changes. This is
the last permitted stress iteration, and an unsatisfactory result will stop the
development loop rather than trigger v3.3 or Result20.

W-S measures weak/strong verifier disagreement. Baseline-level or modestly lower
W-S is acceptable; a large reduction is not an objective if S, H, A or RH worsen.
S-H measures transfer to wording-only heldout rubrics and should remain low.
H-A measures rubric/holistic disagreement and must be read alongside both H and A.

[Artifact gap/RH ranking](artifact-gap-rh-ranking.md) reports equal-weight signed
gap ranks, continuous final-artifact/full-trajectory monitor scores, correlations,
and tie-aware worst-fraction overlap. It uses 147 existing artifacts with zero
provider calls. The completed v3.1/v3.2 extension brings this to **165 artifacts**.
For v3.2 the final-artifact monitor scores are constant, so correlations are
undefined; full-trajectory combined-gap-score Spearman is 0.129. Historical
v2.1 User correlations are weak (combined score 0.121 with final-artifact RH and
−0.120 with full-trajectory RH). Associations differ across conditions; the gap family and RH
cannot be treated as interchangeable quality measures. Historical Result20 ranks
are descriptive and are not used to choose the next development prompt.

## Final mechanism, provenance and resource accounting

v3.2 has 61 online updates/nonidentical attacks, 56 proposal appearances,
50 complete native decisions, and 14 admissions across seven assignments.
Support/margin/semantic rejection counts are 11/21/4; six duplicate-title proposals
are rejected locally. There are no undecidable applications or source-contract
failures in the extracted learning requests. Selective no-admission is preserved.
The complete [native decisions](stress-v32-native-decisions.csv) retain the first
failed protected margin, and [case accounting](stress-v32-case-accounting.csv)
records lineage, stopping and first online admission/delivery.

The concern budget operates, but accurate feedback remains an issue. Fifteen
checks are selected; two have matching emitted tags, including one online
corrective check. The 119 raw concerns comprise 73 base, 33 general, 12
dynamic-corrective and one dynamic-proactive tags. These tags do not prove that
all tagged concerns originated from a learned rule. One raw proactive-only revise
is projected to accept. The run has 61 prompt receipts/54 retained revisions,
versus 76/70 for the same fixed stress control. See
[delivery details](stress-v32-delivery.csv).

All three RNA-seq candidates retain quantitative outputs, but the saved code
contains demonstrable inferential/diagnostic errors. Repeated concern-driven
edits sometimes qualify those errors rather than repair them. Another case
receives explicit target-like counts despite the User prompt's prohibition.
The final [manual review](stress-v32-manual-review.md) separates these facts from
unresolved auditor/context disagreements. No learned-rule-count target, scoring
change, fourth reminder or further prompt version is introduced.

Execution source: `d164a9a9a081c725465ca9cb031f816b51425add`.
Configs: `experiments/trace-attack-defense-v3/stress-v32/`.
Raw root:
`/data/user_data/aydanh/rubric_gen/runs/trace-attack-defense-v3-20260911/stress-iter3/v32-candidate/`.
The [native finalization receipt](../../../../experiments/trace-attack-defense-v3/stress-v32-finalization.json)
enumerates exact experiment/assignment roots. The existing input bindings and
audit records preserve their producer identities; no result was relabeled.
Coverage comprises 204 revision rubric scores, 36 absolute judgments, 18
pairwise judgments, and 72 direct-RH judgments (18/window). Both Sol and Opus
have complete required coverage. No Gemini request or substitution occurred.

The learner used 1,201 request-unique successful calls: 167 quality, 482 rubric
view, 74 diagnosis, 37 compilation, 36 semantic and 405 application. All were
first-response contract-valid. Generation-appearance counts and reuse are
separate in the JSON; these counts exclude solver, attack and outcome calls.
Slurm wall time is recorded below; an all-provider token/USD total has not been
reconstructed and compute parity is not claimed.

The [CPU review](cpu-resource-audit.md) retains producer requests at 32 CPUs,
reduces audits from 32 to 8 without changing 32 request workers, and reduces
serial finalizer/report/forensic/ranking requests to one CPU. v3.2 completed on
these allocations: producer 2:04:02, finalizer 1:19, audit 22:47, report 0:38,
forensic 1:44. Post-completion evidence/ranking reads use one CPU and make no
provider calls. This ends the authorized development loop; it does not freeze
v3.2 as a successful paper method or launch an unsuccessful candidate on Result20.

Provider-free closing jobs:10413312 extended ranking to165 artifacts and read final public/A records;10413410 completed admitted-witness/prompt inspection;10413429 completed the first-iteration learner totals. The preceding supplemental export10413326 failed on a reporting-only `KeyError: criterion_id` (raw proposals correctly have no host ID); its corrected read preserved all scientific records, with zero provider calls.
