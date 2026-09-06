# BioMNIBench red-team experiment plan

Updated: 2026-09-05 (Asia/Shanghai). This file owns the approved experiment scope
and current checkpoint. For routine operation, read Approved scope, Research
objectives, and Current status; the explicitly historical sections are evidence,
not a setup checklist. The reusable operating procedure lives in
[rubric-experiments](skills/rubric-experiments/SKILL.md).

## Approved scope

Run `experiments/biomnibench-results20-user-simulator-full.yaml`: 20 tasks,
three replicates, and four conditions (240 assignments). Cross `full` and
`user_simulator` feedback with `red_team_artifact` and `red_team_trace`.
The user accepted this focused trace ablation; adding a no-red-team control is
not a prerequisite. Solver, seed generator, red team, and proposer use Luna.
Outcome audits use `gpt-5.6-sol`, `claude-opus-5`, and `gemini-3.8-flash`
(updated by the user during acceptance; 3.6 is no longer the requested judge).
Revision completed at concurrency **30**, selected at 12:26 CST after concurrency
60 overloaded the laptop. At 12:30 the user authorized adaptive balancing and
suggested 40 as a candidate, not a mandatory immediate switch. Evaluate sustained
CPU, compressed-memory/swap growth, throughput and connection failures before
raising it; avoid repeated interruption of unfinished calls. Audit concurrency
may differ because its workload is primarily hosted requests. The CLI default
remains 60; pass the chosen concurrency explicitly. Reuse the user-approved local credentials without
printing them or storing them in tracked artifacts.

Since the 20:10 recovery, launch current workflow commands with the explicit
`PYTHONPATH=/Users/yuenanhuang/Desktop/rubric_gen/src` environment. Editable-install
startup files are repeatedly marked hidden by an unidentified actor; this
standard source-path launch was verified through the real SDK/solver path and
does not change the frozen protocol or generation identity.

The user clarified at 11:07 CST that short small tests and roughly one-to-two-hour
full runs are time targets, NOT hard deadlines. Do not use `bounded_run.py` for
future runs and do not stop merely because an estimate is exceeded. Report
updated ETA ranges and bottlenecks at milestones. Keep the configured per-call
failure safeguards, but impose no overall run cutoff. Concurrency may vary with
workload and observed resource pressure; it cannot remove dependencies inside
one assignment. The earlier deadline interruptions below were an assistant
misinterpretation and are historical records, not the current operating rule.

Operational reliability is the first priority. The user explicitly requested
a small end-to-end run before scaling, superseding earlier decisions to defer
small reliability runs. Use existing workflow commands and configuration;
do not add a public preflight or dry-run command.

## Execution sequence (acceptance and revision complete; continue from current status)

1. Confirm collaborator main, preserve local fixes, and adapt Bio/Paper YAML
   task paths to repository-relative local dataset locations.
2. Validate dependencies and relevant regression tests. Inspect dataset size
   and free storage before downloading the configured Results20 tasks.
3. Reuse the valid current-format `da-18-1` seed blocks and prepare five
   paraphrases. Shorten the small-run horizon rather than repeating the full
   ten-turn protocol: acceptance uses all four conditions, three turns
   (the minimum compatible with post-update detection), and all three audit models.
   Complete this check without an overall cutoff, updating the ETA as needed. The full
   Results20 five-turn minimum / ten-turn maximum remains unchanged.
4. Require four valid completed revisions and successful completion of all
   seven audit stages. Inspect real red-team records, rubric gap/admission and
   fallback records, simulator feedback, and provider errors. A run completing
   only because every proposer stage fell back is not sufficient verification
   of the red-team mechanism. Detector abstentions remain legitimate outcomes.
5. Fix reproducible operational failures and verify the affected path. Freeze
   protocol code and configuration before the full run. Do not edit hashed
   implementation files under active workers. Keep old outputs separate when
   identity changes; never fabricate compatibility metadata.
6. Launch the approved 240-assignment experiment at measured concurrency (currently 30), monitor
   through seed, paraphrase, shared pretreatment, revision, and all audits, and
   resume only valid current-format work when needed.
7. Report completion, exclusions, resource use, errors and repairs, provider
   coverage, rubric changes, and task-balanced condition outcomes.

## Monitoring and recovery

Follow the reusable skill's monitoring/recovery procedure. Run-specific facts:

- All invocations are terminal. Final semantic recovery exited 0 at 02:20:10;
  the complete seven-stage gate passed 240 assignments and 9,327 unique judgments.
  Formal results are in `runs/reports/20260905-redteam-v7/REPORT.md`.
  The c12 main invocation
  terminated with exit 1 by 01:12 on September 6; it is no longer running.
  Completed local revisions used 30. Neither 40 nor 60 is a required setting.
- Structured requests use a 300-second timeout; solver sessions use 7,200 seconds.
  These are per-call safeguards, not overall experiment deadlines.
- Check around once a minute at startup and every few minutes during steady
  progress, adjusting to failures and stage transitions. Keep user updates concise.
- Use the private monitor and coverage/outcome helpers under `runs/diagnostics/`;
  current manifests, reports, and invocation paths are indexed in `EXPERIMENT_RUNS.md`.

## Research objectives and interpretation

