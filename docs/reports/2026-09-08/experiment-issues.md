# Experiment execution issues and prevention guide

2026-09-08 EDT. Evidence-based working investigation; the four-condition Result20 remains incomplete. Do not equate infrastructure success with scientific success or request-byte savings with end-to-end acceleration.

## Measured critical path

- Full fresh user-trace10358980 ran12:45:50–14:49:27 (2h03m37s), ended56complete/4failed. Slurm TotalCPU4h03m19s implies1.97 average CPU cores across its4CPU allocation; sampled maximum2.67 cores, global active slots reached60. Sampled process-tree RSS peak38.4GiB,416processes (includes descendants; not416 API requests). Memory request128GiB. These measurements do not establish provider stability at60: the run failed.
- Native recovery10360063 ran14:52:32–15:32:51 (40m19s), recovered three assignments, ended59complete/1failed. TotalCPU3m42s implies0.092 average cores; peak active slots7. This is a serial/provider/filesystem tail, not insufficient allocated CPUs.
- Successor10362700 began18:04:41:2h31m50s after preceding failure. This gap includes engineering/validation/orchestration, not provider execution. It must be reported separately rather than attributing the full delay to API timeouts. Current job reuses all59successes and is on another node with telemetry-only source05acf8e.
- Final full-static/user-static recovery-plus-audit jobs took18m18s/19m12s; full-trace recovery-plus-audit took29m36s. They reuse prior work and are NOT fresh condition runtimes.

Sources: slurm-accounting.txt; runs/runtime-performance-10362795/summary.json; original launch/result/metrics receipts named there. Stage cumulative counters are not additive across samples or overlapping jobs.

## Distinct causes and fixes

1. **Growing/duplicated evidence.** Assessment embeds each full artifact once per pair; induction also repeats preferred/rejected records. Snapshot of latest sealed generation for each of60user-trace assignments: assessment pair/artifact bytes32,044,834→19,110,302,40.36% reduction with exact text/pair reconstruction. Unchanged instruction/rubric/schema bytes excluded. Candidate9587d92 deduplicates assessment; induction extension passes76tests10362831. No pair, artifact, trace, threshold or score definition is dropped. Format changes are versioned and need fresh native scientific artifacts, not fabricated resume compatibility.
2. **Output and request ceilings.** Earlier1MiB requests and32768output ceiling rejected real late-round histories/responses. Current4MiB/65536 prevents those particular local ceilings but is capacity accommodation, not speed optimization. Keep actual response completion/token usage measured; lower ceilings alone would recreate failures.
3. **Mixed repair/transport retry budget.** evolution_stage.run_stage shares six attempts between model-output validation failures and provider errors. One timeout on the last attempt can terminate after five invalid responses. Provider errors have no outer backoff; SDK retries are disabled. Validated outputs are cached, rejected responses/repair state are not, so resume can repeat failed semantic repairs. Need distinct bounded transport and semantic budgets, transient/permanent classification, backoff, durable attempt provenance. Do not silently alter frozen current generation identity or weaken validators.
4. **Shared filesystem hot path.** Previous live workers waited in nfs4_handle_exception; syscall evidence was consistent with append-file open, but pathname was not captured. Original telemetry opened/locked/closed per event while holding a provider lease. Implemented persistent process-owned append descriptor and local thread lock; actual slot admission remains cross-process/node flock.117tests/native59/two provider checks passed. Current live snapshot showed socket polling, not D-state; synchronous NFS writes remain a possible risk, so do not claim every NFS issue solved.
5. **Whole-study stage barrier.** Dispatcher runs revise then detect, stopping on failedrevise. Thus59finished assignments receive no audits while one unfinished assignment holds the condition. Safe future pipeline requires explicit immutable completed-assignment audit ownership, validation and final population completeness. Starting detect on a mutating study without supported per-assignment validation is not an acceptable shortcut.
6. **Manual recovery/report dependency graph.** Hard-coded prior owner/report IDs require replacement launchers/seals; afterok on failed owners yields DependencyNeverSatisfied. Repaired current graph10362700→10362724→10362725/10362726;exposure10359085 andfigures10359093 follownewreports. Future execution should bind immutable experiment identity once, journal successive native resume attempts, classify failures automatically, bound recovery, and release analysis only after verified fullcoverage. Avoid hours of per-failure customscript recreation.
7. **Observability gap.** operation_completed means a provider returned, not semantic validator acceptance. Generic solver reconnect telemetry lacks HTTPclass. Add separate safe counters for transport outcome, schema/semantic rejection class, cachehit, payload bytes/tokens, input construction, localvalidation, filesystemcommit, queuewait and attemptwalltime. Never logkeys or rawpayloads in runtime counters.

