# Experiment runs and versions

Start here to find results. Approved scope/current state are in [EXPERIMENT_PLAN.md](EXPERIMENT_PLAN.md),
and reusable operations in [rubric-experiments](skills/rubric-experiments/SKILL.md);
dated decisions/results in [EXPERIMENT_LOG.md](EXPERIMENT_LOG.md), and implementation
concerns in [CODE_REVIEW.md](CODE_REVIEW.md). All times below are Asia/Shanghai (CST).

## Current work

Version: **20260905-redteam-v7**. Base commit `c45e591` plus archived local fixes;
the Git commit alone does not reproduce this version. Solver/proposer/red-team/weak
judge: Luna. Outcome panel: Sol, Claude Opus 5, **Gemini 3.8 Flash**.

**Completed — September 6, 02:22 CST:** all 240 assignments and all seven audit
stages passed the strict gate (9,327 unique judgments, three-model coverage).
Final semantic session 31197 exited 0 at 02:20:10, with one new Claude score and
all prior records preserved. No invocation is live.

Start with [final report](runs/reports/20260905-redteam-v7/REPORT.md),
[analysis JSON](runs/reports/20260905-redteam-v7/outcomes.json), and
[complete coverage](runs/reports/20260905-redteam-v7/audit-coverage-complete.json).
Completed semantic archive:
`runs/provenance/20260905-redteam-v7/audit-v2/semantic-complete-20260906-0220.tar.gz`.

**Previous invocation — September 6, 02:19 CST:** delayed semantic c1 recovery,
session **31197/controller 83729**, launched 02:18; rubric resume logged 02:19:11
with 4,827 cached scores. Log `runs/logs/results20-v7-semantic-recovery4-c1-20260906-0218.log`.
Unchanged helper, expected 3–8 minutes; stop unchanged retries if the same Claude
disconnect recurs. All four direct windows remain completed.

**Previous checkpoint — September 6, 02:17 CST:** no invocation remained live.
Session 70066 exited 0 at 02:17:08, preserving all 720 prior scores; full-trajectory
independent raw/summary/assignment/model checks passed at 02:17:26 with zero failures.
All four direct windows are complete. Receipt:
`runs/reports/20260905-redteam-v7/full-trajectory-completion-verification.json`.
Archive: `runs/provenance/20260905-redteam-v7/audit-v2/full-window-complete-20260906-0217.tar.gz`.
Still unresolved: one Claude absolute score, both quality summaries, full gate/report.

**Previous invocation — September 6, 02:08 CST:** cached full-window reconciliation,
session **70066/controller 82498**, c2, started **02:08:32** with 720 existing scores.
Unchanged helper; log `runs/logs/results20-v7-full-window-cache-reconcile-c2-20260906-0208.log`.
ETA 8–12 minutes for preparation/validation; terminal raw/summary verification is
still required. Claude absolute retries remain paused.

**Previous checkpoint — September 6, 02:07 CST:** no experiment invocation was live.
Session 61718 exited 1 at 02:07:20 after recovering all four Gemini scores,
preserving 716 previous records; full trajectory has 720 completed raw scores.
Its summary still fails one cached Claude case (revision-000084) during request
preparation with APIConnectionError, so full-panel acceptance remains incomplete.
Archive: `runs/provenance/20260905-redteam-v7/audit-v2/full-window-c2-terminal2-20260906-0207.tar.gz`.
One Claude absolute score and both quality summaries also remain unresolved.

**Previous invocation — September 6, 01:58 CST:** session **61718/controller 80898**,
full-window recovery at **c2**, launched **01:57:51** with 716 preserved scores.
Log: `runs/logs/results20-v7-full-window-recovery2-c2-20260906-0158.log`.
Same validated helper and frozen runtime; the provider-requested TPM cooldown
elapsed before this attempt. ETA 9–15 minutes for this pass only; Claude remains paused.

**Previous checkpoint — September 6, 01:56 CST:** no experiment process remained live.
Full-trajectory c2 recovery exited 1 at 01:56:11, preserving 710 prior scores and
adding six (716/720). Four Gemini judgments failed with HTTP 429 input TPM limits
of 3,000,000, with requested cooldowns of 49–55 seconds; prior cached preparation
failures no longer appear. Terminal panel/log archive:
`runs/provenance/20260905-redteam-v7/audit-v2/full-window-c2-terminal-20260906-0156.tar.gz`.
Claude absolute still lacks one score and both quality summaries remain absent.

