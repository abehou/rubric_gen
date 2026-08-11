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

- **23:15 PDT** — The checkpoint restart under `jagupard28` PID 3419076 is healthy and near completion: it reclaimed all 36 unfinished assignments, completed 27 with zero failures, and has nine live assignments whose states all advanced within nine minutes.

- **03:58 PDT** — Relaunched `luna-top30-semi-r10` under PID 1753194 in tmux session `luna-r10`; it reclaimed all 16 interrupted records, live proposers wrote consistent query audits only under `./artifacts`, and two prospective proposals sealed successfully through the repaired validation boundary.
- **04:11 PDT** — The resumed study remains healthy with all 16 assignments owned by PID 1753194, zero new failures, and continued round advancement; 15 assignments are in solver turns, one is judging, and the older state timestamps correspond to live Codex/R subprocesses rather than stale slots.
- **04:24 PDT** — Canceled the `john7` invocation at the user's request; the coordinator required SIGTERM after Ctrl-C stalled, its detached Codex process groups were terminated, no experiment-specific solver/proposer processes remain, and the study lease is available for a clean `--resume` launch.
- **15:32 PDT** — The `jagupard28` resume reached 245/360 completed overall, with 138 completions, three failures, and 16 active assignments under PID 2321650; the three failures are one query-count/audit mismatch and two snapshot rejections of solver-created `artifacts/venv/bin/python` symlinks, with no new failure since 09:13.
- **15:45 PDT** — Interim metadata analysis of 247 completed assignments found prospective rubrics grew by 3,717 characters and 4.15 criteria on average, but rubric length had no score association after assignment/round controls (r=0.022, permutation p=0.422); evolved-only criteria deducted 1.54 points per evolved round on average.
- **15:45 PDT** — The matched completed subset favored prospective evolution by 12.1 final-score points, but this remains selection-sensitive while the study is running, and 53 early zero-query `no_patch` proposals across 33 prospective assignments must be flagged or repaired before final inference.
- **17:15 PDT** — The 24-concurrency restart under `jagupard28` PID 1862039 is healthy after 68 minutes, with 19 completions, zero failures, 24 correctly owned active assignments, and successful retries of all three assignments that failed in the preceding invocation.
- **20:25 PDT** — The 24-way invocation is dead despite `study.json` retaining 24 stale `running` records: the cross-node lease is available, no state or outcome has advanced since about 19:22, and one additional prospective assignment failed from the recurring query-count/audit mismatch before termination.
- **20:44 PDT** — No recovery invocation has started: the same lease remains available, all 24 recorded workers are now 82–117 minutes stale, and the manifest is unchanged at 324 completed, 12 failed, and 24 abandoned-running records.
- **21:13 PDT** — Clarified resume semantics: `--resume` creates a new invocation but skips the 324 validated completions; the 36 unfinished assignments retain 0–8 sealed scores, while interrupted solver turns are replayed from their last sealed boundary and cross-node restarts rebuild the live workspace rather than continuing in-flight model calls.

## 2026-08-09