## Validation and rollout criteria

- Preserve current running source and all completed evidence. No healthy owner interruption.
- Compaction: exact full-content reconstruction; same pairorientation/coverage, redteamtraceisolation and allvalidators.76tests passed assessment10362741; measure all60 saved histories, then representative frozen matched provider acceptance. Token/latency benchmarks need actual calls; byte savings alone insufficient.
- Retry changes: injected timeout/rate-limit/permanent error/invalidresponse tests; prove boundedtotalcalls, no retry permanent failures, successful cache reuse, no change to admission/scoring. Separately identify any altered attempt budget in fresh condition provenance.
- Recovery orchestration: simulate workerexit, schedulertermination, nodefailure, missingaccounting and already-liveowner; demonstrate oneowner, no duplicates, preserved successes and repaired reporting withoutmanualIDs. Time between terminal failure and safe retry should be explicitly measured.
- Full60: monitor useful validated operations/minute, p50/p95calllatency, timeout/429/retryfraction, RSS, CPU, memoryevents, NFSblockedthreads and checkpoints. Tune only from observed bottlenecks; retain global ceiling60 and4CPU unless CPU evidence changes.
- Completion requires all240assignments and configuredSol/Opus audits, complete figures and honest pairedRH/quality analysis. External failures cannot be guaranteed absent; deterministic local failures and unattended recoverable delays should be prevented/tested.

## Current unresolved incident and next actions

- 2026-09-08 18:15 EDT: Recovery10362700 has59completed assignments and one da-16-1rep001 pending judgment. It completed five provider operations, then recorded one300.196s failure and another retry; useful semantic completion has not yet advanced the round. Telemetry optimization does not eliminate external/request-size-related timeouts. Keep current source frozen and inspect actual failureclass before further intervention.
- Current source05acf8e remains separate from request-compaction candidate9587d92 plus tested induction extension. Do not copy candidate files into the live checkout or patch old manifests.
- Two authorized work streams: finish current Result20/native audits/plots, and harden/benchmark the next execution version. Analyze complete user-static versus user-trace immediately when report10362725 finishes; inspect exposure/quality/recovery confounds before choosing a single targeted dev3 change.
- Root EXPERIMENT_LOG.md owns chronological experiment events; CODE_REVIEW.md owns implementation concerns; this guide owns consolidated failure mechanisms and prevention/acceptance criteria. Preserve negative results and actual historical configuration.

## Before subsequent production runs

1. Reuse native-valid sealed seed/paraphrase pools. Verify all20tasks×3replicates and exactconditionconfig; never regenerate shared inputs unnecessarily.
2. Benchmark realistic late-round payloads, not just tiny API probes. Track input/output tokens, schema size, semantic acceptance, retries and end-to-end elapsedtime. Do not assert performance from byte count or unittest success.
3. Confirm frozen source/config/provideridentities and resumability on actual saved checkpoints before launch. Never invent compatibilitymetadata.
4. Use one journaled owner percondition, sharedglobal60, bounded recovery and correct success-dependent reporting. Terminal failure must create an explicit actionable status; no unattended DependencyNeverSatisfied chains.
5. Inspect memory/CPU/NFS/latency together. FourCPUs are adequate for the observedremoteAPIload; a single sequential tail cannot consume60usefulrequests. Avoid increasing CPUs or launchingduplicates as a response to quietlogs.
6. Separate infrastructure-invalid attempts from scientific outcomes. Verify everyassignment and bothactiveauditors before complete-result claims; Gemini remainscreditpaused.

## 2026-09-08 18:20 EDT — validated candidate improvements

