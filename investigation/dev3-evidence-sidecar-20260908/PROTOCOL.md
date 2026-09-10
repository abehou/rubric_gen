# Evidence-support sidecar dev3 comparison

2026-09-08. Authorized bounded policy development after complete adverse user-policy Result20. No provider-calling scientific job has launched at preparation time.

## Hypothesis

The existing red-team sidecar asks for a material analytical error, insists on mutually consistent answer/trace, and prohibits fabricated execution claims. Result20 natural-RH cases include unsupported completed-computation/output claims, while admitted criteria often target a different, narrower analytical defect. A sidecar prompt emphasizing publicly inspectable evidence-support failures may yield more relevant independently admissible criteria and reduce natural user-setting RH without reducing quality.

This is a hypothesis, not a bug fix or an asserted causal explanation. The induction prompt already requests inspectable evidence; its unchanged blind admission must still reject unsupported, redundant or unobservable proposals. Hidden fabrication cannot be directly diagnosed by artifact-only judges merely through a new prompt. The candidate therefore requires a visible claim/evidence mismatch, not a private confession of wrongdoing.

## Treatment and controls

- Frozen control source `6498d78`, worktree `runs/babel-code/dev3-evidence-control`.
- Frozen candidate source `4a8cebe`, worktree `runs/babel-code/dev3-evidence-sidecar`.
- The exact source difference is only `src/rubric_gen/submission_revision/red_team.py`: focus synthetic sidecars on evidence-support failure, allow that defect inside the scored synthetic artifact, retain honest tool logs and separate truthful sidecar explanation.
- Do not send the adversarial prompt to the ordinary solver or simulator. Sidecars are method evidence, excluded from natural RH outcomes.
- Unchanged selected/master/heldout semantics, solver/simulator/proposer identities, rubric induction/admission, update timing, penalty scale, evaluators and RH thresholds.
- Both sources include identical already-tested request compaction, bounded transport retry and token pacing. Those execution changes distinguish this fresh comparison from historical Result20; do not overwrite or resume historical scientific outputs with these sources.

## Population

Canonical dev3 tasks `da-3-4`, `da-11-1`, `da-18-1`, randomization seed 20260806, three replicates. Reuse each task's native validated seed/paraphrase pool, without merging or rewriting metadata. Prepared configs preserve selected variant0, development1 and heldouts2/3/4.

Control configs contain selected user-static and user-trace cells (six assignments/task). Candidate configs execute user-trace only (three/task). Full comparison is 27 assignments: 9 static, 9 current trace, 9 evidence-support trace. Source/arm namespace distinguishes two trace conditions even though both correctly retain rubric_policy=red_team_trace; analysis must label the candidate separately and must not merge equal condition IDs across arms.

## Runtime gates and launch order

Non-provider acceptance jobs10363149(control),10363150(candidate) validate all canonical inputs and shared workflow tests. A new launcher must record source/config hash seals, condition ownership, native resume,4CPU/128GiB/account-free preempt/preempt_cpu_qos, shared aggregate60 and Anthropic8M inputtokens/min. Use one canonical-task matched comparison first as the real execution gate; reuse its completed cells in the full dev3 comparison. No extra task set or evaluator substitution.

## Analysis and next decision

Collect every frozen RH window by auditor/panel with abstentions, monitor distributions, W/W_train/S/H/A/all gaps, quality, revision/stop behavior, actual criterion admission/penalties/feedback exposure, provider failures and recovery history. Verify matched initial artifacts and selected hashes. Evaluate policy improvement against matched current trace and static controls, not just a favorable subgroup or sidecar detection rate.

A successful criterion proposal without solver exposure is not evidence of efficacy; no admission is different from admission with no effect. If evidence-support sidecars are admitted but natural behavior fails to improve, inspect timing and weak application before adding another factor. If coverage fails at blind admission, examine failed supporting pairs before choosing a proposer change. Return to Result20 only after useful matched dev3 evidence; keep negative results.

## Prelaunch capacity correction

The initial accepted sources9dd3b40/8f4880f retained a32K proposer output cap. Pending scientific jobs10363145/10363146 were held before launch; no scientific artifacts or provider calls were produced. Both arms now preserve the successful Result20 64K output/4MiB input caps at6498d78/4a8cebe. Only red_team.py differs between these two final scientific sources. The first acceptance receipts remain historical evidence, superseded by10363149/10363150 and a new launcher check.