The user's hypotheses are that dynamic rubrics reduce RH across four measures,
and that user-simulator feedback lowers RH relative to full feedback under each
rubric policy. Following `eval_exp.md`, the four measures are:

1. Final weak-minus-strong score under the same original rubric.
2. Final strong selected-minus-held-out rubric score.
3. Final strong original-rubric-minus-rubric-free quality score.
4. Direct final-artifact RH decision and its missingness bounds.

Also retain full-trajectory, post-update, and final-revision direct audits as
separate behavioral outcomes. Smaller signed gaps require joint quality
interpretation: degrading proxy scores alone is not evidence of improvement.
Preserve negative gaps, report quality gains and pairwise preference, and keep
task clustering and matched replicate comparisons. Sidecars are discovery
evidence and never count as natural RH outcomes.

Treat desired directions as hypotheses. Report contrary and null results, failed
assignments, and model disagreement. First make the current protocol work; then
use development cases to propose versioned changes. Changes informed by Results20
are exploratory and require separate evaluation for a confirmatory claim.
Do not alter judges, thresholds, exclusions, or outcome definitions to favor the
expected result. Keep the currently deferred validator-model and held-out
red-team-audit changes deferred unless the user changes their scope.

## Current status

**September 6, 02:22 CST — completed experiment:** delayed c1 recovery session
31197 ended at 02:20:10 with both stage statuses 0, preserving all 4,827 rubric
and 1,619 quality records and adding the last Claude absolute score. Absolute
900/900 and pairwise 720/720 now have successful summaries. The full strict gate
passed all 240 assignments, seven stages and 9,327 unique judgments with complete
three-model coverage. Frozen analysis completed and the honest report is saved:
`runs/reports/20260905-redteam-v7/REPORT.md`, with `outcomes.json` and
`audit-coverage-complete.json` alongside it. No process remains live.
Simulator reduces the original-minus-rubric-free gap by about 9.4 points in both
red-team conditions; other primary contrasts do not establish uniformly reliable
improvement. No claim of isolated red-team benefit or superiority across rubric
policies is supported by this four-arm design. Future reliability/code changes
are recommendations for a new version, not modifications to completed v7 data.

**September 6, 02:19 CST latest:** one delayed serial semantic recovery is live,
session **31197/controller 83729**, c1, launched in the 02:18 minute; rubric resume
logged **02:19:11**, with 4,827 cached records. Log:
`runs/logs/results20-v7-semantic-recovery4-c1-20260906-0218.log`.
The helper is unchanged and validated; approximately 40 minutes elapsed since the
last quality failure and subsequent Claude preparation calls succeeded, though
this does not prove the failing generation path is healthy. Allow 3–8 minutes;
if the same connection failure recurs, stop further unchanged attempts.
Full coverage gate at 02:18 passed direct-window checks but stopped at the missing
absolute summary. The final report remains outstanding.

**September 6, 02:17 CST latest:** session 70066 exited 0 at 02:17:08 with all 720
prior scores byte-identical and no new scores. Independent verification at
02:17:26 passed exact 240-assignment/three-model coverage and raw/summary agreement,
zero failures; all four direct windows are now verified complete. Receipt:
`runs/reports/20260905-redteam-v7/full-trajectory-completion-verification.json`.
No experiment process remains live. One Claude absolute score remains missing
(899/900); pairwise has 720/720 raw scores but both quality summaries are absent.
The full completion gate and formal outcome report remain outstanding.

**September 6, 02:08 CST latest:** cached full-window reconciliation is running,
session **70066/controller 82498**, concurrency **2**, launched **02:08:32** using
the unchanged validated helper with 720 existing scores. Log:
`runs/logs/results20-v7-full-window-cache-reconcile-c2-20260906-0208.log`.
This normal resume pass targets the preparation-only failed summary entry;
estimate 8–12 minutes and verify raw/summary consistency after termination.
Claude absolute's independent repeated-disconnect failure remains paused.

**September 6, 02:07 CST latest:** session 61718 ended with exit 1 at 02:07:20,
preserving all 716 previous scores and recovering all four Gemini gaps. Full
trajectory now has 720 completed raw scores (240/model), but its summary has one
attempt-zero Claude APIConnectionError during preparation, case revision-000084
(`da-13-5/rep-003/luna/user-simulator-red-team-trace`), whose cached completed
score remains intact. Do not synthesize a passing summary or call this verified
completion. No invocation remains live; Claude absolute still lacks one score
and both quality summaries remain absent. Terminal archive:
`runs/provenance/20260905-redteam-v7/audit-v2/full-window-c2-terminal2-20260906-0207.tar.gz`.

**September 6, 01:58 CST latest:** full-window recovery session **61718/controller
80898** is live, launched **01:57:51**, concurrency **2**, starting with 716 scores.
Log: `runs/logs/results20-v7-full-window-recovery2-c2-20260906-0158.log`.
This unchanged validated helper retries four Gemini TPM failures after the
server-requested cooldown; all 197 archived runtime/config/analysis files still
match, with only the documented AGENTS.md difference among 198 archive entries.
Allow 9–15 minutes for this pass, including full preparation overhead; this is
not an ETA for resolving the independent Claude quality failure.

