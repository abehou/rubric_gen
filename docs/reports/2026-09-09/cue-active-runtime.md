# Active-violation Result20 runtime checkpoint

Scientific owner10373129 runs on babel-l9-20, frozen sourcec507d40, bundle0675408. Owner directory: `/data/user_data/aydanh/rubric_gen/runs/result20-cue-active-violations-20260909/owners/trace-results20/10373129-20260909T170453486095Z`.

At elapsed130seconds, shared runtime telemetry reports60active provider slots,60running assignments,60completed initial judge calls and60completed simulator generations. All60initial checkpoints are saved; all60states are turn_in_progress. No recorded HTTP failures, operation failures or repeated requests at this early checkpoint. This establishes successful startup at60, not whole-run stability or a completion ETA.

Cgroup memory peak16,817,983,488bytes (~15.7GiB), noOOMevents; sampled CPU0.23cores. Process count370 and thread count4173 include subprocess/session infrastructure and must not be described as60OSworkers. Shared disk free343,192,633,344bytes (~319.6GiB). Keep monitoring memory and provider tails.

Dependent jobs: report10373145 afterok10373129; joint-gates10373156 afterok10373145. Reports reuse frozen static/originaltrace rows and require complete native fresh-arm coverage. Gates retain the already-prespecified endpoints, margins, task-bootstrap seed and draw count; only the candidate arm label changes. No outcomes are available yet.

At elapsed286seconds, saved checkpoints increased60→65;55assignments were in solver turns and5in judging.60provider slots remained active, no recorded operation/HTTP failures orOOM, cgrouppeak~24.4GiB. Early saved-prompt inspection found60prompts and0active-violation notes; this does not yet establish intervention exposure. Next inspect manifest flags and eligibility at matching checkpoints before interpreting zero delivery.

13:15 EDT: At latest elapsed578seconds telemetry,56provider slots active and no operation/HTTP failures orOOM; cgrouppeak28,533,043,200bytes (~26.6GiB). Live saved-output census advanced to81evaluations/81prompts,3penalized checkpoints and3prompts with policy notes.21states judging/39solverturns. First observed delivery is established, without outcome or efficacy claims.

13:21 EDT: Read-only compute verification checked113submitted prompts against native rubric/score hashes:5notes exactly match currently violated requirements,0mismatches. Diagnostic initially resolved bare `env` to nonexecutable `/home/aydanh/tools/uv/env`; retry with `/usr/bin/env` passed. This affected only the monitoring step, not the scientific job.

13:34 EDT:12/60revisionassignments complete,277savedcheckpoints. One evolution-generationAPIConnectionError (request4a31d0ddd29f396413e82ca5d5cd878fe9c3b367dc73842c13dc6efae2c08081) was followed by same-key operation_completed7.09seconds later in events-babel-l9-20-868347.jsonl. Native retry recovered in-place; no manualrecovery orscientificinvalidity inferred.

At elapsed1972seconds telemetry:20/60revisionassignments complete,315checkpoints,49activeprovider slots; onlythepreviouslyrecoveredAPIConnectionError remains recorded. Cgroupmemorycurrent15,531,270,144bytes,peak34,370,842,624bytes (~32GiB), noOOM. Declining activeconcurrency reflects completedassignments, not a reduced configuredlimit.

At elapsed2376seconds:25/60revisions complete,374checkpoints. FirstAPITimeoutError was evolution-generation at300.20seconds; same request78479ef91bf14a726487fbab2bd36436fc9aa666d1d84a4c551f23ef5c2d1ca1 completed6.62seconds later via native retry. Both recorded transport failures recovered; no separate recoveryjob.

At~50minutes, request9fed074e3b07202f15e918eeef7d6303c00176ee29f39a06c788731d5fe6a3fc recovered withsame-key operation_completed (22.34second successful attempt) aftertwo RuntimeErrors at293.19/286.34seconds. Exactprovider response message was not retained in operation telemetry, so do not label these output-limit errors without further evidence. Latestfullcensus27completedrevisions/440checkpoints; allrecordedfailedrequestkeys now have subsequentcompletion. No separate recoveryjob.

14:05 EDT: Read-only compute census: 44/60 revision assignments completed, 15 judging, 1 solver turn; 492 checkpoints. Shared disk free 343,714,824,192 bytes (~320 GiB). All 18 recorded failed operation attempts have subsequent same-request-key completions; no separate recovery job was required. Scientific job 10373129 and its dependent reports remain owned and unchanged.

14:08 EDT: Read-only native prompt verification inspected 468 saved prompts and verified 42 active-violation notes with zero mismatches. This establishes delivery fidelity only; the complete outcome and terminal delivery census remain pending.

14:22 EDT: Scientific job 10373129 FAILED (exit 1, elapsed 01:13:10). Read-only diagnostic 10374342 found 59 completed revisions and one da-14-3 rep-001 failure: `ValueError: artifact history has invalid red-team evidence`; no audit stage ran. All prior transport retries recovered, but this distinct validation failure correctly stopped automatic retry. Duplicate pair evidence is a code-based hypothesis requiring saved-file verification; preserve all completed work.

Recovery source 30ae38e applies the already-existing ecc152d duplicate-pair correction only (7 lines). Focused regression reproduced the original ValueError, then 8/8 tests passed. Prompt identity remains 3b108c07ba41bf1fbd81c64d98cc37610236cd934decf3223989ee3edf947c2e, but generation implementation changes from saved 442dc3ba7acbaa45e94ae74b2e1080bb602c56c4fd8a87d21a31f2e1a828723b to 97d458e5ad377b2b83764c6216aab18fa9e67364354f2ba9ba8934c0c9d9aeab. Strict native manifest equality prevents in-place resume; no metadata was changed and no recovery scientific job launched. Next resolve minimum valid stage reuse with genuine source identities; old report scripts also require a new owner receipt and cannot simply be rebound to a new dependency unchanged.

14:43 EDT: Replacement revision completed, but its detect subprocess1768792 has emptylog/noauditdir while original audit1746207 is active. This matches commands.py audit-study limiter and runtime audit_studies=1; replacement waits for the shared audit-study slot, not an unexplained provider stall. Shared active_provider_slots40 reflects original audit usage, not replacement-specific calls. No recorded replacement operation/HTTP failures.
