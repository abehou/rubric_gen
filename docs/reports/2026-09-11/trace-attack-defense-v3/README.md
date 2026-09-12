# attack_defense_v3 User calibration

This directory records the provider-free forensic and the bounded development
work for the User-simulator calibration candidate. The scientific reference is
attack_defense_v2.1 Result20; no Result20 case-level outcome is used to choose
v3 wording or parameters.

## v2.1 diagnosis

The User arm reduced full-trajectory RH from 20.00% to 10.00% and improved A by
2.01 points, but W-S increased 1.85 points and S declined 0.62 points. The
saved v2.1 User traces show up to three ordinary simulated-user concerns followed
by a separate focused learned-rule block. In the requested high-contribution
cases, the forensic extraction finds 54 turn records with evidence of useful-work
removal, 25 with dynamic-oversteer evidence, 7 with method/scope drift, 2 with
limitation overuse, and 14 with weak/strong disagreement; these are evidence
classes, not causal relabelings. Positive controls improve under the same
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

The implementation and tests are in the isolated `attack-defense-v3` worktree.
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
| canonical v3 confirmation | pending v3.1 stress gate |
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
The next step is the nine-assignment User-only stress run under the same seeds and
offline materials; no Result20 job is authorized until its quality and mechanism
evidence, followed by canonical dev3, are satisfactory.