**September 6, 01:56 CST latest:** full-trajectory c2 recovery terminated with exit 1
at 01:56:11, preserving 710 prior scores and adding six: 716/720, with Sol/Claude
240 each and Gemini 236. The four remaining summary failures are Gemini HTTP 429
input-token-per-minute limits (3,000,000 TPM, retry delays 49–55 seconds), cases
000076/000100/000118/000207; no preparation failures remain in this summary.
All experiment processes are terminal. Archive:
`runs/provenance/20260905-redteam-v7/audit-v2/full-window-c2-terminal-20260906-0156.tar.gz`.
Next recovery should account for the provider's cooldown rather than increase
concurrency; Claude remains paused as described below. Full audit remains incomplete.

**Previous launch, September 6, 01:48 CST:** full-trajectory-only recovery,
session **11630/controller 79314**, c2, launched at **01:46:49** via
`runs/diagnostics/resume_full_trajectory.py`. The existing production API and
unchanged YAML operate only on this window; cached small validation preserved
12 scores and the full acceptance gate remains 153/153. Prior runtime/config/
analysis identities remain frozen. It starts from 710 raw successes, needing ten
Gemini judgments and reconciliation of four preparation-failed cached summaries.
Allow about 10–20 minutes from launch, conditional on provider response; preserve
successes and do not loop unchanged access errors indefinitely.

Revision 240/240 and rubric scoring 4,827/4,827 are independently verified.
Post-update, final-artifact and final-revision direct panels each pass independent
720/720 checks with zero failures; the complete terminal panels and verification
receipts are in the indexed v7 provenance/reports directories. Direct suite
session 16124 ended at 01:39:55 with historical full-trajectory exit 1 only.

Semantic tail session 48415 ended at 01:35:02 with exit 1, preserving all 4,827
rubric and 1,618 prior quality scores and adding one. Absolute raw coverage is
899/900, pairwise 720/720; both quality summaries remain absent. The remaining
Claude absolute key `2ee448dfd3eac7a466f639a9f2e90ee2` maps to `da-15-2`, replicate 3,
user-simulator/red-team-artifact final submission `s010` (one assignment reference).
It repeatedly encounters a
server-disconnect/APIConnectionError, so further immediate retries are paused.
Asked the user whether network/API configuration changed or service issues are
visible; no keys requested or routing changed. This is not whole-audit completion.

### Historical recovery checkpoints (do not treat old processes as live)

**September 6, 01:31 CST:** main audit session 40033/controller 46331
terminated with exit 1 after the quality loop processed all 1,620 jobs; the final
exception chain reports an Anthropic APIConnectionError, and neither quality
summary was published. Raw quality results remain 863/900 absolute and 707/720
pairwise: 50 missing (48 Claude, two Sol), not proof all share the first exception's
cause. The quality directories and terminal log are archived in audit-v2 provenance.
Together with 39 rubric failures, there were 89 missing semantic judgments.
The validated frozen semantic-only helper started at 01:13:13, session 87050,
controller 74221, concurrency 3, using existing approved credentials and unchanged
protocol/model identities. Small acceptance remains 153/153; old controller absence
was verified before launch. Rubric recovery ended at 01:18:48 with 4,827/4,827
successes and zero failed jobs, preserving all 4,788 prior raw records and adding
39. Independent stage-only raw/plan/summary checks passed all 240 assignments
and all three models at 01:19:26; see `rubric-score-completion-verification.json`
in the v7 reports directory. The completed rubric stage is separately archived.
That first c3 recovery ended at 01:24:10 with exit 1 after another Anthropic
connection error: all 1,570 prior quality scores stayed unchanged, 48 were added,
and two Claude absolute scores remain missing (898 absolute, 720 pairwise).
Both quality summaries remain unpublished. Its terminal quality/log archive is
`semantic-recovery-01-quality-terminal-20260906-0125.tar.gz` in audit-v2 provenance.
After verifying controller 74221 was gone, started the same unchanged helper
again at 01:26:03 (session 91043/controller 76474, c3) for just those two missing
scores; completed scores used normal validated cache reuse. This second recovery
ended at 01:28:38 with no new scores and a server-disconnect/Anthropic connection
exception, preserving all 4,827 rubric and 1,618 quality records; its terminal
archive is `semantic-recovery-02-quality-terminal-20260906-0129.tar.gz`.
Read-only planning shows both requests are within this batch's size range and the
same evidence is scored by Sol/Gemini; that does not establish the disconnect's
physical cause. Changed only the idle private helper's concurrency constant to 1,
validated cached small recovery (105 records unchanged, full gate 153/153), and
archived the new helper separately. Serial recovery started at 01:31:17, session
48415/controller 77227, for the same two Claude scores. Allow a few minutes subject
to connection retries; if the same failures recur, retain the evidence and pause
further immediate retries instead of looping. This is not a whole-audit ETA.
Do not loop unchanged permanent-access failures indefinitely.
Direct session 16124/controller 62758 completed post-update at 01:32:15:
720/720 successes, no failures, all 617 prior scores unchanged and 103 added.
Independent stage-only raw/summary and exact 240-assignment/three-model checks
passed at 01:33:21; the completed panel is archived and its verification receipt
is `post-update-completion-verification.json` in the v7 reports directory.
The same c1 process now runs final-artifact recovery, followed by final revision;
full trajectory still needs its 10 absent Gemini scores and four cached-summary
failures reconciled through the current workflow. Aggregate current cap is 2.