**Previous invocation — September 6, 01:48 CST:** full-trajectory-only recovery,
session **11630/controller 79314**, concurrency **2**, launched **01:46:49 CST**.
Entrypoint: `runs/diagnostics/resume_full_trajectory.py`; log:
`runs/logs/results20-v7-full-window-recovery-c2-20260906-0147.log`.
It preserves 710 previous scores and uses the unchanged current direct API to
recover ten missing Gemini judgments and refresh four cached preparation failures.
Cached small validation preserved 12 records and full acceptance remains 153/153;
entrypoint/log archive is `runs/provenance/20260905-redteam-v7/audit-v2/full-window-c2-entrypoint-20260906-0147.tar.gz`.
Allow about 10–20 minutes from launch, conditional on provider response.

The earlier direct suite ended at 01:39:55 (session 16124, exit 1 from full
trajectory only); post-update, final-artifact and final-revision are independently
verified 720/720 each with no failures. Latest receipt:
`runs/reports/20260905-redteam-v7/final-windows-completion-verification.json`.
Latest terminal archive:
`runs/provenance/20260905-redteam-v7/audit-v2/direct-recovery-01-final-windows-complete-20260906-0146.tar.gz`.
Semantic session 48415 ended at 01:35:02 with one recovered score and one remaining
Claude absolute failure; 899 absolute + 720 pairwise raw records survive, without
quality summaries. Archive:
`runs/provenance/20260905-redteam-v7/audit-v2/semantic-recovery-03-quality-terminal-20260906-0136.tar.gz`.
Immediate Claude retries are paused pending diagnosis/user network/API information.
The remaining key `2ee448dfd3eac7a466f639a9f2e90ee2` is the final `s010` submission
for `da-15-2/rep-003/luna/user-simulator-red-team-artifact`, affecting one assignment's
Claude absolute-quality score; do not exclude it or substitute a surviving model.

### Historical invocation checkpoints

**September 6, 01:31 CST:** main session 40033/controller
46331 is terminal, exit 1, after processing all quality jobs; its first reported
fatal error is Anthropic APIConnectionError. Quality raw coverage is 863/900
absolute and 707/720 pairwise, with no terminal summaries; 50 missing records
are Claude 48/Sol 2, not all independently classified by the one exception chain.
Archive: `runs/provenance/20260905-redteam-v7/audit-v2/formal-attempt-02-quality-terminal-20260906-0112.tar.gz`.

First semantic-only recovery: session **87050**, controller **74221**,
started **01:13:13 CST**, concurrency **3**, via the validated unchanged private
`runs/diagnostics/resume_semantic_panels.py`. Log:
`runs/logs/results20-v7-semantic-recovery-c3-20260906-0113.log`.
It began with 89 missing judgments (39 rubric + 50 quality). At 01:18:48 rubric
recovery completed 4,827/4,827 with zero failures and all 4,788 prior records
byte-identical; independent stage-only checks passed all raw/plan/summary identities
and all 240 assignments at 01:19:26. Verification:
`runs/reports/20260905-redteam-v7/rubric-score-completion-verification.json`.
Completed-stage archive: `runs/provenance/20260905-redteam-v7/audit-v2/semantic-recovery-01-rubric-complete-20260906-0119.tar.gz`.
It ended at 01:24:10 with exit 1 after an Anthropic connection error, preserving
all 1,570 prior quality scores and adding 48; two Claude absolute scores remain
missing, so absolute has 898 raw records, pairwise 720, and both summaries are absent.
Terminal archive: `runs/provenance/20260905-redteam-v7/audit-v2/semantic-recovery-01-quality-terminal-20260906-0125.tar.gz`.
Second semantic recovery, session **91043/controller 76474**, c3,
launched **01:26:03 CST** after the previous controller was confirmed gone.
Log: `runs/logs/results20-v7-semantic-recovery2-c3-20260906-0126.log`.
ended at 01:28:38 with zero new records and a server-disconnect/Anthropic connection
exception; all 4,827 rubric and 1,618 quality records stayed unchanged. Archive:
`runs/provenance/20260905-redteam-v7/audit-v2/semantic-recovery-02-quality-terminal-20260906-0129.tar.gz`.
Third semantic recovery is **running serially**, session **48415/controller 77227**,
c1, launched **01:31:17 CST**. Only the idle private helper's concurrency constant
changed; cached small verification preserved 105 scores and full acceptance remains
153/153. Helper/log archive: `runs/provenance/20260905-redteam-v7/audit-v2/semantic-recovery-c1-entrypoint-20260906-0132.tar.gz`.
Formal log: `runs/logs/results20-v7-semantic-recovery3-c1-20260906-0131.log`.
If these same two failures recur, pause further immediate retries for diagnosis.
Direct session **16124/controller 62758**, c1, completed post-update at 01:32:15:
720/720, zero failures, 617 original records unchanged and 103 recovered.
Independent stage checks passed at 01:33:21; receipt:
`runs/reports/20260905-redteam-v7/post-update-completion-verification.json`.
Archive: `runs/provenance/20260905-redteam-v7/audit-v2/direct-recovery-01-post-update-complete-20260906-0133.tar.gz`.
The same direct process now runs final-artifact recovery, then final revision.
Current aggregate concurrency is **1 + 1**.
Whole-audit completion remains unproven; keep current model coverage intact.