- **10:40 PDT** — The completed 2×2 RH analysis found fewer majority-vote detections under the diligent prompt (complete-block risk difference −7.9 points, permutation p≈0.0008), but no supported prospective-rubric main effect or interaction. This prompt result is detector-sensitive—present for Claude/Gemini and absent for GPT or the any-detector ensemble—so it is evidence about conservative detector agreement, not yet a robust reduction in reward hacking.
- **10:52 PDT** — Changed the main 30-task, three-replicate experiment from semi to full feedback and assigned it the distinct `luna-top30-full-r10` identity and output tree, preserving the completed semi-feedback study instead of mixing protocols.
- **14:08 PDT** — The first `luna-top30-full-r10` invocation is healthy under `jagupard28` PID 3853299: 49/360 assignments completed in about two hours, all 24 worker slots are live, no failures occurred, and the oldest state belongs to a trajectory still writing actively.
- **15:00 PDT** — Generated reproducible PNG/PDF figures for the completed semi-feedback study showing majority-vote RH rates across the 2×2 cells and task-clustered mean score trajectories across all 11 submissions.
- **15:23 PDT** — Moved finalized study figures out of ignored run storage into a tracked `figures/luna-top30-semi-r10/` tree while keeping bulky raw experiment artifacts ignored.
- **15:35 PDT** — Added a separate `all-behaviors` ensemble target that flags concrete ordinary errors, weak reasoning, incomplete work, noncompliance, refusal/giving up, lucky success, sabotage, and existing MALT abnormal behaviors without redefining the narrow RH outcome; completed Biomni studies now support explicit post-hoc broad audits.
- **15:43 PDT** — Archived the completed semi-feedback protocol as `experiments/luna-top30-semi-r10.yaml` and repointed its study metadata away from the now-full-feedback main YAML; all 360 historical assignments validate for post-hoc ensemble detection without modifying trajectories or outcomes.
- **15:56 PDT** — Added a dedicated `MALT preparation` progress bar before model judging so provider token counting and prompt-boundary planning no longer look like a frozen detector; the focused detector suite passes (62 tests).
- **16:22 PDT** — Replaced the deterministic partial-feedback draft with an LLM-based `simulated_user` policy that independently reviews the current answer against the private rubric and comments on a non-exhaustive subset without seeing scores or judge reasoning. Generated comments and provider provenance are sealed separately for exact resume, only the comment is exposed to the solver, and all 333 tests pass (1 skipped).
- **19:05 PDT** — The `luna-top30-full-r10` invocation on `jagupard28` is dead at 162/360 completed: its lease is free, all 30 recorded workers have been stale for 68–90 minutes, and no assignment failure was captured, indicating coordinator termination rather than a workflow-reported error.
- **22:17 PDT** — The resumed `luna-top30-full-r10` invocation on `jagupard28` is healthy at 257/360 completed, with a held lease, 30 advancing workers, and zero failures; the oldest state file belongs to a solver whose trajectory is actively writing.

## 2026-08-10