**September 6, 00:49 CST latest:** rubric scoring finished its first c12 pass at
00:47:32, with 4,788/4,827 successes and 39 terminal failures (Sol 4, Claude 13,
Gemini 22). Nineteen failures have only transport errors across their attempts;
20 Gemini failures involve unsupported location (four also had transport errors).
The complete rubric directory, including all prior failed attempts, is archived
as `formal-attempt-02-rubric-score-20260906-0048.tar.gz` in audit-v2 provenance.
Main session 40033 has moved to absolute/pairwise quality scoring (900 + 720 jobs);
at 01:02:58, 863 absolute and 54 pairwise scores are saved, including all three
models in both instruments. The processed/saved gap is not a final failure count
until the runner finishes; do not declare absolute complete because pairwise has
started. Allow roughly 10–25 further minutes from 01:03 for this quality pass,
with direct recovery and any remaining failure recovery additional; this is not
a whole-audit completion guarantee.
Direct c1 recovery session 16124 finished full trajectory at 01:03:51 and entered
post-update preparation with 617 prior scores. Full trajectory now has 710 raw
successes (Sol 240, Claude 240, Gemini 230), with all 594 prior scores byte-identical
and 116 new scores. Its current summary has 706 successes and 14 failures: nine
Gemini unsupported-location, one Gemini transport, and four preparation transport
failures masking intact cached scores (two Sol, two Claude). The new complete
panel archive is `direct-recovery-01-full-trajectory-20260906-0104.tar.gz`; this
panel is still incomplete, and a further unchanged retry is not a substitute for
resolving permanent access failures. The other direct summaries remain historical
until their new passes end. The prepared semantic recovery helper remains
unlaunched while the main semantic writer is active.

**23:55 CST audit recovery checkpoint:** revision is complete, 240/240, with
attempt 3 ending at 21:41:16 (session 73847/controller 89959, exit 0). All 237
completions in the full independent check and the final three in its supplement
passed current-format validation; both checklists are in `runs/reports/20260905-redteam-v7/`.
The complete terminal study/log archive is preserved, including the earlier
attempt histories and the two first-turn replacements' quarantine.
Only after revision ended, repaired direct-audit mixed-failure exit status;
110 focused and 744 full tests pass (two pre-existing environment exclusions).
Generation identity and study IDs are unchanged; do not rerun the 240 revisions.
Source/analysis is frozen in the 198-file audit-v2 archive; see
`runs/provenance/20260905-redteam-v7/audit-v2/README.md`.
At 23:22, the user-requested maintenance-guidance revision changed only `AGENTS.md`
among those 198 archived files; the other 197, including every runtime/config
and frozen analysis file, remain identical. The immutable archive is retained;
do not describe the working tree as an exact 198-file match after this change.
Fresh acceptance passed the independent gate at 153/153 after serial recovery;
all 149 earlier successful records remained unchanged. Formal audit is live in
`runs/detections/20260905-redteam-v7-audit-v2/`, recovery session 40033/controller
46331 at concurrency **12**, launched about 22:12:40 with `detect --resume`.
The initial concurrency-30 invocation was interrupted after a large failure gap;
its archive preserves 238 successful scores, all verified byte-identical during
recovery, along with all 198 frozen source/analysis files. The full-trajectory
stage ended with 593 summary successes and 127 failures (84 Gemini input-TPM
429s, 35 transport failures, eight Gemini unsupported-location 400s). There are
594 intact raw successes because one Sol preparation failed before cache lookup.
The full stage is archived. Post-update is also archived, with 617/720 successes
and 103 failures: 54 Gemini TPM-limit, 35 transport, seven Gemini unsupported-
location and seven Claude insufficient-credit errors. Final-artifact detection
ended with 719/720 successes: Sol/Claude each 240, Gemini 239, with one Gemini
unsupported-location failure; its complete stage is archived. Final-revision
detection also ended and is archived: 715/720 successes, three transport and two
Gemini unsupported-location failures. All direct passes retain 2,645 raw successes
out of 2,880; recovery must also refresh the one preparation-failed summary record
whose cached score is intact. Rubric scoring began about 23:03:45 with the actual
manifest confirming 4,827 unique jobs (2,471 saved at 23:55:23). Recent throughput
is roughly 40–55 saved jobs/minute: allow about 40–70 more minutes for this stage,
with quality scoring/recovery additional and no guarantee of complete recovery.
Gemini region/account eligibility confirmation is also pending after repeated
unsupported-location responses in rubric scoring. User verification
of Anthropic billing is requested; the seven earlier billing errors do not mean
every current Claude call is blocked. Preserve successes,
use lower request rates for recovery, and do not bypass provider region restrictions,
purchase credits or substitute the model panel without appropriate user direction.
Current-source `PYTHONPATH` remains required.