**Latest audit checkpoint — September 6, 00:49 CST:** rubric scoring ended at
00:47:32 with 4,788/4,827 successes and 39 failures: Sol 4 transport, Claude 13
transport, Gemini 2 transport-only and 20 with unsupported-location attempts
(four of those also had transport attempts). Full stage archive:
`runs/provenance/20260905-redteam-v7/audit-v2/formal-attempt-02-rubric-score-20260906-0048.tar.gz`.
Session 40033 continues at c12 in absolute/pairwise quality scoring; at 01:02:58
there are 863/900 absolute and 54/720 pairwise records, with every model represented.
Both summaries remain unpublished; the processed/saved gap must be reconciled
at termination, not treated as fully successful absolute coverage. From 01:03,
allow about 10–25 more minutes for this pass, excluding direct/failure recovery.
Direct session 16124 remains c1 and entered post-update preparation at 01:03:51.
Its full-trajectory pass preserved all 594 prior scores and added 116: 710/720 raw
successes (Sol/Claude each 240, Gemini 230). The new summary has 14 failures: nine
Gemini region errors, one Gemini transport error, plus four preparation failures
with intact cached scores, so raw and summary success counts differ by four.
Archive: `runs/provenance/20260905-redteam-v7/audit-v2/direct-recovery-01-full-trajectory-20260906-0104.tar.gz`.
Other direct terminal counts below remain prior-attempt history until recovery ends.

**Revision is complete: 240/240.** Attempt 3 ran from **20:10:51 to 21:41:16 CST**,
session **73847**, controller **89959**, concurrency cap **30**, and exited 0
with no new invocation failures. Its controller is gone. This recovery took about
90 minutes; total v7 revision wall time from the original 14:40 launch was about
seven hours, including earlier failures and the interrupted monitoring interval.
Attempt 2 actually ended at 16:39:07 with 126 complete and 114 failed after
connection failures; it did not keep running through the interrupted monitoring
period. Its full terminal archive is preserved and the old 18:00–19:00 ETA is invalid.

The hidden startup `.pth` flags recurred and clearing them was not durable. Current
workflow launches explicitly set `PYTHONPATH=/Users/yuenanhuang/Desktop/rubric_gen/src`,
validated with a minimal proposer request and a real solver command; source and
protocol are unchanged. Both first-turn/no-session failed directories were moved
intact to provenance quarantine, and both replacements completed through normal
fresh workflow. No completed artifact was regenerated or metadata faked.

