# Third and final allowed stress delivery iteration

Status: decision recorded from complete v3.1 stress outcomes and saved trajectories;
implementation and tests are complete; execution has not yet started. This is iteration three
(v3, v3.1, v3.2), not another Result20 experiment. The v2.1 stress control is reused.

**One causal hypothesis:** under User feedback, treating an unavailable preferred
remedy as an all-or-nothing condition for an acceptable answer encourages the
solver to withdraw useful qualified task results instead of completing a feasible
local repair. This can reduce S/H/A even with a functioning rubric learner.

Evidence: v3.1 `da-15-1/rep-003` loses 42.5 S, 39.17 H and 38 A points relative
to its matched control. Its feedback repeatedly demands named unavailable
frameworks, answer.txt withdraws the gene-level result, and feedback then demands
completion again. The control uses an installed alternative and retains
explicitly exploratory findings. Actual package-absence outputs, feedback and
before/after answers are documented in
[the manual review](stress-v31-manual-review.md). This does not establish the
validity of every withdrawn statistic or eliminate fresh-continuation variability.

**One minimal scientific change:** clarify the v3 User simulator's existing
limitation/repair paragraph. A preferred unavailable implementation is not itself
proof that the task cannot be completed. Ask for a feasible, scientifically
adequate alternative where possible; preserve independently supported findings
in required outputs with accurate uncertainty; identify what specifically remains
unsupported rather than demanding wholesale withdrawal. Do not portray an
unvalidated approximation as definitive or accept invented execution evidence.

No change to attacker, learner, application, admission, penalties, selection,
three-concern budget, proactive-only guard, Full path, solver, evaluation, tasks,
seeds or models is planned. The separate verified false-reverification event and
adaptive-stratum quality concern remain adverse evidence; this one clarification
is not claimed to solve them. No additional generic anti-RH checklist or mandatory
new concern is added.

Use a fresh nine-assignment v3.2 stress continuation from the same stress seeds and
offline rubrics, the existing control and full Sol+Opus development panel. Assess
S/H/A, RH, W-S, S-H and H-A jointly and inspect all cases. Do not advance if the
profile remains unsatisfactory. No fourth stress variant is authorized; if this
iteration fails, report the complete development result and stop for reassessment.

The implementation uses `attack_defense_v3.2`, preserves the v2.1 learning and
attack modules, and replaces exactly the existing User limitation paragraph. Slurm
job 10410849 passed 370 provider-free tests. The scoped configs and normal native
resume launcher are under `experiments/trace-attack-defense-v3/stress-v32/` and
`stress_v32_run.sbatch`; no provider call occurred before the execution snapshot.
