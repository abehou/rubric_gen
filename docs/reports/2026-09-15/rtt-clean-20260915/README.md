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

The new YAML and stage wrappers are ready locally. The read-only inventory and
home-retirement helpers were canceled before execution after their bounded
cleanup attempt. The first clean source setup (10447181) ran after queue delay
and downloaded all 722 files, but failed post-download JSON validation because
the launch script wrote a literal backslash-n into `source-access.json`
(`JSONDecodeError: Extra data`). No model/provider call occurred. Its dependent
jobs were canceled and the same frozen chain was resubmitted after fixing only
that receipt serialization bug: source 10448331, smoke 10448332,
seed/paraphrase 10448333/10448334, preflight 10448335, revision 10448336,
completion 10448337, audit 10448338. Source 10448331 completed validly, while
smoke 10448332 then failed before a model turn because its node denied
`/scratch/job_tmp/10448332`; no scientific call occurred. The tested local-temp
fallback was committed and the dependency-blocked jobs were replaced without
repeating source: smoke 10448379, seed/paraphrase 10448380/10448381, preflight
10448382, revision 10448383, completion 10448384, audit 10448385. The resumed
smoke is currently `PENDING (Priority)`.

The replacement source 10448331 has since completed cleanly: official revision
`e1c8ca5e11a620087bc48d97888eb69176a1f235`, 722/722 files, and valid source
manifests. Smoke 10448332 then failed before any model turn because its assigned
node (`babel-l5-32`) rejected `/scratch/job_tmp/10448332` with `Permission
denied`; seed/paraphrase therefore never ran. The source is durable on NAS1.
The wrappers now try `/scratch/job_tmp/$SLURM_JOB_ID` and fall back to a local
`/tmp/rubric-gen-$SLURM_JOB_ID` directory on nodes where the scratch root is not
writable. This is execution-only; no scientific request or identity changes.

At 04:43 EDT, replacement paraphrase stage 10448381 failed after setup because
the wrapper did not export `OPENAI_API_KEY` on the compute node
(`RuntimeError: OPENAI_API_KEY must be set`). It reached no scientific model
turn and produced no valid paraphrase outputs. Source 10448331 and smoke
10448379 remain valid; seed 10448380 is still running. The narrowly scoped
execution fix loads the existing key from `.env.local` only for the paraphrase
stage, without logging it or changing scientific requests. The failed
paraphrase and dependency-blocked downstream jobs will be replaced missing-only
after this fix is pushed; source, smoke and seed will not be rerun.

The preserved seed stage 10448380 then failed for all nine blocks after making
no durable seed manifests: its optimizer-jury subprocesses reached
`RuntimeError: OPENAI_API_KEY must be set`. This is the same wrapper credential
omission, with no new scientific calls beyond the failed attempts. The fix now
loads the existing key only for both provider-backed input stages (`seed` and
`paraphrase`); only the failed seed stage will be resubmitted, while the valid
source, smoke, and completed paraphrase are preserved.

Corrected seed recovery 10448435 is now running. The completed paraphrase
10448421 is preserved. Provider-free preflight 10448442, revision 10448444,
completion gate 10448447, and audit 10448448 are queued in that order; revision
cannot start until preflight validates the seed. A transient shell-quoting error
while attaching dependencies submitted only the single intended revision job;
no duplicate completion or audit job was created.

Seed recovery 10448435 produced eight valid blocks, but only
`da-18-1/rep-002` failed its required `trace.md` validation after an invalid
`apply_patch` tool hunk. Native missing-only recovery 10448467 reran only that
block; it then completed successfully and all 9 seed manifests validated. The
provider-free preflight is now 10448487, frozen revision 10448489, completion
gate 10448490, and audit 10448491. No historical inputs are involved.

Revision 10448489 then failed before its first provider turn because the stage
wrapper did not export `OPENAI_API_KEY` to pairwise rubric induction
(`RubricProposerProviderError`, four key-check failures). The preflight
10448487 passed and no assignment output was created. The execution-only stage
wrapper now loads the existing key for `revise`; the failed revision will be
resumed with native `--resume`, preserving all frozen inputs and settings.

The key fix was committed as `fa2b0a2` and pushed. The replacement revision
`10448523` is now running from preflight `10448487` with the required `revise`
argument and the existing key loaded privately. Its 36-assignment study has
entered pretreatment/assignment work; early files show valid Full and User
static/trace states. Completion gate `10448528` and audit `10448529` remain
dependency-controlled. The prior `10448489` failure and its blocked children
made no provider turn and are not part of the scientific cohort.

At 06:18 EDT, the frozen revision `10448523` reached the halfway milestone:
18/36 assignment states are terminal-completed and 26 assignment manifests have
been created, with eight workers still active. No assignment failure artifact or
timeout is present. The clean root is approximately 6.7G with about 8.3G free on
NAS1; storage remains adequate for the remaining study and audit.

At the latest check (2026-09-15 02:07 EDT), the preempt CPU scheduler reported an
estimated source-stage start around 07:48 EDT; this is queue priority, not a
runtime failure. NAS1 remains writable with about 15 GiB free and 4% inode use,
and the clean root has not yet been created.

At 02:15 EDT, the explicitly scoped old home-root cleanup removed the complete
`trace-task-paraphrase-required-fresh-20260914` root and most of the older
candidate root. The remaining 621 MiB is protected historical scientific output
whose nested files reject deletion under the current permissions; no chmod/chown
or broad retry was attempted. NAS1 now reports about 15 GiB free and 4% inode
use. The cleanup and inventory jobs were canceled after this bounded result so
they cannot interfere with the clean chain; no clean scientific output has been
written yet. Later test-only checks for the same preempt CPU request forecast
the next available slot around 2026-09-16 06:17 EDT. The existing job remains
scheduler-owned and was not resubmitted; this is a capacity/priority delay, not
a scientific or provider failure.

The latest milestones through `c827908` are pushed to the canonical GitHub
`aydan-red-team` branch.