All 126 prior completed assignments passed independent current-format validation
in 83.65 seconds; all 33,455 files match the pre-resume terminal archive exactly,
and all 195 frozen source files matched at the revision/audit boundary. The full independent check passed
all 237 completed assignments captured at startup in 175.11s, including both fresh
first-turn replacements; see `runs/reports/20260905-redteam-v7/revision-validation-before-audit-237.json`.
The final three assignments also passed supplemental validation (4.23s including
source verification), completing independent coverage of all 240;
see `revision-validation-terminal-240.json` in the same report directory.
All 20 shared rubrics remain complete.
The [treatment-delivery report](runs/reports/20260905-redteam-v7/treatment-delivery.md)
now records exact per-condition solver turns, online rubric changes, retries,
fallbacks and red-team exclusions for all 240 assignments. Simulator arms averaged
more turns than full arms; final RH comparisons must retain this adaptive-exposure
context, not imply equal-turn comparisons.
At recovery launch there were 653 online generations and 56 admitted criteria.
At 21:06 there are five response-validation fallback generations across four
assignments, all in simulator/artifact; these retained the prior rubric. The latest
pair-ID validation fallbacks are generation 7 of da-12-2/rep-002 and generation 9 of
da-19-1/rep-003: both stored generations validate and accept no new candidate.
Six sealed red-team sidecars have provider exit 1 and
`included=false`; the current protocol preserves these exclusions, which must
remain distinct from successful red-team evidence and rubric fallbacks.
**Fresh audit acceptance passed 153/153** after serial recovery under the repaired
audit identity; all 149 prior successful records remained byte-identical.
Verification: `runs/reports/20260905-redteam-v7/audit-v2-acceptance-verification.json`.
**Formal audit is running**, recovery session **40033**, controller **46331**,
concurrency **12**, launched about **22:12:40 CST**. Results:
`runs/detections/20260905-redteam-v7-audit-v2/biomnibench-da-factorial-r10-8ab12c898ae7`.
Log: `runs/logs/results20-v7-audit-v2-resume-c12-20260905-2212.log`.
From **September 6, 00:00:12**, direct-only recovery also runs at concurrency **1**,
session **16124**, controller **62758**, while the c12 process remains in separate
rubric/quality directories (13 aggregate workers). It calls existing production
stage APIs through `runs/diagnostics/resume_direct_panels.py`, after cached small
recovery preserved all 48 direct scores and complete acceptance passed 153/153.
Log: `runs/logs/results20-v7-direct-recovery-c1-20260906-0000.log`.
Entrypoint/small-log archive: `runs/provenance/20260905-redteam-v7/audit-v2/direct-recovery-entrypoint-20260906-0000.tar.gz`.
At September 6 00:28, both invocations are verified live: rubric scoring has
3,894/4,827 saved records and direct full-trajectory recovery has 608/720 raw
successes. Comparison against the prior archive confirms all 594 earlier scores
remain byte-identical; 14 earlier failures now have scores (13 Gemini, one Claude).
The recovery panel has not yet published its terminal summary; 716 jobs were
scheduled after preparation, so preparation failures still need reconciliation.
A semantic-only recovery entrypoint is prepared but **not launched formally**:
`runs/diagnostics/resume_semantic_panels.py` (c3, existing production APIs).
Small cached validation at 00:30 exited 0, preserving 105 semantic records; the
complete acceptance gate remains 153/153. It may run only after the current
semantic writer terminates and terminal evidence is archived; see the provenance
README and `semantic-recovery-entrypoint-20260906-0031.tar.gz`.
The following direct-stage failure counts describe the preserved prior attempt,
not fresh recovery failures; wait for the new per-panel terminal summaries.
The first concurrency-30 attempt was interrupted after a large processed/saved
gap and archived with 238 successful scores; all 238 remain byte-identical during
recovery. At 22:35 the full-trajectory stage has 594/720 saved successful scores,
but its summary recognizes only 593 due to one failed preparation before cache
lookup. The 127 summary failures comprise 84 Gemini input-TPM rate limits, 35
transport failures and eight Gemini unsupported-location responses; the complete
stage is archived. Post-update ended at approximately 22:52 with 617/720 successes
and 103 failures: Gemini 54 TPM-limit/13 transport/seven unsupported-location,
Claude 13 transport/seven insufficient-credit, and Sol nine transport errors.
Its stage archive is preserved. Final-artifact detection ended by 22:58 with
719/720 successes: Sol and Claude each 240/240, Gemini 239/240, and one Gemini
unsupported-location failure. Thus Claude billing errors are historical failed
calls, not evidence of universally blocked current access; user billing verification
is still requested. Final-revision detection ended with 715/720 successes and
five failures (three transport, two Gemini unsupported-location). All four direct
passes are archived: 2,645 raw successes out of 2,880, with 236 failed summary
records because one failure still has an intact cached score.
**Rubric scoring is now running**, started about 23:03:45: its manifest confirms
4,827 unique jobs, and 2,471 scores were saved by 23:55:23 across all three models
(Sol 829, Claude 814, Gemini 828). Session 40033 is still live; 221 of 237 jobs
with recorded failed attempts subsequently saved successfully, while the remaining
16 include in-flight work and jobs with three failed attempts, not a published
terminal-stage failure count. Recent throughput is roughly 40–55 saved jobs/minute;
allow about 40–70 more minutes
for this stage, including its tail but not a guarantee of complete recovery. Absolute
and pairwise quality scoring and direct-stage recovery remain additional.
Full coverage still requires recovery and the independent final gate.
Both earlier 30–60-minute and 1–2-hour audit ETAs are superseded. Exact read-only
planning found 9,327 judgments total, including 4,827 rubric, 900 absolute and
720 pairwise judgments; see `runs/reports/20260905-redteam-v7/audit-planned-counts.json`.
At 22:40, provisional remaining time is 2–4 hours, using small-run timings and
allowing for recovery; recalibrate from actual formal rubric-stage throughput.
No hard cutoff. At 23:24, 197/198 archived files still match: the only difference
is the user-requested maintenance `AGENTS.md` cleanup, recorded separately in the
provenance README. All frozen runtime/config and analysis files remain unchanged.
Revision log: `runs/logs/results20-v7-revise-resume3-c30-20260905-2011.log`.
Full terminal revision archive and the frozen 198-file audit/source-analysis
archive are indexed in [audit provenance](runs/provenance/20260905-redteam-v7/audit-v2/README.md).

