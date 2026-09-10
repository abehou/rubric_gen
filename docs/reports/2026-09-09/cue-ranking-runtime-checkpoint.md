# Ranking-preservation Result20 runtime checkpoint

Verified 2026-09-09 10:55 EDT. Job10371501 remains owned by the frozen trace-only launch; reports10371512 and10371561 depend on its completion. This is an interim runtime report, not a scientific result.

- Latest telemetry elapsed: 15.9minutes; assignment states: {'running': 60}.
- Active provider slots: 58; configured shared aggregate ceiling60.
- Sampled CPU: 2.40cores of4requested.
- Peak cgroup memory: 39.47GiB; request128GiB. Summed process RSS can double-count shared pages and is not substituted for cgroup memory.
- Available monitored filesystem space: 13.93GiB; monitor continued growth.
- HTTP failure counts: {}; call-level operation failure counts (may recover): {'APITimeoutError': 1}.
- Runtime events, including retries, are enumerated below. One earlier solver retry was specifically app-server startup, not a reported HTTP429.

```json
{
  "acquired:": 989,
  "api_retry:solver": 1,
  "operation_completed:evolution-generation": 377,
  "operation_completed:hosted-generation": 133,
  "operation_completed:optimizer-judge": 246,
  "operation_completed:solver-resume": 61,
  "operation_completed:solver-turn": 112,
  "operation_failed:evolution-generation": 1,
  "released:": 930
}
```

Saved treatment-integrity check found60offline evolution records without the new online rule and7completed online records with preserve_positive_rank. That verifies routing in those saved records, not successful mitigation. Keep current execution unchanged while checkpoint progress continues; no outcome-based early stopping.

Next: require all60assignments and full frozen two-auditor coverage, then run the queued report and joint/exposure analysis. No30/45scale-up until all scientific requirements are met.

## 10:56 EDT — recovered transient timeout

An evolution-generation call failed with APITimeoutError after300.25seconds; the same telemetry request key subsequently completed in14.77seconds, about21seconds after the failure event. This is a recovered call failure, not a terminal assignment failure or HTTP429. No restart, configuration change or new recovery job was needed.

## 11:20 EDT — 23/60 revisions complete

Job10371501 remains RUNNING at40minutes;23completed/37running assignments,42active provider slots. All three recorded300second evolution APITimeoutError requests have subsequent same-key successful completions,20.96/9.46/16.60seconds after the failure events. No HTTP status failures recorded; no manual recovery. Both10371512 and10371561 remain dependency-pending.

## 11:55 EDT — late revision checkpoint

Owned10371501 remains running; latest states {'completed': 54, 'running': 6}, activeprovider slots6, activeauditstudies0. Report10371512 and joint/exposure10371561 remain dependency-pending. All30recorded call failures had same-key success at the preceding recovery check; monitor new events separately. No treatment/runtime changes or recovery submission.