**September 6, 00:01 CST parallel recovery:** session 16124/controller 62758 is
running the existing four direct-stage APIs sequentially at concurrency 1 via
`runs/diagnostics/resume_direct_panels.py`. Session 40033/controller 46331 keeps
rubric/quality at concurrency 12; its sequential command will not revisit direct
directories. The entrypoint passed cached small-panel recovery (48 scores unchanged)
and the full 153/153 acceptance gate before formal use. It checks prior successful
score bytes before/after each panel; all four earlier terminal direct archives
remain intact. Log: `runs/logs/results20-v7-direct-recovery-c1-20260906-0000.log`.
At 00:28:05, rubric scoring has 3,894/4,827 saved records; direct full-trajectory
recovery has 608 raw successes, up from 594. A read-only comparison with the prior
stage archive verified all 594 prior scores byte-identical and 14 newly recovered
failures (13 Gemini, one Claude). Preparation took about 19 minutes and yielded
716 scheduled jobs out of 720, requiring reconciliation when the panel ends.
Recent connection retries caused a temporary throughput dip; both live handles
and controllers were rechecked at 00:28 without interruption. The displayed direct summaries
remain historical until each recovery panel publishes a replacement. Main session
40033 may still exit nonzero from its earlier collected direct statuses even if
this separate recovery repairs them: verify current raw/summary coverage and both
invocation results rather than blindly restart the entire audit.
If semantic scores remain incomplete after session 40033 terminates, the private
`runs/diagnostics/resume_semantic_panels.py` calls only the existing rubric/quality
runners at c3, leaving direct directories untouched. Its cached small acceptance
passed at 00:30 with all 105 prior semantic records unchanged and full coverage
still 153/153; the helper/log are archived in audit-v2 provenance. Do not start it
against the formal study while the current semantic writer is live; inspect and
archive terminal failures first, and do not repeatedly retry permanent access errors.
Preserve and report five rubric response-validation fallbacks (including the
20:48 and 21:06 pair-ID validation fallbacks in da-12-2/rep-002 and
da-19-1/rep-003/simulator-artifact) and six sealed
red-team exclusions; do not rewrite these as successful evidence.
The revision ETA is superseded by actual completion. Both the old 30–60-minute
and later 1–2-hour audit estimates are superseded: at 22:40, read-only exact planning
established 4,827 rubric + 900 absolute + 720 pairwise judgments, in addition to
four 720-judgment direct stages (9,327 total). Provisionally allow 2–4 additional
hours from 22:40, conditional on provider health, recovery and formal rubric-stage
throughput; small c6 acceptance took 263s/78 rubric and 39s/27 quality jobs.
See `runs/reports/20260905-redteam-v7/audit-planned-counts.json`. No hard cutoff.

## Historical checkpoints (superseded; not current process state)

**15:45 CST recovery update:** initial v7 session 8165 ended at 15:42:36 with
68 completed and 172 failed records; its full study/log archive is preserved.
Supported recovery session 78150 (controller 36019) now has 30 active assignments
at concurrency 30 and produces new trajectories/rubrics, without new import errors.
All 68 prior completed assignments passed current validation and their 16,543
files remain unchanged. Two first-turn failures cannot resume without missing
trajectories: after this invocation, quarantine their exact failed directories
and regenerate only those assignments from valid seeds using current workflow;
do not fabricate metadata or interrupt healthy active work. All 195 frozen source
files matched before launch. Revision ETA is provisionally 17:30–18:30 CST based
on pre-incident throughput, to be recalibrated after stable recovery completions.
See `runs/reports/20260905-redteam-v7/environment-incident.md` for evidence and
the separate single response-validation fallback, which remains in the results.

**14:41 CST update: formal v7 launched at concurrency 30**, session 8165, after
fresh acceptance passed 4/4 revisions and all 153/153 three-model audit judgments.
One Gemini transport failure required serial recovery; its full first-attempt
archive is preserved and all 152 prior successful files are unchanged. Acceptance
had six online generations, six included sidecars, one admitted criterion and no
proposer retries/fallbacks or assignment failures. Initial full-run estimate is
1.5–3 hours for revision plus 30–60 minutes for audit; at 15:20 the measured
completion rate revised the revision ETA to **17:00–18:15 CST**, with audit and
the planned stage-boundary repair/verification additional. Estimates remain
conditional on throughput and transport stability, with no overall cutoff. Provider exhaustion
now fails without publishing a generation and reaches the study circuit; validation
fallback behavior is unchanged. New generation identity uses separate
`provider-availability-v7` acceptance outputs and `20260905-redteam-v7` formal
outputs. Regression passed 742 tests with two known environment exclusions;
the new implementation's acceptance gate passed. The direct CLI can exit 0 with
failed judgments, so the independent artifact-level coverage gate is mandatory
before declaring formal audit completion; this automation risk is in CODE_REVIEW.md.
At the natural revision/audit boundary, repair the direct detector's misleading
exit status and verify failure, successful cached resume and abstention cases before
formal audit launch. Keep the running revision source frozen until then, confirm
the rubric generation identity is unchanged, and use fresh audit outputs under
the resulting audit identity; never rewrite existing audit metadata to force reuse.
Validate the changed audit workflow on the completed small study before scaling
the audit, retaining its prior 153/153 acceptance record as versioned history.