Fresh v7 acceptance passed: 4/4 revisions in 12m20s including preparation, six
online generations/six included sidecars/one admitted criterion, no proposer
retry/fallback or assignment failure. All **153/153** three-model audit judgments
are verified after serial recovery of one Gemini IncompleteRead failure. The first
attempt is archived; all 152 previously successful score/record files are unchanged.
That original CLI could exit 0 with a failed direct judgment; this is repaired,
but always require the independent coverage gate, not the exit code alone.
See the historical [acceptance report](runs/reports/20260905-redteam-v7/acceptance.md).
The boundary repair passed 110 focused and 744 full tests with two pre-existing
environment exclusions; generation identity is unchanged. Fresh small-audit
verification passed under its new audit identity before formal audit launch.
Provider-call exhaustion now raises a workflow failure without publishing a rubric
generation and counts toward the study circuit. Response-validation fallback rules
are unchanged. Regression: 742 passed, two known environment exclusions. New
generation identity requires fresh artifacts; the acceptance cannot reuse v6b
generations or v6c audit results. Network reliability is not guaranteed by this
successful acceptance; monitor the formal run and preserve any failures.

Formal v6d is **stopped**, not running. Attempt 2's actual
Python controller **951** and all live descendants were stopped at **14:07:04**;
session **90781** exited 143. Its terminal counts are **18 completed, 30 interrupted,
192 pending**, but **16 of the 18 completed assignments contain connection-induced
rubric fallback**. In total, 21 assignments/21 generations contain 34 fallback stages.
Do not present these as 18 clean formal results or silently rewrite their history.
See the [network incident report](runs/reports/20260905-redteam-v6d/network-incident.md).

The runtime repair itself passed 735 regressions and a real project-Python,
single-threaded OpenBLAS/Agg test; post-resume CPU idle was about 53% and compressed
memory fell to about 4.2 GiB. Network availability is intermittent: a minimal actual
proposer call succeeded after the stop, but bulk failures were already sealed.
V7 tests cover exhausted calls, retry recovery, publication prevention and circuit
gating. Preserve v6d as incident evidence, not relabeled clean outcomes; this code
repair does not establish that intermittent network failures themselves are fixed.