- Provider calibration10362844 on the same saved319,560-byte development assessment: original33.147s, compact198,464bytes/20.108s; both schema-valid. This single matched pair supports feasibility,not a guaranteed speedup or semantic-equivalence proof. No outputs enter scientific results.
- Separate transport/semantic retry candidate passes78tests10362868. It keeps semantic response attempts unchanged, permits at most3additional transient retries, uses bounded exponential backoff, fails immediately on known permanentHTTP/auth/quota classes, and updates recorded generationcallbudgets/nativevalidation bounds. Tests cover last semantic repair surviving a timeout, permanentfailure stop, and completedgeneration replay. This candidate changes generationfingerprints and is not installed in current05acf8e. Durable failed-repair caching and automatic stage orchestration remain outstanding.

## 18:25 EDT — broader execution validation

Job `10362885` passed **199 tests in 45.83 seconds**, covering evolution, red-team behavior, pre-treatment reuse, revision execution/artifacts, rubric generation, architecture, global capacity, Babel launching, and portability. This supports the candidate’s code and native replay contracts; it does not prove unattended end-to-end Result20 completion. Automatic stage orchestration and durable failed-repair recovery remain open. The current frozen recovery still uses its original retry behavior.

## 18:28 EDT — same-allocation revision recovery candidate

The standard Babel dispatcher now uses `scripts/babel/stage_recovery.py` to retry a joined, failed revision child only when all unfinished selected assignments have recognized transport timeout/connection errors. It retains one owner, checks frozen source before each invocation, preserves separate logs and manifest hashes, and runs at most three native stage invocations with a ten-second cancellation-aware delay. Permanent/unknown errors, incomplete/running manifests, signals and source drift do not trigger automatic relaunch. Successful completion then follows the existing audit path under the same job.

Fault-injection and launcher/runtime tests `10362903` passed **48 tests in 17.59 seconds**. This is not yet an accepted production Result20 launcher: the active custom dispatcher remains frozen, and scheduler/node loss plus audit-specific recovery still need explicit handling and a complete end-to-end smoke. Do not claim unattended full-pipeline completion from these tests alone.

## 18:34 EDT — confirmed Anthropic input-token rate bottleneck

Current user-trace full-trajectory summary has Sol60/60completed and Opus35/60completed,25failed with `RateLimitError`. The provider explicitly reports HTTP429 `rate_limit_error`: requests would exceed the organization’s **10,000,000 input tokens per minute** for Claude Opus5. This is a token-rate limit, not depleted credits, CPU pressure, or proof of a provider outage. Do not infer a complete-panel RH rate from the35surviving pairs.

The global60request-slot limit prevents excessive simultaneous calls but does not limit aggregate tokens per minute. Large full-trajectory inputs plus immediate audit retries can overshoot provider admission even when fewer than60calls are active. `detection/job_runner.py` currently retries exceptions immediately, with no shared token-rate pacing.

Required fix: shared cross-process/node Anthropic token admission before generation, pacing calibrated to the observed10M limit with headroom, plus Retry-After/cooldown handling. Preserve request text, models, thresholds, successful judgments and globalworkerceiling60. The current owner continues later audit stages; native recovery after it terminates must reuse completed judgments and fill missing coverage under validated pacing. Do not rerun successful Sol judgments or substitute another evaluator.

## 18:38 EDT — token-rate limiter candidate

`runtime/capacity.py` now contains a cross-process/node rolling input-token window for Anthropic hosted generation. It uses the existing provider token-count integration, caches counts by request hash, reserves at most8million tokens per60seconds across the shared runtime, and releases global provider slots while waiting. A429 imposes shared cooldown of at least60seconds or Retry-After; all60worker slots remain configured. New state warms up for60seconds to avoid immediately overlapping an unpaced preceding burst. This cannot account for unrelated external projects sharing the same provider organization, so2million tokens/minute headroom and subsequent429cooldown remain necessary.

Tests10362923 passed48checks. The isolated source `59757ce` at `runs/babel-code/result20-token-runtime` differs from current05acf8e only in runtime/capacity.py (plus its test), preserving scientific generation/audit fingerprints. Follow-up10362926 validates final fork/temp-file safeguards, source diff and all60completed revisions read-only. Production missing-audit recovery has not yet launched.

### 18:49 EDT — paced audit recovery passed

