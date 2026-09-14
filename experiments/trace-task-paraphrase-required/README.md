# Task-required canonical Dev3 candidate

This is the provider-ready configuration for the single structural RTT
revision selected by the 2026-09-13 architecture audit:
`attack_defense_v2.1_task_paraphrase_required`.

It reuses the canonical three-task Dev3 pretreatment/g1 inputs and the v2.1
Full/User conditions. It changes only the version-scoped diagnosis,
compilation, semantic obligation-mode contracts; attack, views, application
(native checks), admission mathematics, delivery, solver, and outcome settings
remain pinned. No provider run has been launched from this bundle.

The run entrypoint is `run_candidate.sbatch`. It requires a 32-CPU Slurm
allocation and writes new durable study/audit outputs under
`/home/aydanh/runs/trace-task-paraphrase-required-20260914/` (NAS1). Frozen
tasks, seeds, paraphrases and realized g1 inputs remain read-only on NAS8 at
their recorded producer paths. Per-job temporary files use
`/scratch/job_tmp/$SLURM_JOB_ID` when available. This is an execution-path
relocation only; the scientific recipe and request identities are unchanged.
Do not submit until the provider-free path validation and same-route worker
smoke succeed. Resume only through the native study ledger.