The earlier v6c acceptance audit completed 153/153 judgments across all three models,
but it is not the formal 240-assignment outcome audit now running under v7 audit-v2.
The old v6d full-run ETA is superseded by the v7 estimate above. Concurrency
40 remains a candidate only after sustained resource checks; ETAs are not deadlines.
The earlier v5 study is stopped and will not be resumed under current code.

This section reflects only current work; dated history is retained in
`EXPERIMENT_LOG.md` and each version's provenance ledger.

| Run | Purpose | Current state | Data / log |
|---|---|---|---|
| `results20-v7` | Approved full experiment | Revisions complete and independently validated, 240/240; fresh audit acceptance running, formal audit pending | [Provenance](runs/provenance/20260905-redteam-v7/audit-v2/README.md) |
| `acceptance-v7` | Fresh four-condition check of provider-failure propagation | Complete: 4/4 revisions, 153/153 audit judgments after one-request recovery | [Report](runs/reports/20260905-redteam-v7/acceptance.md) |
| `results20-v6d` | Approved 240-assignment study, now incident evidence | Stopped; 18 complete (16 affected by fallback), 30 interrupted, 192 pending; formal audit not started | [Incident report](runs/reports/20260905-redteam-v6d/network-incident.md) · [Source epoch](runs/provenance/20260905-redteam-v6d/attempt-02/README.md) |
| `audit-v6c` | Validate Gemini transport retries and complete the acceptance panel | Complete after serial recovery, 153/153 judgments | [Report](runs/reports/20260905-redteam-v6c/acceptance.md) · [Provenance](runs/provenance/20260905-redteam-v6c/README.md) |
| `acceptance-v6b` | Verify byte-exact storage/replay/shared installation in the full workflow | Revisions 4/4 complete; old audit incomplete, superseded by separate v6c audit | [First-attempt report](runs/reports/20260905-redteam-v6b/acceptance.md) · [Provenance](runs/provenance/20260905-redteam-v6b/README.md) |
| `results20-v5` | Full approved 240-assignment experiment | Stopped for storage repair; 68 completed, 7 failed, 30 interrupted, 135 pending; no audit | [Source and execution ledger](runs/provenance/20260905-redteam-v5/README.md) · [Last revision log](runs/logs/results20-v5-revise-c30-20260905-1227.log) · [Cost estimate](runs/reports/20260905-redteam-v5/cost-estimate.md) |
| `component-v5` | Two real-history proposer generation/reload checks | Passed; 5 calls each, no retry/fallback | [Summary](runs/diagnostics/score-derived-v5/summary.json) |
| `acceptance-v4` | Four-condition development check with repaired assessment validation | Completed; 4/4 revisions, 162/162 audit judgments; one redundant-preference fallback repaired in v5 | [Report](runs/reports/20260905-redteam-v4/acceptance.md) · [Study](runs/preflights/assessment-contract-v4/biomnibench-da-factorial-r3-b07888ff76df/) · [Source snapshot](runs/provenance/20260905-redteam-v4/README.md) |
| `acceptance-v3` | Pre-fix diagnostic, 1 task, 4 conditions, 3 turns | 4/4 revisions and 153/153 audit judgments completed; proposer fallbacks prevented readiness | [Report](runs/reports/20260905-redteam-v3/acceptance.md) · [Study](runs/preflights/simulator-contract-v3/biomnibench-da-factorial-r3-98e520cfd5eb/) · [Audit log](runs/logs/biomni-redteam-acceptance-v3-audit-gemini38-20260905-1118.log) · [Source snapshot](runs/provenance/20260905-redteam-v3/README.md) |

The persisted `study.json` can say `running` after process death; consult the
latest invocation status, not a stale ledger alone. Acceptance runs are development
diagnostics, not Results20 outcomes. The v3 study originally named Gemini 3.6,
but no 3.6 audit was launched; its separate completed audit used Gemini 3.8.

## Storage convention for new versions

Keep each code/protocol version in its own namespace, with separate stage outputs:

```text
runs/
  provenance/<version>/              source/config snapshot + hashes
  studies/<version>/<experiment_id>/ raw revision study
  detections/<version>/<audit_id>/   raw independent audit stages
  reports/<version>/                 readable summaries and analysis tables
  logs/                             one append-only log per invocation
```