Job `10362935` completed in **6m24s** with an unchanged source seal and successful native detect exit. It filled the 25 missing Opus full-trajectory judgments, reused saved audits, and recorded no HTTP failures in runtime samples. Peak sampled aggregate occupancy was 44 provider slots and process RSS about 1.15 GiB. Keep the global ceiling at 60 and the shared Anthropic admission budget at 8M input tokens/minute; this small recovery does not yet demonstrate sustained 60-call fresh-panel stability. SDK automatic retries are disabled, so generation retries re-enter the shared token admission path. Native all-stage coverage validation follows as `10362937`.

### Prelaunch capacity regression caught

Fresh main-derived dev3 sources retained a 32,768-token proposer output cap even though the successful Result20 runtime allowed65,536. On2026-09-08 the two pending dev3 jobs were held before provider calls, both arms and main restored to65,536, and acceptance gained explicit assertions for65,536 output tokens and4MiB request bytes. Match runtime resource defaults to the accepted source when deriving fresh checkouts; passing workflow tests alone does not prove that previously required capacity settings were retained.

### 19:58 EDT — fresh dev3 in-job transport recovery evidence

Live jobs10363145/10363146 recorded five failed call attempts: four300-second APITimeoutError events and one10-second APIConnectionError, with no HTTP status. Every failed attempt now has a later successful completion with the same request key inside the same job; repeated failures can share a request key, so these are not five distinct assignments. Recovery elapsed15.7–324.0seconds after a failure, with the longest including another timeout.

This demonstrates working bounded request retries on fresh revision work, not a promise of failure-free execution or completed audits. No new recovery job was submitted. Snapshot: investigation/dev3-evidence-sidecar-20260908/transport-recovery-checkpoint.json; retain global60 and token pacing, and investigate terminal failures only after the owning process resolves.

## 20:49 EDT — Transient NFS cleanup after saved judgment

Result20 job10364363, static da-16-1/rep001, failed at s000 when removal of its temporary evaluation directory returned errno39 ENOTEMPTY. A durable judgment copy exists and the temporary directory was subsequently empty, supporting a filesystem cleanup race rather than provider failure. Other assignments continue; no active source or output was changed.

An isolated fix retries only ENOTEMPTY/EBUSY up to seven times with 15.75seconds total backoff, preserving ownership checks and terminal errors. Slurm validation10364655 passed164tests in29.62seconds. This is tested preparation, not a completed recovery; wait for the owning invocation to finish and verify native resume identity before applying it.

Recovery scheduling: job **10364765** waits for **10364363** to exit, then invokes the original frozen launcher and native `--resume` in the same namespace. This preserves runtime identity and lets native validation decide reuse; it does not install cleanup fix7697ec5 into this study. Report10364371 now waits for successful10364765 and10364364. No compatibility metadata was changed.

### 20:54 EDT — Recurrence under concurrent revision load

A second static assignment, da-10-1/rep003, failed with the same errno39 cleanup error at s001. Both reported temporary directories are now empty on read-only inspection, recorded in `investigation/result20-cue-contrast-20260908/cleanup-failure-checkpoint.json`. Static has1completed/57running/2failed; trace60running. The existing queued native continuation10364765 covers both missing assignments; no additional owner or retry job was created. This recurrence makes the tested cleanup fix necessary for future launches, while current source remains immutable.

## Recovered Result20 HTTP520

Trace10364364 recorded InternalServerError/HTTP520 on evolution request `a654289536af3429e5125ae410abfd4a2c6d122dc401f63e0eb6da2d7e8b45a2` at epoch1788916389.43. The same request key completed at1788916405.71,16.28seconds later, inside the original job. No terminal assignment failure or separate recovery submission resulted. Event source `runs/.runtime-babel/events-babel-m9-20-601748.jsonl`; distinguish this successfully handled provider event from the separate NFS cleanup failures.

## 21:27 EDT — Codex thread/start hang in static tail

Static da-15-8/rep002 remained in its first turn for approximately45minutes, with no session_id or solver artifacts beyond s000. Read-only compute inspection verified Codex PID2257643 under adapter2254478 in that assignment's exact workspace; its SQLite event sequence stopped after thread/start, while background model-list refreshes continued. No solver session began. The configured7200-second turn deadline did not provide a separate startup deadline.

