# Result20 runtime failure census

2026-09-11 EDT. Read-only diagnosis completed before implementation, from the
existing home receipts and Slurm readers 10397916/10397928 of persistent NFS.
No provider calls. Counts below identify attempts, judgments, or assignments
explicitly; overlapping snapshots and retries are not summed as distinct cases.
Request-minutes are aggregate occupied request time, not elapsed job time or a
claim that all work in a failed job was wasted. Human recovery time is unmeasured.

| Stage / cohort | Failure type / provider | Observed count and error | Time attributable or observed | Recovery / shared applicability |
|---|---|---|---|---|
| PaperBench rubric audit, 10387274 | Invalid cardinality / Anthropic | 137 rejected attempts among 46 exhausted judgments; one additional API timeout | Producer 2h02m55s includes 1,754 successful rubric judgments and other stages; invalid-call durations unavailable | Native resume recovered 19; shared audit representation, exposed by long PaperBench rubrics |
| PaperBench unchanged resume, 10388169 | Cardinality / Anthropic | 92 count errors, one connection error, one timeout; 27 judgments still missing | 2h10m44s job, not pure waste; two timeout attempts across both native jobs imply about 10 request-minutes | Preserved 3,314 valid judgments; ended at 3,333. Failed files manually archived because numbered native failure files would be overwritten |
| PaperBench exact-request diagnosis, 10389550 | Extra/missing criteria / Anthropic | Two responses: 146/145 and 868/872; neither hit token cap | 35m16s, including approximately 23m37s audit-lease wait | No count repair; motivated count-safe single-call format. Shared infrastructure |
| PaperBench schema tests v1–v4 | Provider grammar/schema complexity / Anthropic HTTP 400 | Seven rejections: both 145/872 in v1–v3; 872 only in v4. V4 145 passed | Jobs 4m25s, 22s, 23s, 5m06s; includes compilation and one success | Exact tested v5 indexed 64-leaf blocks plus tail passed 145/145 and 872/872 on first calls in 10392624 (24m07s). Provider limitation, not benchmark logic |
| PaperBench v5 recovery, 10393145 | Full-rubric 300s request timeout / Anthropic | 18 APITimeoutError attempts, six exhausted judgments (five 872, one 403 criteria) | Approximately 90 aggregate request-minutes; entire job 1h28m24s | SSE with 300s network-inactivity timeout recovered all six, one call each. Shared long-call transport |
| Same v5 recovery | Invalid structured response / Anthropic | Four attempts: two block-count errors, two non-JSON outputs; 19 new successes plus two reused validation successes | Individual duration unavailable; included in preceding job | Existing bounded retries recovered these. V5 still requires strict local validation |
| PaperBench streaming recovery, 10394282 | No failures / Anthropic | Six successes; five 872/872, one 403/403 | Streams 317.79, 724.11, 735.29, 979.36, 1004.37, 1223.35s; job 54m43s | 3,333 native + 21 earlier v5 + six streamed = 3,360. Five healthy streams exceeded legacy 360s watchdog equivalent |
| PaperBench revisions, 10386492 | NFS cleanup ENOTEMPTY / no provider cause | Two assignments: rice temporary judging cleanup, lbcs final live-tree cleanup; 118 completed | Initial job 1h57m06s; recovery 10387246 34m30s includes real remaining revision work | Native checkpoint reuse plus incident-specific orphan quarantine. Shared filesystem/session lifecycle; not repaired here |
| PaperBench recovery orchestration | Manual recovery / no provider | 10387189 stopped on protected systemd helper descriptors; 10394223 stopped before calls on incomplete diagnostic-request lookup | Human time unknown; additional inspection/dispatch cycles | Exact process inspection and parent-attempt request reuse; historical helpers preserved. Shared operational overhead |
| BioMNIBench trace revisions, 10381602 | Codex app-server/session startup | Six RPC-socket startup failures (two startup attempts each), one FileNotFoundError and one solver-turn failure in 05:15:56Z snapshot; 57 additional circuit-blocked assignments | Six failed assignment spans total 7,428.53s, including useful earlier work; whole job 1h34m57s | 55 assignments completed; later same-study recovery. Shared runtime; no evidence these were 7,200s solver-turn expirations |
| BioMNIBench trace resume, 10382423 | Codex session transport / stale runtime state | Five closed-stdout startup failures, one live-workspace checkpoint mismatch, 30 circuit-blocked assignments | Five failed spans total 819.96s; mismatch 3.46s; job 1h01m15s with 29 new completions | Existing isolated readiness/completion repair and 32 CPUs/workers completed remaining 36 in 10382970; 84 valid assignments preserved. Shared runtime, leave solver policy alone |
| BioMNIBench trace direct full-trajectory audit | Anthropic 5xx | 29 HTTP 529 overload operation errors in 10382970 telemetry; five terminal semantic judgments exhausted three attempts | Error durations unavailable; audit-only recovery 10384474 3m33s | Native detect --resume added exactly five judgments, reused 955 RH + 1,958 rubric + 360 holistic + 240 preference scores. Shared existing recovery works |
| BioMNIBench trace generation telemetry | Timeout/connection/5xx, provider not identified by aggregate counter | 10381602: 10 API timeouts, one connection, one internal error/HTTP520; 10382423: four timeouts; 10382970: eight timeouts, one connection, one internal error/HTTP520 | Operation durations/semantic attribution unavailable | Existing generation retries; these are not evidence of full-rubric 300s failures, nor attributable OpenAI 5xx counts |
| OpenAI 429/5xx | No attributable Result20 count established in inspected evidence | No provider-specific OpenAI 429/5xx incident identified; unassigned HTTP520 counters above remain unassigned | Unknown | No retry-policy change justified |
| Gemini capacity checks | HTTP429 RESOURCE_EXHAUSTED / Google | Saved PaperBench and BioMNIBench checks report depleted prepayment credits; two inspected receipts, not a claim of independent underlying incidents | Unknown | Paused/omitted under historical authorization; no new probe and no transport repair for a billing failure |
| BioMNIBench revision, 10367631 | Slurm preemption / no provider | One confirmed PREEMPTED job, six assignments completed; no HTTP error recorded | 9m32s job, completed work retained | Same-source native resume 10367784; shared scheduler exposure |
| Solver turns / scheduler walltime | 7,200s turn timeout / Slurm TIMEOUT | None established in the inspected Result20 receipts; startup timeout and generic solver failure are not turn-duration evidence | Not estimable | Keep solver timeout_seconds=7200 and scheduler behavior unchanged |
| Audit/report orchestration | Resume/review/lease overhead | Repeated native scans and private recovery/report jobs; 10394984 report job took 42m25s | Includes native replay/report work and lease wait, not all avoidable. Human time unmeasured | No new recovery framework: fix transport/representation and preserve failed-attempt files in ordinary resume |

