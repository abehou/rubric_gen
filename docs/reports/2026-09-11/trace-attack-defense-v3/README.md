# attack_defense_v3 User calibration

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
runner are recorded under `experiments/trace-attack-defense-v3/`. Provider work
is not launched from this report until the saved seed/control receipts are
complete and the snapshot is committed.

## Development status

| stage | status |
|---|---|
| provider-free forensic | complete |
| v3 structural tests | 11/11 pass on Slurm compute environment |
| canonical v2.1 User dev3 control | complete; Sol+Opus audit complete (job 10402123) |
| matched stress dev3 | 18/18 selected assignments sealed; producer recovery 10405463, consumer recovery 10405844, provider-free finalizer 10407854 |
| stress Sol+Opus audit | v2.1 control 10408028, v3 candidate 10408035 (serialized; no duplicate judgments) |
| canonical v3 input binding | complete; current producer identities recorded |
| v3.1 stress revisions | 9/9 valid; producer 10409332, finalizer 10409423 complete |
| v3.1 stress outcomes | audit 10409706 running; report 10409709 and forensic 10409710 queued |
| canonical v3 confirmation | not launched; pending satisfactory stress evidence |
| single Result20 | not launched |

Result20 will be launched at most once, only after the stress and canonical dev3
evidence supports this narrow delivery change. If it fails, the report will retain
the failure and stop rather than tune on Result20.

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

The complete Sol + Opus audit and downstream report are in progress. See
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

W-S measures weak/strong verifier disagreement. Baseline-level or modestly lower
W-S is acceptable; a large reduction is not an objective if S, H, A or RH worsen.
S-H measures transfer to wording-only heldout rubrics and should remain low.
H-A measures rubric/holistic disagreement and must be read alongside both H and A.

[Artifact gap/RH ranking](artifact-gap-rh-ranking.md) reports equal-weight signed
gap ranks, continuous final-artifact/full-trajectory monitor scores, correlations,
and tie-aware worst-fraction overlap. It uses 147 existing artifacts with zero
provider calls. Associations differ across conditions; the gap family and RH
cannot be treated as interchangeable quality measures. Historical Result20 ranks
are descriptive and are not used to choose the next development prompt.
