# Experiment reliability: lessons and launch checklist

Recorded after the completed BioMNIBench Results20 red-team experiment, 2026-09-06.
The successful dataset was historically named `20260905-redteam-v7`: 240 completed
assignments and 9,327 verified judgments across seven stages. Historical version
labels below identify incidents, not recommended names for future runs.

No checklist can guarantee a third-party API never fails. The operational goal is
to prevent known local defects, contain transient failures, preserve successful
work, and detect incomplete results before analysis.

## Failures that caused discarded or interrupted runs

| Failure | Evidence / consequence | Current repair or prevention |
| --- | --- | --- |
| Simulator category contract mismatch | Distinct valid concerns sharing a category were rejected; prompt-only repair did not solve the semantic mismatch. | Fixed: validators allow legitimate repeated categories while preserving bounds and repair guidance. Test generation through downstream projection, not only schema parsing. |
| Assessment arrays treated as positional | Valid exact-ID records in a different order could fail; generic errors concealed the issue. | Fixed: exact unique-ID coverage and canonical ordering; continue rejecting missing, duplicate and unknown IDs. |
| Redundant rubric-view winner field | Model-declared winner disagreed with totals and exhausted repair attempts. | Fixed: derive rubric-view winner from validated scores/penalties; rubric-free preference remains independently model judged. |
| Text newline normalization broke hashes | A CRLF fixture reproduced staging/replay disagreement; failed incident responses were not retained, so not every historical failure can be attributed conclusively to CRLF. | Fixed: preserve exact UTF-8 bytes in staging, replay and shared-rubric installation. Test LF/CRLF/CR/mixed newlines and tampering. Never relax hashes to accept an old artifact. |
| Excess local concurrency / nested numeric threads | Assignment concurrency 60 overloaded the laptop; later 30 assignments still spawned 12-thread numeric subprocesses and saturated CPU. | Fixed propagation of project Python and numeric-thread defaults. Measure actual children, compressed memory and swap; assignment concurrency is not a process/thread limit. Start conservatively and increase only from sustained evidence. |
| Native Python plotting abort | macOS reports show Matplotlib GUI initialization SIGABRT, not proven OOM; exact experiment-task attribution was not established. | Fixed headless `Agg` propagation to actual solver commands; verify real PNG creation in the configured child environment. Do not assume every future Python crash has this cause. |
| Provider outages sealed as successful rubric fallbacks | The discarded scientific run had 34 connection-induced fallback stages across 21 assignments, including 16 completed assignments. | Fixed in the successful run: exhausted invocation errors propagate to the circuit without publishing a generation. Keep genuine response-validation fallbacks distinct from unavailable-provider failures. |
| Unsafe workspace snapshot | A generated clean-run directory contained a symlink to live workspace data and failed snapshot validation. | Keep snapshot validation strict; recover through the normal last-scored-checkpoint workflow. Do not rewrite solver output or weaken the validator to make a run pass. |
| Environment / interpreter drift | App-server PATH handling selected the wrong interpreter; editable-install startup files repeatedly acquired hidden flags. | PATH propagation was repaired. Explicit project `PYTHONPATH` was the verified workaround for the hidden-startup-file issue; its external cause remains unresolved. Verify imports in a real child process, not only the parent shell. |
| iCloud files not locally available | During comparator recovery, dataless seed files reported nonzero logical sizes but reads returned empty bytes or blocked; seed validation correctly refused them. | Ensure required inputs/results are actually downloaded before execution. Accepted download requests alone are insufficient; verify actual byte hashes. One file recovered via native download, four via exact-hash original backup restoration with placeholders preserved, then all 230 completed cases passed current validation. Do not rewrite hashes or treat a cloud placeholder as an empty artifact. |

## Hosted API and audit failures: still relevant

