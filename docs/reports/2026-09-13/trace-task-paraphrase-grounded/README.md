# v2.1 task/paraphrase-grounded forensic and candidate record

This is a provider-free decision record for the next permitted Red-Team-Trace
candidate. It does not alter `attack_defense_v2.1`, historical Results20
artifacts, or the held Results30/45 work. The current external provider limit is
reported in the mission status and the native missing-only chains remain held;
no new candidate call is authorized while that block is active.

## Finding from the v2.1 implementation

The executing v2.1 source at commit `78ab83885fafa391fabffa3cc00f71e84c3a990f`
confirms the suspected asymmetry:

* `trace_defense_v21.py:93-99` builds context from the immutable original
  rubric, active learned rules, replaceable rules, and same-update accepted
  rules.
* `:102-110` sends that context to diagnosis and includes the selected/original
  rubric only; the development rubric is absent.
* `:211-216` sends the original rubric to compilation; the development rubric
  is absent.
* the semantic request uses the same original-only context.
* `:183-201` does evaluate the original and development views independently and
  puts both into pair comparisons. Thus the development view affects preference,
  gap and native margin evidence, but not the text supplied to criterion
  diagnosis, compilation or semantic nonredundancy.

The source fingerprints are preserved here for review:

| source | SHA256 |
|---|---|
| `src/rubric_gen/submission_revision/trace_defense_v21.py` | `19cd329b8939e9cda7d7daccfbf548928c8cc7b649738d15ffe70f07c5144bf1` |
| `src/rubric_gen/submission_revision/trace_defense_v2_prompts.py` | `35e5d7ee9493fc72bbddc8cb1ea81c25567d6e0586c6c1121ad95f8fb7902a4e` |
| `src/rubric_gen/submission_revision/trace_defense_v2_stage.py` | `d3936ae868cc501d1bee71e182ed7ab87dd1c813e838cafa20c52c32c7b3a7e3` |
| `src/rubric_gen/submission_revision/trace_defense_registry.py` | `f82a4af4548553a98174d69e89c1a63f941d1ccd643eeb357acb6537f790490c` |
| `src/rubric_gen/submission_revision/trace_defense.py` | `88f6281f9700dcee9dda8807e6440ad5c30e10556d8f879604cfa26bad3f7e4f` |
| `src/rubric_gen/submission_revision/evolution_assessment.py` | `51176ea51386588cf5340a8bc93ec2bcb73e723bafc5fce387d22093c423f026` |

`evolution_assessment.partition_gaps` reserves a deterministic subset of gap
pairs after excluding the selected red-team priority pairs. The corresponding
native checks are a support/no-regression constraint over active and development
views; this code does not make them a semantic heldout rubric. `select_pairs`
keeps the newest sidecar in slot one and sorts slot two by the minimum active or
development margin, latest checkpoint and pair ID. It has no explicit
active/development-disagreement priority.

The compact saved receipts do not retain a complete count of all eligible
active/development-disagreement opportunities. The archived NFS pair records
remain the authoritative source for that count when provider/storage access is
available; this report does not invent one from aggregate generation counts.

## Development evidence

The compatible canonical User v2.1 control is nine assignments and 336/336
judgments. Its equal-weight Sol+Opus mean is W 91.22, S 83.72, H 83.11, A
72.67, W-S 7.50, S-H 0.61 and H-A 10.44. The assignment-level decomposition is
in `v21-user-s-h.csv` and the source JSON is
`../../2026-09-12/biomnibench-v21-to45/queue3/user_simulator-trace.json`.

Positive S-H is concentrated rather than universal: `da-3-4/rep-002` is +3.67
for both auditors, `da-3-4/rep-001` is 0 for Sol and +11 for Opus, and
`da-11-1/rep-003` is 0 for Sol and +4.67 for Opus. The remaining assignments
are zero or negative. This supports a wording/heldout-transfer investigation,
but it does not prove overfitting: the compact receipt has no per-turn strong
score or public artifact text for a causal reconstruction. The same rows include
both appendix exposure and no-appendix turns, so appendix presence alone does
not explain the pattern.

The queue-2 same-criterion analysis found 20 positive and 106 tied selected-base
criterion/auditor rows, with no negative rows; `da-11-1` contributes 68.89% of
its 7.50 mean. Saved cases concern missing requested outputs, captured QC or
pathway reporting, and traceability. They show that task completion and
claim-qualification can diverge; ordinary User feedback already sometimes asks
for complete analyses, so “the simulator never prioritizes completion” is not a
supported root cause. The stress records also contain invalid retained
computations, target-like private guidance and evaluator/context disagreement,
so the selected-rubric pathway is only one mechanism among several.

## Smallest candidate (not run)

The evidence supports one opt-in RTT-only candidate:
`attack_defense_v2.1_task_paraphrase_grounded`.

Its single scientific difference is to pass both the selected/original base
rubric and the development base-rubric paraphrase into the existing diagnosis,
compilation and semantic-review contexts, with short guidance to express the
underlying task relation, carry the concrete corrective action, and avoid
selected-wording restatement. Attack, quality, rubric-view, application,
locator repair, selection order, admission mathematics, penalties, schedule,
feedback, solver, models, settings, and heldout evaluation remain unchanged.
Outcome heldout rubrics are never supplied.

No source file was changed for this candidate. This is deliberate: the current
account-capacity receipt records provider access reset at `2026-09-19 04:09`,
and adding or editing a `trace_defense*.py` module currently changes the
implementation fingerprint used for every v2 recipe. A safe version-scoped
dispatch must first preserve the historical v2.1 fingerprint while giving the
new recipe a distinct request identity. Adding a compatibility hash or silently
rewriting old generation receipts during an external provider outage would add
complexity without producing evidence. The candidate therefore remains
unlaunched and v2.1 remains the incumbent.

When provider access returns, the native order is: implement the version-scoped
dispatch with a provider-stub test, run the canonical three-task/three-replicate
Full and User development block (18 fresh candidate assignments), audit all four
RH windows, and compare S/H/A and the three signed gaps against compatible v2.1
controls. A selector change is conditional and must not be stacked on this
candidate unless the resulting saved pair-disagreement analysis demonstrates
that the two-slot selector systematically misses such pairs.

## Operational state

The current mission status is
`experiments/biomnibench-v21-to45/status.json` at `2026-09-13T08:10:00-04:00`.
The only complete scale result remains the v2.1 Results20 table in the main
mission report. Results30 has ten valid seed manifests but four `da-1-3` Full
records stuck after `s000`; Results45 has 44/45 valid seed blocks and requires
native regeneration for `da-17-1/rep-003`; Queue3 still lacks the
Score-only/no-appendix `da-11-1` cell. Their native recovery, audits and reports
are held behind the external provider limit. PaperBench jobs are unrelated and
were not touched.

This record is a concrete scientific limitation, not a successful candidate.
Expectations remain **partially met**: v2.1 Full Results20 is a supported
incumbent, User calibration and selected-to-heldout transfer remain unresolved,
and the larger scale outcomes are operationally incomplete.