After rechecking executable name, parent PID and workspace, SIGTERM was sent only to the hung Codex subprocess. Owner10364363 then recorded native BrokenPipeError for this assignment and entered COMPLETING, preserving57completed assignments and the two earlier cleanup failures. Existing continuation10364765 resumes all3missing assignments after owner exit; no new experiment or duplicate job was submitted. Future runtime work should bound session startup separately from scientific turn duration and retry only when no session began, with focused tests. Do not change active frozen sources.

## 23:33 EDT Duplicate red-team pair crash

Crossfile10366421,da13-3rep1: checkpoints1and2 share sourcehash8d5b8b62fadff5bab0f0e92cd8362fac81afde508b01f793e43161f4814d5af0 andsidecarworkspacehash51834942b512f48e99956de4b862bfbfacb92e53668b5279d73d70add9a1ab6f, with distinctsealedtrajectories. Artifactpairs arededuplicated butthecontrastbuilder appendedtwored_team_evidence records; ArtifactHistory rejectsduplicatepairIDs. NoHTTPfailurecausedthiserror.

Fix: retainfirstchronologicaltrace for eachsemanticpair, consistentwithonecomparisonpair/weight; retainallrawsidecars. Regressiontest createsrepeatedpairswithdifferenttraces andverifiesoneevidencerow/noextraweight/rawsecondtraceunchanged.81focusedtestspassed. Do notmutatecurrentfrozencode/manifests; anisolatedrepair mustpreserveprovenance andnativevalidation. Do notrerunvalidcells orcount thisfailureasRH.

## 2026-09-09 Scheduler preemption, separate from provider failures

Slurm preempted10367631 after9m32s, with6completed assignments; noHTTPerror recorded. Native same-source resume10367784 started onbabel-m9-20 and advanced saved checkpoints; report10367657 reconnected afterok10367784. Currentcpu partition absent; general CPU-only rejected(min1GPU). Account-free general/normal4CPU128G1A6000/48h test-only accepted but estimated09:54start, so do not move the healthy immediate recovery into that queue. Test-only response10367800 is not a submitted job.

Preemptible allocation cannot guarantee uninterrupted completion. Preserve receipts/checkpoints, confirmterminal Slurmstate, then native--resume with the same frozen source; do not fabricatecompatibility or rerun completedcells. A general allocation is an approved alternative when itsGPUrequirement andqueuewait are worth the tradeoff; no GPUcomputation is needed by this workload. Rechecklivequeue estimates for future runs.

## 2026-09-09 01:56 EDT: Audit tail and non-HTTP errors

Bounded-score survivor audit 10367838 reached 106/108 full-trajectory judgments; missing cases were revision-000093 and revision-000152, both Opus. Runtime events recorded one `APITimeoutError` with no HTTP status, followed by an active automatic retry. The configured hosted request timeout is 600 seconds and audit attempt limit is three. An empty HTTP-status counter does not mean no timeout failures. Inspect operation_failed error_type in the job-specific events before diagnosing a stall; preserve saved judgments and let bounded native retries run before considering recovery. This is a runtime observation, not a scientific outcome.

## 2026-09-09 03:24 EDT: Preparation connection failures bypass judgment attempts

First-concern Result20 completed all60revisions, full/post/finalrevision RH and allrubric/qualityjudgments. Seven finalartifact preparations failed APIConnectionError with attempt_count0 (fiveOpus,twoSol), leaving detect exit1 despite progress reaching120/120 processed jobs. Inspect summary.records statuses, not only saved score files or progress totals. Frozen native resume10368806 reuses valid outputs; investigate preparation retry coverage separately before future launches. Raw failedrecords preserved in failure-checkpoint-10368391.

## 2026-09-09 05:12 EDT — Trace policy assessment timeout tail

Owner `10368826` reached 58/60 successful revisions before `da-13-6` replicate 3 exhausted five proposer attempts in `assessment_development_rubric` (four provider failures; final `APITimeoutError`, underlying `httpcore.ReadTimeout` while receiving response headers). `da-15-2` replicate 3 remains live. No HTTP 429 is recorded in the owner metrics; this is not evidence of CPU saturation or a rate-limit burst.

