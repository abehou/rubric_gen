# Conditional Result20 recovery — 2026-09-08 10:28 EDT

Status: user explicitly authorized this recovery and future relevant routine recoveries. Original four stalled owners are terminal; recovery jobs10357585/10357642/10357630/10357631 submitted. Commands below are a recovery reference, not instructions to duplicate active owners.

## Evidence and scope

- Main runtime fix6c24511; isolated scientific checkout6535840 at `runs/babel-code/result20-local-temp`, based onb4d751d. Only temporary Codex runtime locks and the earlier observer-lock correction differ in runtime source from409104f. Models, prompts, scoring, tasks, policies and thresholds remain unchanged.
- Synthetic host-isolation smoke10357367:69/69 passed including60workers on affected babel-l5-28. Actual proxy smoke10357429:two starts/commands passed, workspace scratch unchanged, network denied, persistent fixtures preserved.35 focused tests passed in10357433. These do not prove sustained real-provider60 or actual model-thread resume.
- New dispatcher checks every prior owner is absent from squeue and the corresponding sacct main-job state is terminal; verifies original source hashes; preserves missing/failed producer receipts as such. It never rewrites original completion metadata. Current native validation must accept each resumed cell.

## Approved-stop step, only after explicit approval

```bash
scancel 10356969 10356970 10357169 10357170
```

Wait for all four to disappear from squeue, including cleanup; preserve existing logs/receipts and verify terminal sacct states. A userspace timeout alone is not terminal evidence. Confirm isolated NFS lock acquire/release and shared-budget health before any provider work. No lock files may be deleted and no alternate provider-capacity pool may be created.

## Resume commands after terminal-owner and runtime gates

```bash
sbatch --parsable investigation/result20-local-temp-recovery-20260908/condition.sbatch full-static --workers 60 --audit-workers 60
sbatch --parsable investigation/result20-local-temp-recovery-20260908/condition.sbatch user-static --workers 60 --audit-workers 60
sbatch --parsable investigation/result20-local-temp-recovery-20260908/condition.sbatch user-trace --workers 60 --audit-workers 60
sbatch --parsable investigation/result20-local-temp-recovery-20260908/condition.sbatch full-trace --workers 60 --audit-workers 60
```

Resource profile:account-free preempt/preempt_cpu_qos,1node,1task,4CPUs,128GiB,48h,CPU-only. All stages/studies share the original60-slot policy and one audit-study admission. Native `revise --resume` then `detect --resume` reuses original configs/output paths,60seeds and100variants. Source and launcher hashes are recorded per new attempt; old attempts remain immutable.

Observe initial real provider operations before broadening concurrent recovery; test the actual model-session continuation and stop expanding if any runtime validity gate fails. Do not interpret the synthetic60-command pass as sustained provider stability.

## Remaining cell and analysis issues

- Two user-static cleanup failures retain native-valid cached judgments; let native resume reuse them.
- Four trace cells had workspace/hash mismatches:two only empty protected directories, two also artifact bytes. Preserve changed live trees and inspect native checkpoint recovery after terminal ownership. Never patch hashes, discard evidence, or replace session history to force acceptance. The proposed runtime fix does not resolve these data-state failures by itself.
- Original analysis10357038 depends on10356969. After approved cancellation, replace that now-unsatisfiable analysis dependency with a fresh coverage-gated report owner bound to the successful recovery receipt. Preserve its old pending-owner record.
- Pending10357398 is an independent non-provider proxy check on babel-l5-28. Keep its result separate from scientific assignments.

Do not claim Result20 results or render scientific comparison plots until complete matched Sol/Opus audit coverage is verified.

## Additional checkpoint validation — 10:33 EDT

Non-provider Slurm10357528 passed4/4 temporary-copy restorations of the exact rejected trace checkpoints. The existing native `RevisionWorkspaceManager.restore_last_scored_workspace` copies the latest sealed submission (s001 here), verifies its snapshot, restores canonical task inputs, and does not modify state/session identity; all four resulting solution hashes exactly match sealed metadata. This is narrower than `_rebuild_live_workspace`,which separately discards solver session state.

After prior ownership is terminal,first preserve each changed live workspace and original state/session/manifest evidence,then assess this native checkpoint restoration under exclusive ownership. Re-read current phase/checkpoint/session identity before any mutation and run full native resume validation afterwards. Do not apply while owners are live,patch hashes or infer full resume acceptance from the temporary-copy test. Exact diagnostic source:investigation/result20-report-20260908/checkpoint_restore_smoke.py;receipt:runs/babel-result20-current-20260908/checkpoint-restore-smoke-10357528/result.json.