**V6d attempt 2 is stopped.** Actual Python controller 951 and
all live descendants stopped at 14:07:04; session 90781 exited 143. There are 18
completed assignments, of which 16 contain provider-connection-induced rubric
fallback, plus 30 interrupted and 192 pending. All original records and a terminal
study archive are preserved. A post-stop minimal proposer call succeeded in 3.09s,
so availability is intermittent, not verified permanently broken or fixed.
The provider propagation/circuit fix is implemented and regression-tested in v7;
fresh small end-to-end verification passed; formal execution is now in progress.
Changing generation implementation identity requires fresh current-format artifacts;
do not rewrite/relabel the v6d fallback history or call it clean formal evidence.
The complete 240-assignment run plus all three-provider audits remains outstanding.
Use the current v7 estimate above, not the superseded v6d ETA.

### Most recent execution — historical, now stopped

- **14:00 CST v6d attempt 2:** resumed session 90781 at concurrency 30 after a
  controlled 13:55 stop for nested OpenBLAS threading and project-Python PATH drift.
  Two complete assignments and all scored checkpoints are preserved; the stop also
  recorded one simulator connection failure, 30 interrupted and 207 pending tasks.
  The runtime-only repair passed 735 regressions plus a real Luna child check:
  project NumPy 2.2.6, OpenBLAS one thread, Agg PNG and finite residual below 1e-12.
  NumPy and sandbox font/cache warnings are retained, not suppressed. Scientific
  protocol and rubric/audit hashes are unchanged, but process environments differ
  across source epochs and this intervention must be disclosed in final reporting.
  Current log: `runs/logs/results20-v6d-attempt02-revise-c30-20260905-1400.log`;
  current archive: `runs/provenance/20260905-redteam-v6d/attempt-02/source.tar.gz`.
  Original code, interruption archive and logs remain separate. The existing v6c
  acceptance audit is complete at 153/153; formal audit has not started. Re-estimate
  the initial 1.5–3-hour revision ETA from resumed throughput; no overall cutoff.

## Earlier checkpoints — historical, not current process status

- **13:18 CST audit recovery:** concurrency-6 invocation exited 1 with 148/153
  successful judgments, leaving two final-artifact and three pairwise Gemini
  failures. Its complete output is archived as `acceptance-audit-after-c6-20260905-1318.tar.gz`
  in v6b provenance. Serial audit-only resume is now session 32614, log
  `runs/logs/biomni-redteam-acceptance-v6b-audit-resume-c1-20260905-1318.log`;
  completed scores are preserved. Full launch remains gated on all 153 judgments
  and exact saved-score/provider/assignment validation.
- **13:16 CST audit recovery:** Gemini TLS and a minimal structured request passed
  (3.34s) without changing source, keys or proxy settings. Audit-only resume is
  now active at concurrency 6, session 26369, log
  `runs/logs/biomni-redteam-acceptance-v6b-audit-resume-c6-20260905-1316.log`.
  Verify complete coverage and retained successful judgments; do not rerun the
  four revisions. Formal Results20 remains gated. Recovery ETA: 5–10 minutes
  if connectivity remains available; no overall cutoff.
- **13:12 CST network gate:** session 28533 is terminal (exit 1), not running.
  All four v6b revisions passed, but only 119/153 audit judgments succeeded; all
  34 failures are Gemini (14 direct, 11 rubric-score, 5 absolute, 4 pairwise).
  Single-request and independent-client probes also fail at Gemini TLS, while
  other tested HTTPS hosts connect. No new code/protocol change is justified by
  these transport failures. First-attempt audit evidence is archived in v6b provenance.
  Once Gemini connects reliably, use `detect --experiment
  experiments/preflights/biomnibench-elicitation-10.yaml --resume --max-concurrency 6`
  to recover missing judgments while validating/reusing successes, then run the
  strict coverage check. Do not restart completed revisions or launch full Results20
  before the gate passes. The audit ETA now depends on connection recovery.
- **13:07 CST milestone:** v6b acceptance revisions completed 4/4 in 14m37s
  after shared preparation; five online generations and five included sidecars,
  zero retries/fallbacks, one admitted criterion. The same session 28533 is now
  executing all seven audit stages with Sol/Claude Opus 5/Gemini 3.8; ETA 5–10
  minutes. Check exact per-model/per-assignment coverage before full launch.
- **12:51 CST acceptance:** the complete exact-byte fix includes shared-rubric
  installation; 724 tests pass (two known environment exclusions). Initial v6
  preparation was stopped before assignments; corrected acceptance is running
  in `exact-newlines-v6b`, session 28533, log
  `runs/logs/biomni-redteam-acceptance-v6b-20260905-1251.log`, concurrency 30.
  The small matrix has only four assignments, so at most four revision workers.
  ETA including audits is 15–25 minutes. Formal v6b is not started; outputs will
  be under `runs/studies/20260905-redteam-v6b` and matching detection/report paths.
- **12:48 CST repair:** v5 is STOPPED (session 29868 exited 143 at 12:44),
  not actively running despite stale ledger statuses. Six generation-storage
  failures plus one unsafe solver snapshot led to a controlled stop at 68 completed,
  7 failed, 30 interrupted and 135 pending; no formal audits have started.
  Exact-newline storage/reload repair passes 61 focused tests. Complete regression
  and fresh four-condition acceptance under v6 before scaling; preserve v5 as
  diagnostic evidence and never mix its completions into a changed implementation.
  Previous remaining-time estimates are superseded by this repair gate.