The frozen launcher already supports up to three native revision invocations for recognized transient transport failures, retaining completed assignments and checking source identity. Wait for the live invocation to join; do not submit a competing recovery owner. Confirm its recovery receipt and final audit coverage before treating the condition as complete. The long serial tail means peak concurrency 60 does not guarantee short end-to-end runtime.

## 2026-09-09 05:39 EDT — Full-trajectory audit fan-out

At 118/120 processed judgments in owner `10368826`, missing score files were Opus cases `revision-000177` (da-15-7 replicate 2) and `revision-000220` (da-15-7 replicate 3). Their completed Sol records show respectively 108 and 4 planned/completed chunk calls, both on attempt 1. Replicate 2 contains 31,200,807 source bytes and 12,702,855 compact characters after removing 18,486,689 exact-duplicate characters; replicate 3 has 829,847 compact characters. These are Sol plan counts, not verified Opus plan counts.

`detection/job_runner.py::_run_once` processes each judgment’s chunks sequentially; the full-trajectory rule aggregates the maximum score across chunks. Thus a few enormous trajectories can dominate end-to-end latency even with aggregate capacity 60. Preserve complete evidence and current aggregation for this frozen comparison; report chunk/exposure counts with RH, and investigate redundant solver output at its source for future efficiency. Do not truncate evidence or change aggregation mid-run.

### 05:40 EDT — Source of oversized evidence

Read-only inspection of da-15-7 replicate 2 `submissions/s005/trajectory.stream.jsonl` attributes 30,566,295 serialized characters to 58 `codex.turn.diff.updated` events, out of a 31,166,980-byte stream. The largest repeated records are approximately 6.06M characters each; their diffs cover `analysis_revised.py`, `answer.txt`, and cervical/lumbar/thoracic duration-ranking TSV artifacts. Cumulative file-diff telemetry, rather than ordinary assistant prose alone, dominates this case. Exact deduplication already removes repeated records, but distinct cumulative snapshots remain large.

Future optimization must first establish which telemetry duplicates already-retained command/file-change evidence. Any evidence projection change needs focused fidelity tests and separate versioned audit provenance; do not remove these events from this active frozen evaluation or silently redefine full-trajectory RH.

## 2026-09-09 Private weak-context diagnostic failures

10369750 incorrectly checked a penalty-only excerpt as a complete100-point study rubric; failed before calls. Native scoring parser supports penalty-only diagnostic input; v2 checks exact criterion levels/title while leaving production validation intact.10369754 then completed one judgment but report extraction expected wrapped `raw_report` instead of native `criteria`/`reasoning`. v3 revalidates/reuses that successful attempt and only requests the remaining three judgments. These are private harness defects, not provider failures or scientific nulls. Future harnesses must inspect actual return formats and separate complete-study validation from subset scoring.

## 2026-09-09 08:46 EDT — Criterion-update audit transport failure and setup overhead

Owner10369781 preserved60completed revisions and232holistic scores before OpenAI APIConnectionError terminated detect. Recovery10370563 invokes native detect --resume only, preserving all successful audits; dependent report jobs were repaired to afterok10370563. This is a transport failure, not observed HTTP429/quota exhaustion.

The recovery then spent over7minutes in uv sync before its scientific launch receipt. A read-only process check inside the allocation found uv with low CPU/RSS; no auditor was active yet. Each wrapper constructs a job-specific environment and node-local cache, so environment preparation can dominate a small missing-audit tail. Do not modify this active wrapper. A future immutable environment cache keyed by Python/lock/source requirements needs validation before adoption; no cache optimization has yet been deployed.

### Verified second failure and successful bounded recovery

10370563 completed the missing holistic calls but exited1 because10RH preparation calls to hosted token counters failed, even though the corresponding raw RH judgments already existed. Native detection plans every case before checking saved scores; token-counter clients use max_retries=0. Snapshot failures are preserved under its owner receipt. A same-source native resume10370740 with8audit workers passed full coverage in1m41s, aggregate capacity remains60. This distinguishes burst-sensitive preparation from model-generation failure. Future runtime work should persist validated request plans/counts by exact identity and retry transient counter transport failures; neither local token estimates nor fabricated historical metadata are acceptable substitutes.