| Failure | Evidence / status | Required handling |
| --- | --- | --- |
| Provider-specific request incompatibility | Claude whole-rubric requests rejected `temperature=0`; token-count success missed generation-only Gemini TLS trouble. Both adapter problems were repaired and tested. | Exercise the actual structured-generation and whole-rubric paths with each configured model. Use trusted CA roots; never disable TLS verification. |
| Transient transport failures | EOF, IncompleteRead, SSL errors, RemoteProtocolError and APIConnectionError occurred across providers. The last Claude score succeeded after a later unchanged serial retry. | Bounded retries with delayed recovery; preserve completed records and original errors. A later success does not establish the physical network root cause or guarantee permanent recovery. |
| Gemini input-token rate limit | Explicit HTTP 429 identified 3,000,000 input tokens/minute and retry delays around 49–55 seconds in this run. | Provider-aware pacing and respecting RetryInfo remain code work. Current immediate retries can exhaust attempts inside one limit window. Concurrency alone does not bound tokens/minute. |
| Access / region / credit errors | Explicit unsupported-location responses and some Anthropic insufficient-credit errors occurred; later successes do not prove access is permanently fixed. | Classify separately from throttling/transport. Ask for account/eligibility action when necessary; no endless retry, route bypass, secret rotation or model substitution. |
| Preparation runs before cached-score reuse | Transient token-preparation failure marked existing valid scores failed in the new summary. Even an all-cached 720-job pass took over eight minutes to prepare. | Cache/preparation ordering remains unresolved. Preserve cached bytes and verify raw/summary consistency; use supported recovery, not hand-edited passing summaries. |
| Incomplete direct audit returned exit zero | A mixed success/failure audit originally looked successful to its caller. | Fixed after revision completed; tested both preparation and judgment failures. Still require all-stage coverage checks, not only process exit status. |
| Quality connection errors escaped local retry handling | Some APIConnectionError types bypassed the rubric-free local catch and prevented both quality summaries, despite many saved judgments. | Exception normalization and durable failure summaries remain code work. Preserve partial scores and resume only the missing work after the owner terminates. |
| Failed-attempt evidence missing or delayed | Some proposer failed responses were discarded; direct failed rows could remain only in memory until stage completion. | Durable per-attempt response/error/provenance recording remains code work. Do not invent causes for missing diagnostics. |
| Sealed excluded red-team sidecars | Six sidecars were excluded and were not retried by ordinary resume. Five response-validation fallbacks also occurred in the completed study. | Preserve and report actual treatment delivery. A completed assignment does not mean every intervention succeeded. Do not selectively regenerate or delete inconvenient outcomes. |

## Before launching any new full experiment

1. Give the run a descriptive date-based name, e.g. `biomnibench-redteam-2026-09-05`,
   with explicit `study`, `audit`, `reports`, `acceptance` and `provenance` areas.
   Record source/config identity and model roles separately; avoid ad-hoc v4/v5 labels.
2. Confirm dataset paths, disk headroom, the exact interpreter, package imports,
   headless plotting and numeric thread limits in the real solver child environment.
   For cloud-backed folders, confirm local availability of required artifacts;
   a file listing and logical size do not prove readable contents. Native download
   requests may finish asynchronously or leave descendants unavailable.
3. Safely check credential presence and actual model endpoint availability. Keep
   settled credential consent; do not print keys or expose environment files.
4. Run focused regression tests for changed behavior, then the smallest real
   representative end-to-end experiment with all four conditions and all three
   audit models. For this protocol the validated acceptance design uses three
   revision turns, sufficient for the post-update window.
5. Verify the complete small result, including all seven stages and actual rubric
   admission/fallback behavior. The successful acceptance had 153 unique judgments;
   that count belongs to this design, not every possible future configuration.
6. Freeze runtime code, prompts and analysis before scaling. Any change that
   invalidates identity requires fresh current-format work, not relabeled hashes.
7. Choose concurrency from measured throughput/resources and provider limits.
   The completed run used 30 for revision; this is an observation, not a universal
   safe default. Hosted audit and recovery may need different concurrency.

## During execution and recovery

- Record process ownership, logs, start time and explicit concurrency. Poll actual
  handles and artifact growth; a quiet progress bar alone does not prove a stall.
- Do not impose a total hard cutoff merely to satisfy a duration estimate. Retain
  per-call safeguards and update ETA from successful throughput and remaining stages.
- Stop dispatching new work on systemic failures; drain or safely stop only owned
  processes. Do not launch two writers against the same output directory.
- Separate response-validation errors, provider transport, quota, billing and
  permanent access errors. A model failure is not an analytical abstention.
- Preserve successful bytes before recovery; verify they remain identical afterward.
  Do not restart all assignments to recover a few missing judgments.
- Treat the scientific hypotheses as hypotheses: no model substitution, exclusion
  or changed threshold merely to obtain the expected direction.

## Completion and cleanup gates

- Validate every expected assignment, every configured model and stage, exact
  unique-job coverage, consistent raw/summary records and provenance integrity.
- Retain legitimate abstentions and treatment fallbacks/exclusions. Never clean a
  successful dataset by deleting bad scientific outcomes or referenced evidence.
- Generate analysis only after the coverage gate passes. Report quality, actual
  treatment delivery and uncertainty alongside RH metrics.
- Back up code and original outputs, verify remote checksums, and record cleanup
  targets before removing obsolete runs. Prefer recoverable trash over permanent deletion.
- Saved records bind original paths. A friendly directory rename must preserve
  raw bytes and have a separately verified read/relocation strategy; do not blindly
  replace paths inside JSON or pretend relocated records were generated elsewhere.

## Evidence and priorities

See [experiment log](EXPERIMENT_LOG.md), [code review log](CODE_REVIEW.md), and
[completed report](runs/biomnibench-redteam-2026-09-05/reports/REPORT.md). Full v7 incident
evidence remains available in the verified [GitHub backup](GITHUB_BACKUP.md).

Before the next large run, prioritize typed provider failures and pacing,
cache-first validation, durable per-attempt errors, and safe resumability. These
are outstanding implementation tasks, not claims that cleanup itself fixes them.