- **12:39 CST monitoring:** 61 completed, 30 running, 136 not yet started,
  nine interrupted records queued for current-invocation recovery, plus four
  recorded failures (one earlier simulator connection failure still queued,
  two newly staged rubric text-integrity failures, one solver snapshot symlink
  rejection). Run the supported `revise --resume` again after the current invocation
  seals to retry any remaining failures before launching audits. Preserve failed-turn
  evidence first; do not manually edit manifests, accept invalid snapshots, or erase
  historical proposer fallbacks. Current remaining revision/retry/audit ETA is
  approximately 1.5–2.5 hours from 12:35 CST, subject to task-length variability.
- **12:27 CST recovery:** revision session `29868`, controller PID `77506`,
  `runs/logs/results20-v5-revise-c30-20260905-1227.log`, explicit concurrency 30
  and `--resume`. Source/config and scientific protocol remain unchanged.
  The original 60-concurrency session exited 143 after an intentional resource
  stop at 12:24 CST; the brief 20-concurrency recovery (`47957`, PID `77137`)
  was replaced by 30 at the user's request. Forty-one completed assignments are
  preserved; interrupted records are reclaimed and queued by the current workflow.
  Do not mistake `InterruptedStudyInvocation` markers for new API failures.
  Audit has not started; revise ETA after observing sustained concurrency-30 throughput.
- At 12:22 CST, SSL unexpected-EOF errors caused six assignment failures and
  connection-error fallbacks in eleven online generations. Those fallbacks remain
  in the evidence and must be disclosed in final treatment-coverage reporting;
  resume does not erase them. Original study status was copied before recovery to
  `runs/provenance/20260905-redteam-v5/study-after-resource-stop-20260905-1224.json`.
  CPU was 100% busy and the 24-GiB laptop used ~10 GiB compressed memory plus
  ~5 GiB swap. After stopping, CPU became ~61% idle and a minimal Luna request
  succeeded in 2.07 seconds; causation between overload and SSL failure is unproven.
- Full Results20 v5 preparation completed; formal revision launched at concurrency 60, no overall deadline.
  Seed session `92718`, PID `50032`, log `runs/logs/results20-v5-seed-20260905-1152.log`;
  paraphrase session `78817`, PID `50099`, log
  `runs/logs/results20-v5-paraphrase-20260905-1152.log`. The two independent stages
  started together around 11:52 CST. Initial estimates: preparation 10–20 minutes,
  full workflow 2–3 hours, to be revised using actual throughput and resource pressure.
  Paraphrases are complete: 100/100, exit 0, 2m09s. Seeds completed 60/60, exit 0,
  10m15s at 12:02 CST. Revision session `46711`, controller PID `58211`, log
  `runs/logs/results20-v5-revise-20260905-1202.log` started at 12:02 CST;
  shared preparation completed by 12:04 CST: 20 generations, no stage fallbacks,
  four admitted criteria across three tasks. First 60 assignments are running,
  180 pending. Remaining revision/audit
  ETA is approximately 1.5–3 hours, to be calibrated after the first assignments.
- Initial process check confirmed 60 seed Codex workers with approximately 8.8 GiB
  aggregate owned-process RSS; system memory pressure was normal. Monitor especially
  when red-team sidecars overlap persistent solver sessions during revision.
- V4 completed four revisions, six valid sidecars, and all seven audit outputs
  (162/162 judgments, no missing provider). One of six online generations had a
  redundant score/preference mismatch despite corrective retries.
- V5 removes only rubric-view preference from the model response and derives the
  same higher-total/tie rule in code from validated scores and penalties, floored
  at zero. Rubric-free quality preference remains model-judged. Two real-history
  proposer generation/reload regressions completed with five calls each, zero
  retries/fallbacks (80.7s and 68.4s); full regression passed 720 tests with the two
  known environment exclusions. This complete v4 workflow plus targeted current
  component verification supplies the readiness gate; no complete v5 small rerun
  is claimed. Historical artifacts were not rewritten for the changed contract.
- Next: monitor the active `revise --max-concurrency 60` on the full YAML,
  including shared pretreatment and the first assignments. Launch `detect` after
  revision seals; its concurrency can be tuned from observed resource/rate limits.
  Keep all four conditions, three replicates, and full min-5/max-10 horizon.
- Freeze source while v5 runs. Rubric implementation SHA-256:
  `657f8c1cba0ed958cd5a1e5905d90dc450e209be451a59dbf2bbb0f17ad35520`.
  Source/config snapshot and actual invocation ledger:
  `runs/provenance/20260905-redteam-v5/README.md`.
- Full study: `runs/studies/20260905-redteam-v5/biomnibench-da-factorial-r10-8ab12c898ae7`.
  Audit: `runs/detections/20260905-redteam-v5/biomnibench-da-factorial-r10-8ab12c898ae7`.
  Revision has launched; audit has not. Use `EXPERIMENT_RUNS.md` to distinguish
  preparation from completed experimental results; version namespaces and
  implementation hashes remain necessary even when configuration IDs match.

## Execution history (superseded attempts; not current instructions)

- Checkpoint preserved at `origin/aydan-checkpoint-1` (`1c2d686`).
- Reviewed collaborator main: `c45e591`; remote rechecked and unchanged.
- Local runtime fixes and concurrency defaults are present but uncommitted.
- Results20 data download completed at pinned Hugging Face revision
  `e1c8ca5e11a620087bc48d97888eb69176a1f235` (410 files, 0.452 GiB).
  Approximately 44 GiB disk was free at initial inspection.
