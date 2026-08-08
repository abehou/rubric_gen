# Experimental Log

## 2026-08-06

- Replaced hash-bound randomized-study configuration with an `experiment.yaml`
  DAG and updated the seed, revision, and detection workflow to use it directly.
- Added recovery for missing live workspaces, cross-filesystem proposer evidence,
  normalized Codex configuration, and lost Codex sessions; tests passed, but the
  resumed run subsequently exposed additional validation and model-output failures.
- The latest randomized-study run advanced both static revisions and prospective
  rubric evolution, but completed revisions were rejected because manifest keys
  and the validator disagree; the run should not be treated as usable yet.
- Fixed the current revision manifest schema to persist and validate judge and
  rubric-proposer endpoints consistently; all 309 tests pass, and the real
  11-round assignment that was previously rejected now validates successfully.
- After restart, the fixed validator accepted 12 completed static assignments;
  17 other sixth-attempt assignments still failed while recovering older
  interrupted states, chiefly due to incomplete solver-turn artifacts.
- **22:09 PDT** — Fixed interrupted-turn recovery to handle attempt-only artifacts
  and partially attested solver identities by restoring the last sealed boundary
  and restarting the session; all 310 tests pass.
- **22:37 PDT** — The resumed seventh attempt crossed the repaired recovery
  boundary without new artifact or identity failures; its first three failures
  were instead prospective rubric proposers returning no JSON after both retries.
- **23:59 PDT** — Since the 22:33 restart, all 39 accepted completions were static
  while all 65 finished prospective assignments failed in rubric proposal, showing
  that recovery works but the prospective treatment is currently non-runnable.

## 2026-08-07

- **00:06 PDT** — Replaced unconstrained proposer text with Codex-native JSON Schema
  output captured directly into `answer.txt` and retained malformed attempts for
  diagnosis; all 311 tests pass, pending live prospective verification after restart.
- **00:27 PDT** — Added `experiment_preflight.yaml` with three previously failing
  proposer tasks, one replicate, all four conditions, and two revision rounds for
  a 12-assignment isolated end-to-end debug run.
- **00:51 PDT** — The preflight completed three static assignments but failed all
  five finished prospective assignments; retained traces show the proposer made
  zero trajectory queries because its sandbox referenced a missing Codex binary.
- **01:33 PDT** — Fixed prospective proposer execution by mounting Codex's native
  helper and bundled `rg` read-only and making the bounded query tool self-contained
  and relocation-safe; three clean live proposers made 5, 8, and 7 audited queries,
  and all 313 tests pass (1 skipped).
- **01:37 PDT** — Rejected proposer decisions that retrieve no trajectory events
  after a live retry incorrectly sealed a zero-query `no_patch`; all 314 tests pass
  (1 skipped), and the contaminated preflight was archived before a clean restart.
- **13:37 PDT** — The clean preflight completed all 12 revisions and all prospective
  proposals were grounded, but final validation falsely failed all six prospective
  assignments because it expects `--prospective` instead of the configured
  `-prospective` condition-ID suffix.
- **14:03 PDT** — Replaced condition-name inference with explicit
  `rubric_evolution` metadata in final validation; the existing preflight revalidated
  all 12 assignments in 23 seconds with no model reruns and now finishes successfully.
- **15:43 PDT** — Removed git/source-tree hashes from detector run identity and made
  DAG resume start detection when no matching evaluation exists; the zero-cost stale
  detection attempt was archived, and all 315 tests pass (1 skipped).
- **15:54 PDT** — Fixed the fresh-detection resume handoff so a newly allocated
  evaluation starts with `resume=false` while existing evaluations remain strict;
  the empty failed attempt was archived, and all 315 tests pass (1 skipped).
- **16:15 PDT** — Made RH verdict schemas Anthropic-compatible by removing unsupported
  numeric bounds while retaining local range validation; the live token-count API
  accepted the exact schema, all 316 tests pass (1 skipped), and the resumable
  detection attempt remains at zero recorded cost.
- **16:45 PDT** — The preflight RH audit completed all 36 judgments across 12
  complete three-model panels with zero detections and $8.23 observed cost; a tiny
  negative reserved-cost epsilon remains a defect for future resume validation.
- **17:46 PDT** — Attempt 8 of the full `luna-top30-semi-r10` study is live with
  16 active assignments and frequent state writes, but its first five outcomes
  are three completions and two failures (zero proposer evidence and task-data mutation).
- **17:58 PDT** — Allowed solver mutations to the disposable workspace `data/`
  copy, added a persistent `artifacts/` directory for generated outputs, and kept
  source-corpus integrity checks; the full suite passes (319 passed, 1 skipped).
- **18:11 PDT** — Attempt 9 loaded the new workspace policy and advanced both
  previously failed assignments, with one completion and no new failures so far;
  17 dead-PID records remain falsely `running` and threaten final DAG completion.
- **18:17 PDT** — Added an exclusive one-writer study lease and resume-time
  reclamation of abandoned `running` records, so interrupted assignments become
  retryable without permitting concurrent runners; all 321 tests pass (1 skipped).
- **20:16 PDT** — The live worker cleared the stale queue and reached 92 completed
  assignments, but 42 resumes failed strict `next_prompt` validation because the
  new `artifacts/` initial prompt disagrees with prompt text stored before that change.
- **21:13 PDT** — Made persisted prompts authoritative and validated interrupted
  turns against their executed `prompt.txt`, added idempotent promotion of sealed
  snapshots and `./artifacts` guidance to all feedback prompts; 324 tests pass (1 skipped).
- **21:26 PDT** — Suppressed solver event rendering for experiment seed and revision
  stages while retaining complete trajectory logs, leaving progress bars as the
  normal terminal output; 325 tests pass (1 skipped).
- **22:10 PDT** — The post-fix invocation acquired the study lease under PID 1993319, owns exactly 16 live assignments with fresh state writes, and has no stale records or new failures; first completions are still pending.
- **22:50 PDT** — The invocation remains live and produced three completions, but two prospective assignments falsely failed as zero-query proposers because they followed the new isolation guidance and moved query audit files from `data/` to `artifacts/` while validation still reads the old location.
- **22:58 PDT** — Moved proposer query accounting canonically to harness-managed files under `./artifacts`, removed the old `data/` accounting interface, and added explicit missing-audit validation plus regression coverage; the full suite passes (326 passed, 1 skipped).

## 2026-08-08

- **03:58 PDT** — Relaunched `luna-top30-semi-r10` under PID 1753194 in tmux session `luna-r10`; it reclaimed all 16 interrupted records, live proposers wrote consistent query audits only under `./artifacts`, and two prospective proposals sealed successfully through the repaired validation boundary.
- **04:11 PDT** — The resumed study remains healthy with all 16 assignments owned by PID 1753194, zero new failures, and continued round advancement; 15 assignments are in solver turns, one is judging, and the older state timestamps correspond to live Codex/R subprocesses rather than stale slots.
- **04:24 PDT** — Canceled the `john7` invocation at the user's request; the coordinator required SIGTERM after Ctrl-C stalled, its detached Codex process groups were terminated, no experiment-specific solver/proposer processes remain, and the study lease is available for a clean `--resume` launch.
