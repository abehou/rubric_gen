# Acceptance v6b — revision passed, audit incomplete

**13:25 CST update:** this is the preserved first-attempt report, not a current
running status. Recovery reached 148/153 summarized judgments; an observed run
saved two more pairwise records but exposed an IncompleteRead retry bypass before
summary completion. Gemini transport handling and audit identity coverage are now
repaired in separate version v6c. Its fresh audit reuses the four unchanged, valid
Luna revision trajectories and regenerates all judgments; v6b audit outputs remain
historical and are not relabeled. See the v6c provenance ledger for current execution.

Status at 2026-09-05 13:14 CST: **not cleared for the full Results20 run**.
The acceptance workflow exited 1; no experiment process remains active.

## Scope and verified revision behavior

One development task (`da-18-1`), rep-001, all four full/user-simulator × red-team
artifact/trace conditions, minimum/maximum three solver turns. This is not a
Results20 outcome dataset and must not be mixed into its 240 assignments.

- Four of four revision assignments completed; revision phase took 14m37s after
  shared preparation. Three assignments stopped on an unchanged third turn and
  therefore have two distinct revised snapshots; one has three changed snapshots.
- Five online rubric generations and five included red-team sidecars sealed.
  All five generations had zero stage retries and zero fallback; one criterion
  was admitted. That generation exercised all five proposer stages successfully.
- All 13 installed assignment-generation manifests passed current-format loading
  and integrity checks. The 195 frozen source/config files still matched the archive
  at 13:13 CST; no source change was made during execution.
- Regression: 724 tests passed, with the two known unrelated Harvey/MALT environment
  exclusions. New tests cover exact LF/CRLF/CR/mixed-newline publication, replay,
  shared installation/reinstallation under all eligible policies, and tamper rejection.
- No actual CR-containing raw response was observed in this small live run. The
  newline defect is established by controlled reproduction/regressions, not by
  recovery of the v5 failed response bytes, which are unavailable.

## Audit coverage — first attempt

| Stage | Planned semantic judgments | Successful | Failed |
|---|---:|---:|---:|
| Direct full trajectory | 12 | 10 | 2 |
| Direct post-update | 12 | 8 | 4 |
| Direct final artifact | 12 | 8 | 4 |
| Direct final revision | 12 | 8 | 4 |
| Rubric score | 78 | 67 | 11 |
| Rubric-free absolute | 15 | 10 | 5 |
| Pairwise preference | 12 | 8 | 4 |
| **Total** | **153** | **119** | **34** |

Sol and Claude Opus 5 each completed all 51 planned judgments. Gemini 3.8 Flash
completed 17/51, accounting for all 34 failed judgments. Progress-bar totals count
processed failures too; they do not establish successful coverage. Successful
semantic requests may serve several assignment/rubric references and are counted
only once in this table.

Direct failures report TLS unexpected EOF. Rubric-score attempt evidence contains
47 TLS-EOF failures plus one other APIConnectionError attempt (attempts are not the
same as failed semantic judgments; some recovered). Unauthenticated urllib/HTTPX
checks and a minimal single Gemini structured request failed through the configured
proxy, while Google web, OpenAI and Anthropic HTTPS probes reached HTTP responses.
Three further unauthenticated Gemini checks at 13:13–13:14 also failed.

These observations identify a connectivity gate, not an established invalid-key
diagnosis or a proven Google-wide outage. Do not weaken TLS verification, change
models, alter outcome rules, or substitute two-provider means. The acceptance RH
comparison remains incomplete and is not evidence for the desired scientific direction.

## Preserved evidence and recovery

- Study: `runs/preflights/exact-newlines-v6b/biomnibench-da-factorial-r3-b07888ff76df`.
- Audit: `runs/preflight-detections/exact-newlines-v6b/biomnibench-da-factorial-r3-b07888ff76df`.
- Log: `runs/logs/biomni-redteam-acceptance-v6b-20260905-1251.log`.
- Source and incident archive: `runs/provenance/20260905-redteam-v6b/`.
- The complete first-attempt audit was archived before any resume as
  `acceptance-audit-first-attempt-20260905-1312.tar.gz`, SHA-256
  `3b1e3d53c7d0c1d6c732f0ac45fd37c5ec03cc47d9b75c48f6f80f47e767b222`.

After Gemini connectivity recovers, run the existing audit-only workflow with
`detect --experiment experiments/preflights/biomnibench-elicitation-10.yaml
--resume --max-concurrency 6`. It validates/reuses completed judgments and retries
missing ones; do not regenerate the four completed revisions or edit old identities.
Use the private read-only `runs/diagnostics/check_audit_coverage.py` to verify all
seven stages and exact provider/assignment coverage, followed by a new dated report.

The formal v6b 240-assignment experiment has not started. Its five-turn minimum /
ten-turn maximum, task set, models and four conditions remain unchanged. Initial
revision concurrency remains 30, with 40 only a candidate after sustained resource
evidence; no hard overall deadline is imposed.
