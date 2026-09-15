# Clean RTT Dev3 run — 2026-09-15

Status: preparation in progress; no fresh scientific provider call has started.

## Frozen scientific scope

- Incumbent: `attack_defense_v2.1`
- Candidate: `attack_defense_v2.1_task_paraphrase_required_completion`
- Tasks: `da-3-4`, `da-11-1`, `da-18-1`
- Replicates: 3
- Feedback arms: Full and User simulator
- Conditions: fixed and red-team trace under each arm
- Fresh matched assignments: 36
- Scientific source commit: `d43ee1e`

The candidate is a diagnosis-only RTT change. It preserves the v2.1 attacker,
pair construction/selection, rubric-view scoring, application and admission
mathematics, penalty scale, reminder delivery, simulator, solver, stopping rules,
models, and outcome evaluation. Its sole change is a version-scoped diagnosis
clarification that preserves an explicit public distinction between an
unperformed/preliminary required output and a reported output as a
`task_required` relation.

## Forensic decision

The one-time historical 16/18 inspection identified diagnosis/compilation
abstraction as the earliest repeated failure. In User `da-11-1` rep-002,
completion gaps were selected but generations 7–8 called them redundant with the
broad base rubric; the useful completion criterion was therefore not admitted.
Task-required application did not convert the omission to `not_applicable`.
The focused forensic record is
[trace-task-paraphrase-required-forensics.md](../trace-task-paraphrase-required-forensics.md);
durable future-use lessons are
[red-team-trace-lessons.md](../red-team-trace-lessons.md).

Historical run data will not be used as input to this clean experiment. It is
scheduled for explicit retirement after the forensic commit.

## Clean execution plan

1. Install `phylobio/BiomniBench-DA` with the repository's
   `download_biomni.py` into
   `/home/aydanh/runs/rtt-clean-20260915/source/data/biomnibench-da`.
2. Record only Hugging Face access and dataset revision; validate the three task
   directories and required files.
3. Generate fresh native seeds, paraphrases and pretreatment rubrics under the
   clean root, then freeze their manifests/hashes.
4. Run all four matched conditions from that same fresh input pool.
5. Validate all 36 assignments before launching the Sol+Opus audit.
6. Run only the missing authoritative audit judgments, then report W,
   W_train, S, H, A, W-S, S-H, H-A, W-A, four RH windows, both auditors, and
   case-level repair mechanisms.

New persistent paths are all under the clean NAS1 root. Temporary provider
workspace/cache paths use per-job `/scratch/job_tmp/$SLURM_JOB_ID`. No new
stage references NAS8 or historical run outputs.

## Current operational state

The new YAML and stage wrappers are ready locally. Historical home-run retirement
is queued as Slurm job 10447107; the read-only inventory job was canceled before
execution because it remained pending. No candidate scientific job is running.
The clean source setup job has not yet been submitted because the scheduler is
still waiting on the cleanup allocation.

The canonical GitHub SSH push is currently unavailable from Babel
(`github.com` DNS/public-key failure). The scientific commit remains locally
on `aydan-red-team`; push will be retried when the route is available.
