# V6d Results20 — stopped for connection-induced rubric fallback

Status verified 2026-09-05 14:10 CST. **Not a complete or clean formal outcome run.**
No formal outcome audit has started, and no RH comparison is reported from this
partial dataset.

## Final scope and retained progress

- Configured: 240 assignments, all 20 tasks × 3 replicates × 4 conditions.
- At the confirmed 14:07:04 stop: 18 completed, 30 interrupted, 192 pending.
- Of the 18 completed assignments, 16 contain at least one connection-induced
  rubric fallback. Only the first two completed assignments are unaffected by
  this incident; do not cherry-pick them as the new formal study.
- Total: 78 online rubric generations, 10 admitted criteria, 84 retried stages,
  21 fallback generations across 21 assignments, 34 fallback stages (all recorded
  as `Connection error.`), and 82 included red-team sidecars.
- Twenty shared pretreatment generations had four admitted criteria and no fallback.
- The existing `study.json` says running for interrupted work; process/session
  termination is authoritative. No active full-study process remains.

## Intervention chronology

1. Attempt 1 began 13:41:15 at concurrency 30. Native samples later identified
   system-NumPy OpenBLAS thread oversubscription and persistent SDK PATH drift.
2. Its controller 94199 and 123-process tree stopped at 13:55:26, preserving two
   completed assignments and scored checkpoints. One simulator connection error
   occurred before this stop; CPU causation was not established.
3. Runtime-only attempt 2 began 14:00:20, session 90781, after 735 regressions and
   a real child-runtime check. The original two assignments' 378 files were verified
   unchanged. Initial CPU idle recovered to 53%, compressed memory to about 4.2 GiB.
4. Monitoring at 14:03 found 21 new fallback generations, even though assignment
   completion counts were increasing. Provider failures were not healthy progress.
5. A first stop targeted PID 953 at 14:05:09; subsequent process verification showed
   that it was the caffeinate helper, not the Python controller. Its eight reported
   descriptor fields therefore do not diagnose the controller's descriptor usage.
6. Actual Python controller **951** and 106 owned processes were stopped at
   **14:07:04**; no live descendants remained and session 90781 exited **143**.
   The earlier 14:05 ledger snapshot is not the terminal snapshot.
7. An independent, minimal call through the actual Luna proposer client passed in
   3.09s after stopping. This establishes momentary connectivity, not the cause of
   historical failures or readiness for another large run.

## Defect and next gate

`RubricProposer._stage` catches provider-call exceptions and eventually emits a
fallback generation. The study circuit only counts Codex session health exceptions,
so hosted proposer failures can silently change effective rubric treatment while
assignments still finish. The next implementation must fail an unavailable-provider
generation without publication, preserve enough diagnostic context, and reach the
study's bounded circuit/recovery workflow. Invalid model response handling is a
separate protocol decision and must not be conflated with connectivity.

This fix is **not yet implemented**. No credential, proxy or model was changed.
Do not overwrite sealed fallback generations, claim all eighteen assignments are
clean, relax implementation hashes, or splice selected results into a new-version
study. A changed generation implementation must produce valid new-format artifacts.

## Evidence

- Terminal ledger: `runs/provenance/20260905-redteam-v6d/attempt-02/study-after-confirmed-stop-20260905-1407.json`.
- Whole terminal study archive: `runs/provenance/20260905-redteam-v6d/attempt-02/study-after-network-stop-20260905-1407.tar.gz`.
  SHA-256: `6c9823e2e812658a260206a0be80c371f83d22035eb2f2bc44be0b4b3ba7d3e9`.
- Attempt log: `runs/logs/results20-v6d-attempt02-revise-c30-20260905-1400.log`.
- Both source epochs and earlier interruption archives remain in
  `runs/provenance/20260905-redteam-v6d/`.
