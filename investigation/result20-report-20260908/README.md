# Current four-condition Result20 reporting

## Current owners and automatic reporting (2026-09-08)

Full-static10357585 and report10357605 are complete (60 assignments,2,040 semantic judgments); see `runs/babel-result20-current-20260908/full-static-report-v2/milestone.md`. Current scientific owners are user-static10357642,user-trace10357630,full-trace10357631. Native corrected follow-on owners10357851(user-static) and10357852(full-trace) wait on afterany of their respective current owners; no running experiment is interrupted.

Read-only reports10357863(user-static),10357864(full-trace),10357865(user-trace) wait on successful final producers10357851/10357852/10357630. Combined report/figures/exposure job10357891 waits on all three reports. Scripts `analyze_*_current.sbatch`, `analyze_combined_current.py`, and source seals in this directory bind exact final receipts, require both revise/detect success and unchanged sources, and perform native complete-panel checks. Never edit these queued scripts or their sealed dependencies. Reconcile a failed producer/dependency rather than accepting incomplete survivors.

Final follow-on runtime is frozen1f995df at `runs/babel-code/result20-checkpoint-recovery`; user-trace/full-static use6535840 at `result20-local-temp`. Only tested runtime/recovery bookkeeping differs from original scientific409104f. Combined analysis uses the frozen1f995df helper with unchanged metric definitions, outputs `runs/babel-result20-current-20260908/report-v1`, and produces both versioned figures plus exposure diagnostics. No provider credentials/calls are needed. All report jobs request1CPU/8GiB/2h.

The initial-producer instructions/history below predate these verified recoveries; the owner bindings above supersede their job IDs and source paths. The analysis and plotting command structure and scientific scope remain unchanged.

Scope: static and red-team trace, each full feedback and user simulator; 20 canonical tasks ×3 replicates=240 assignments, two executing auditors=480 final rows. Offline elicited and red-team artifact are unrun and must not be filled from historical results.

Before running analysis on a Slurm compute node, verify every study's latest owner completed both revise/detect with source_unchanged=true, inspect any failed attempts/recovery, and check that sealed source hashes still match. Current producer IDs:10356969,10356970,10356971,10357008. These are initial producers, not permission to discard failures. Native analysis also checks every configured audit stage, semantic identity, and per-assignment/model evidence. Do not analyze only completed survivors.

Producing code: runs/babel-code/result20-current at409104fd98290f2577d9644b36f43c7a35338c6f. Use its frozen Python3.12/uv environment and PYTHONPATH=$PWD/runs/babel-code/result20-current/src from the main repository. Analysis/plotting needs no credentials and no providers. Run on Slurm with1CPU/8GiB/2h; do not queue afterok on currently failure-containing jobs until native recovery ownership is resolved.

Exact analysis command from repository root (after gates; `$PYTHON` denotes the frozen environment's Python):

```bash
"$PYTHON" investigation/babel-overnight-20260907/analyze_babel.py \
 --study runs/babel-result20-current-20260908/full-static/study/biomnibench-da-factorial-r10-bfbdd0f9833c \
 --audit runs/babel-result20-current-20260908/full-static/audit/biomnibench-da-factorial-r10-bfbdd0f9833c \
 --study runs/babel-result20-current-20260908/user-static/study/biomnibench-da-factorial-r10-bfbdd0f9833c \
 --audit runs/babel-result20-current-20260908/user-static/audit/biomnibench-da-factorial-r10-bfbdd0f9833c \
 --study runs/babel-result20-current-20260908/user-trace/study/biomnibench-da-factorial-r10-bfbdd0f9833c \
 --audit runs/babel-result20-current-20260908/user-trace/audit/biomnibench-da-factorial-r10-bfbdd0f9833c \
 --study runs/babel-result20-current-20260908/full-trace/study/biomnibench-da-factorial-r10-f0203f5d69f3 \
 --audit runs/babel-result20-current-20260908/full-trace/audit/biomnibench-da-factorial-r10-f0203f5d69f3 \
 --contrast full-static user-simulator-static \
 --contrast full-static full-red-team-trace \
 --contrast user-simulator-static user-simulator-red-team-trace \
 --output runs/babel-result20-current-20260908/report-v1
"$PYTHON" investigation/result20-report-20260908/plot_results.py \
 --analysis runs/babel-result20-current-20260908/report-v1/analysis.json \
 --output runs/babel-result20-current-20260908/report-v1/figures
```

The analysis exposes W_train separately, per-auditor RH and any-detect panel bounds, matched contrasts, task-cluster bootstrap intervals, all four RH windows, monitor distributions, revision behavior and source hashes. Its generic historical two-task caution is inapplicable to this20-task run; retain task-cluster inference and report actual20-task coverage.

Plot variants preserve the original per-auditor-average convention, not panel union. RH abstentions are shown as bounds; whiskers are not confidence intervals. The old original-rubric-to-holistic panel is explicitly labelled master−A; the current decomposition H−A is a separate panel. Versioned files preserve avg.png and Openal + Anthropic averace.png. CSV and provenance accompany figures. Plot arithmetic, abstention bounds, incomplete and duplicate rejection passed synthetic in-memory checks; Slurm10357017 also passed synthetic rendering of both layouts (temporary images removed);native complete-data checks and actual scientific figures remain pending.

After the complete matched report, run the existing exposure diagnostics on the same frozen environment and all four conditions:

```bash
"$PYTHON" investigation/babel-overnight-20260907/policy_exposure.py \
 --analysis runs/babel-result20-current-20260908/report-v1/analysis.json \
 --output runs/babel-result20-current-20260908/report-v1/policy-exposure
"$PYTHON" investigation/babel-overnight-20260907/feedback_exposure.py \
 --analysis runs/babel-result20-current-20260908/report-v1/analysis.json \
 --output runs/babel-result20-current-20260908/report-v1/feedback-exposure
```

Interpret mitigation using actual criterion admissions, retention, scored penalties and delivered feedback—not the policy label alone. Shared pretreatment g1 is separate from online generations≥2; red-team sidecars are method evidence, not natural-RH outcomes. Compare W_train separately from selected-base W and absolute quality A. A null with no admissions/exposure differs from a null after meaningful exposure. These diagnostics do not justify excluding any assignment from the outcome population.

The exposure helpers are main-repository private analysis scripts (not present in the producer checkout). Verify their hashes against exposure-source-seal.json before analysis and record them in the report; they do not change scientific execution.

Recovery provenance: initial trace producers10356971/10357008 were user-approved cancellations during an NFS lock stall,with source_unchanged=true. Current trace owners are10357169/10357170 at b4d751d (observer-only runtime fix),same native configs/output paths. Final report must validate their completion receipts plus the preserved original attempts;never require the cancelled initial attempts to appear successful. Static producers10356969/10356970 remain unchanged.