## Evidence and limitations

Home evidence (relative to `/home/aydanh/repos/rubric_gen`):

- `docs/reports/2026-09-10/paperbench-static/{recovery,diagnosis,keyed-validation,v5-recovery}.md` and `results20/provenance.json`.
- `runs/paperbench-static-v2-20260910/{keyed-validation-10392624,v5-recovery-10393145,v5-stream-recovery-10394282,v5-stream-report-10394984,gemini-check}.json` and corresponding `runs/slurm-paperbench-*.out`.
- `docs/reports/2026-09-10/trace-forensics/{README.md,audit-recovery-failures.json,gemini-existing-check.json}`, `EXPERIMENT_RUNS.md`, `EXPERIMENT_LOG.md`, `docs/BABEL_SETUP.md`.

Read through Slurm under `/data/user_data/aydanh/rubric_gen/runs/`:

- `paperbench-v5-missing-only-20260910/*/audit/*/*/attempt-*/result.json`: 19 successes, 18 API timeouts, four validation failures (the two initial successes were reused elsewhere).
- `paperbench-v5-stream-missing-only-20260910/*/audit/*/*/attempt-*/{result,transport-result}.json`: six complete streams, timings above.
- `trace-repair-result20-20260909/diagnostics/failure-evidence-*.json`, `diagnostics/runtime-repair-before/receipt.json`, and `owners/candidate/{10381602-20260910T043109Z,10382423-20260910T061730Z,10382970-20260910T080302Z,10384474-20260910T093253Z}/metrics.jsonl`.

Slurm accounting independently confirmed the job states/durations listed above.
This is a bounded evidence census, not a recursive census of every historical
artifact under NFS. Telemetry snapshots can precede final publication; terminal
completion receipts take precedence over their assignment totals. No scientific
output was modified and no failure was inferred from a quiet log.