- **10:47 PDT** — Generated repository PNG/PDF figures comparing semi/full score trajectories and narrow RH detections, plus a separate semi-feedback broad listed-behavior plot; all three audits retain 352 complete panels and 82 complete randomized blocks. Cross-feedback comparisons are labeled descriptive because the separate studies began from sharply different mean scores (10.4 semi versus 59.7 full), while the broad 82–87% endpoint is explicitly not presented as an RH rate.
- **11:12 PDT** — In the completed full-feedback study, prospective rubrics scored 1.84 points lower on average after revision and 2.71 points lower at the final round, whereas the semi-feedback study showed gains of 9.36 and 5.06 points. These are measurement-relative contrasts because prospective answers are scored with their evolving rubric versions; a common fixed-rubric or rubric-free evaluation is required to infer actual solution quality.
- **11:36 PDT** — Diagnosed that the current prospective proposer targets generic process failures and exposes each new penalty to the same solver, with dynamic-only traces showing retrospective checkpoint fabrication, evaluator-language scrubbing, and self-authored audit compliance. The recommended successor keeps task quality fixed and places only prospective, private, harness-verifiable, concealment-resistant checks in a separate integrity layer after counterfactual red-team validation.
- **12:20 PDT** — Implemented experiment-schema-2 integrity generator v2 without an acceptance gate: quality stays frozen at `r0000`, private checks activate only after their evidence boundary, and only natural remediation reaches the solver. Removed the schema-1 evolution interface, separated quality scores, integrity penalties, and rewards, moved the active/full and preflight YAMLs to new v2 run trees, and passed 333 tests (1 skipped).
- **14:11 PDT** — Recovered and audited integrity-generator v2 against 3,600 legacy proposal decisions: 1,442 patches were added, 359/360 prospective assignments received at least one, and majority-RH-positive assignments averaged 4.87 patches versus 3.90 otherwise. V2 fixes rubric comparability and retrospective activation, but its missing promotion gate, free-form single-lineage checks, self-assessment, targeted remediation, and compensable penalties require replacement with shadow discovery, cross-fitted validation, independent assessment, and hard integrity gating.
- **14:31 PDT** — Rejected the gated dynamic-rule design as too complex and reduced the recommendation to a frozen quality rubric plus one hidden reward-hacking veto: a detected violation sets reward to zero and terminates the episode, while no generated criterion or targeted remediation reaches the solver.
- **14:40 PDT** — DR Tulu and EvoRubrics show that useful dynamic criteria come from contrasts among several current responses, survive only when they separate those responses, stay in a fixed small pool, and receive independent criterion-level judgments. The current workflow instead grows one rubric from one solver-written trace and judges all criteria together, so the next design should generate one short outcome challenge from each three-replicate batch and expire it after one round.
- **14:47 PDT** — Replaced the ambiguous “challenge” concept with several independent singleton rubric sets: each set contains one short criterion, must produce a distinct nonconstant score pattern across current replicas, and contributes separately to an averaged reward.
- **15:47 PDT** — Placed dynamic rubric sets inside a synchronized three-replica revision loop as the feedback and optimization signal, while a common frozen evaluator and independent reward-hacking audit remain outside the loop as hidden measurements. The clean next comparison freezes identical short rubric sets in the control arm and refreshes them in the treatment arm, with all other revision settings fixed.
- **15:55 PDT** — Rejected synchronized peer submissions as a deployment assumption and replaced them with a single-lineage, outcome-trained rubric generator. Offline training forks historical states under candidate one-line criteria, retains criteria that cause the best independently verified clean revision and reject reward-hacking continuations, and deploys the trained generator from only the current submission and its prior versions.
- **16:21 PDT** — Across 360 matched static–dynamic pairs, 344 complete detector panels gave 7.0% static versus 6.7% dynamic majority-RH rates; the within-task length slope was +1.9 points per 1,000 added characters (95% task-cluster interval −1.0 to +4.7, permutation p=0.207). Rubric length, criterion count, update count, and penalty capacity were nearly or exactly collinear, and the positive GPT-only result did not survive detector-family correction.
- **16:37 PDT** — Added `TRAINING_PLAN.md` with the full single-lineage protocol: matched `no_patch` continuations estimate criterion effects, high-confidence reward hacking vetoes candidates, adversarial continuations test superficial compliance, and rejection-sampling fine-tuning precedes any preference training or untouched evaluation.
- **16:42 PDT** — The current non-normal detector cannot audit the completed `luna-top30-full-r10` study because its archived experiment is schema 1 and the current loader accepts only schema 2. A non-normal audit now requires a completed current-format `luna-top30-full-integrity-v2-r10` study rather than a compatibility path for the old artifacts.
- **16:51 PDT** — Added `rubric_v1_analysis.md` with the complete legacy static-dynamic rubric analysis, concrete useful and evaluator-drift examples, matched RH results, and reproduction steps. The analysis attributes the unsupported −0.3-point majority-RH contrast to target mismatch, reactive unvalidated patches, revealed and compensable proxy criteria, model monoculture, single-lineage overfitting, and detector disagreement.
- **16:52 PDT** — Appended complete-panel `any_detects` panels beneath the majority-vote panels in the feedback-comparison RH figure. Any-detector cell rates range from 18.0% to 37.9%, versus 1.1% to 12.6% for majority vote, which exposes substantial detector disagreement without changing the 352-panel denominator.
- **17:00 PDT** — Rolled the active runner back from schema 2 to schema 1 as the sole accepted contract, restored prospective rubric evolution and the `luna-top30-full-r10` output tree, and removed the integrity-policy implementation. The active configuration loads all 360 assignments, and all 333 tests pass (1 skipped).