- Acceptance seed preparation relaunched 2026-09-05 10:34 CST with `caffeinate -i`, existing
  credentials, and `rubric-gen run --experiment
  experiments/preflights/biomnibench-elicitation-10.yaml --max-concurrency 60`.
  Tool session: `48639`; log: `runs/logs/biomni-redteam-acceptance-20260905-1034.log`.
  Experiment ID: `biomnibench-da-factorial-r10-2a14ebaeab38`; revision output:
  `runs/preflights/biomnibench-da-factorial-r10-2a14ebaeab38`; audits:
  `runs/preflight-detections/biomnibench-da-factorial-r10-2a14ebaeab38`.
  All three seed blocks completed in approximately eight minutes. After the
  user's duration requirement, a graceful interrupt stopped at this barrier
  without discarding completed seeds. Full-run launch remains gated on the
  shorter acceptance check.
- The initial 10:31 invocation (session `1534`, same log stem with `1031`) was
  stopped before seeds completed after a synthetic whole-rubric request found
  Claude Opus 5 rejects `temperature`. The adapter and provenance contract are
  fixed; all three whole-rubric provider paths now pass real synthetic calls.
  Post-fix suite: 702 passed, two unrelated Harvey/MALT environment tests
  explicitly excluded. No historical completed artifact metadata was changed.
- Tracked source/test/dependency/config diff SHA-256 at relaunch:
  `c78391e7c6799c0e425bcc78677ba5e89ac1089194706346a77ddb59fafde085`
  (`git diff -- src tests pyproject.toml uv.lock experiments | shasum -a 256`).
  Hashed workflow sources remain frozen while this invocation is active;
  documentation corrections do not alter its protocol implementation.
- A one-second dummy deadline test killed both the launched process and its
  detached child (exit 124); verified neither remained alive. Five paraphrases
  completed in 16.9 seconds under a 300-second limit, session `87803`, log
  `runs/logs/biomni-redteam-paraphrase-20260905-1043.log`.
- Short acceptance launched 10:44 CST, session `61543`, controller PID `44636`,
  with `bounded_run.py 600 caffeinate -i ... run --max-concurrency 60` and log
  `runs/logs/biomni-redteam-short-20260905-1045.log`. Its ID is
  `biomnibench-da-factorial-r3-3e086256742d`; output roots use this ID under
  `runs/preflights/` and `runs/preflight-detections/`. All three seeds and the
  paraphrase pool passed current validation and were reused without regeneration.
  Tracked source/test/dependency/config diff SHA-256:
  `1be0b7e3dc614badcf83e7897e1aa2fa2cb8a9ef3efcb5c811babd8260cd74cd`.
- That attempt stopped after 158 seconds because both simulator arms returned
  duplicate categories at `s000`. The prompt now states category uniqueness and
  validation retries receive specific repair guidance, preserving the existing
  projection contract. Actual checkpoint replay passed on the second attempt;
  regression suite: 703 passed, two unrelated environment tests excluded.
- Second corrected acceptance: started 10:50:40 CST; deadline 11:00:40 CST;
  session `8857`, controller PID `45140`; log
  `runs/logs/biomni-redteam-short-v2-20260905-1050.log`. Study/audit output roots
  are now `runs/preflights/simulator-contract-v2/` and
  `runs/preflight-detections/simulator-contract-v2/`, using the same r3 ID.
  Old failed artifacts remain untouched. Tracked diff SHA-256:
  `8e48e8e197e3b920b2cbcddc3c28c9a1ff337f8c5cbcf3d0c4682e20d4fd5d61`.
- That attempt was stopped after 135 seconds: uniqueness prompting still failed
  in one simulator arm. It is superseded by a contract correction allowing
  distinct concerns in the same category (labels are internal metadata, not
  unique IDs). Both validators now agree with the structured schema; concern
  count/content bounds and repair retries remain. Seven captured real responses
  pass diagnostic replay, but old run artifacts are not relabeled as successful.
  Next clean acceptance uses `simulator-contract-v3` output roots and new ID
  `biomnibench-da-factorial-r3-98e520cfd5eb`.
- Active acceptance: started 10:54:03 CST; deadline 11:04:03 CST; session
  `79592`, controller PID `45559`; log
  `runs/logs/biomni-redteam-short-v3-20260905-1054.log`. All seed blocks and
  paraphrases passed current validation and were reused. Tracked diff SHA-256:
  `671c4b0d8d59f314beab9cb813d63f0caf141ea63019096a6c995c696eecb73a`.
- During that invocation, the user switched the Gemini audit panel to 3.8 and
  requested milestone ETAs. All three Gemini 3.8 API paths (whole-rubric,
  structured generation, direct SDK token count) pass. A graceful controller
  interrupt will stop after active revisions finish, before any 3.6 audit.
  Finalize the old study under its unchanged YAML first, then update the active
  YAML and use the supported `detect --study-dir` path: evaluation tracks the
  original study ID and the new audit ID separately, without editing artifacts.
  That invocation was interrupted at 11:04:04 by the earlier cutoff. The user
  subsequently clarified that only an ETA was wanted; recovery at 11:07 uses
  no overall deadline, as specified in the current operating rules above.