The focused Results20 YAML now targets
`runs/studies/20260905-redteam-v7/{experiment_id}` and
`runs/detections/20260905-redteam-v7-audit-v2/{experiment_id}`.
Its current configured ID is `biomnibench-da-factorial-r10-8ab12c898ae7`;
recompute it if semantic configuration changes. The existing acceptance attempts
remain under `runs/preflights/`; do not relocate them because artifacts contain
path-bound provenance.

The experiment ID does not include every rubric implementation change: versions
can share configuration IDs but differ in their implementation hashes and version
namespaces. Never use the short experiment ID alone as the code-version key.

Before each full run, freeze the Git base, dirty source/config hashes, exact YAML,
dataset revision, model roles, and command in `provenance/<version>/`. Preserve
an allowlisted source archive without `.env`, credentials, runtime caches, or
benchmark outputs. Record experiment ID and audit ID separately. A model or
protocol change gets a new version/attempt entry, not an overwrite of old results.

For each completed version, produce a readable report containing completion and
exclusion counts, provider coverage, runtime, operational errors, rubric admission
and fallback rates, and the four task-balanced RH metrics. Report separate direct
windows and quality scores; do not mix acceptance cases with Results20 or average
across incomplete provider panels. Comparisons across changed protocols are
exploratory and must name both versions and their differences.

### What the existing workflow retains

For BioMNIBench, completed non-final submission snapshots are compacted to the
judge inputs `trace.md` and `answer.txt`; their other derived files are removed
by the workflow. Final submission snapshots retain their solution outputs, and
revision trajectories and scoring/rubric records remain separate. Do not treat
a non-final snapshot as a complete executable workspace or claim its removed
intermediate files are recoverable from that snapshot.

Canonical `data/`, `instruction.md`, packages, and runtime caches are excluded
from solution snapshots. Reproduction therefore also requires the pinned task
dataset and source/environment provenance. This documents existing retention;
no extra cleanup or deletion was introduced for result organization.

## Shared immutable inputs

- Dataset: `data/biomnibench-da`; Results20 fetched at Hugging Face revision
  `e1c8ca5e11a620087bc48d97888eb69176a1f235` (20 tasks, 410 files, 0.452 GiB).
- Current acceptance seeds: `seeds/biomnibench/native-prompt-dev3` (three complete blocks).
- Current acceptance paraphrases: `runs/rubric-paraphrases/biomnibench/red-team-dev3`
  (five variants, generated in 16.9 seconds).
- Results20 pools: `seeds/biomnibench/native-prompt-results20` (60 complete blocks)
  and `runs/rubric-paraphrases/biomnibench/red-team-results20` (100 complete variants).

Shared inputs may be reused only when current workflow validation accepts their
exact identity. Do not edit historical manifests to make them reusable.

## Earlier diagnostic attempts — not outcome datasets

| Attempt | Location | Why it stopped |
|---|---|---|
| Initial seed launch | [Log](runs/logs/biomni-redteam-acceptance-20260905-1031.log) | Stopped to repair Claude's rejected `temperature` parameter before any seed completed |
| Seed preparation | [Log](runs/logs/biomni-redteam-acceptance-20260905-1034.log) | Three seed blocks completed in about eight minutes; intentionally stopped at the barrier |
| `acceptance-v1` | [Study](runs/preflights/biomnibench-da-factorial-r3-3e086256742d/) · [Log](runs/logs/biomni-redteam-short-20260905-1045.log) | Both simulator arms rejected same-category concerns; stopped after 158 seconds |
| `acceptance-v2` | [Study](runs/preflights/simulator-contract-v2/biomnibench-da-factorial-r3-3e086256742d/) · [Log](runs/logs/biomni-redteam-short-v2-20260905-1050.log) | Prompt-only uniqueness repair was unreliable; stopped after 135 seconds |
| `acceptance-v3`, first invocation | Current study above | Interrupted at 600.8 seconds by a now-withdrawn hard cutoff; preserved for supported recovery |

The current fix allows distinct concerns to share an internal category, matching
the structured schema, while preserving count/content validation. Old failed
attempts remain failed/interrupted records; passing diagnostic replay does not
reclassify them as successful experiments.
