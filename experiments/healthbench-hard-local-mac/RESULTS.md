# HealthBench Hard local Dev3 — 2026-09-25

Completed 14:28 PDT. Main invocation: `20260925T211220Z`, runtime source
`b89b638ba80338104d618ce90f472f4315a6aefe`, study
`healthbench-hard-factorial-r3-d189fa58c2f7`.

## Scope and coverage

All experiment roles use `gpt-5.6-luna`; the supplied OpenAI credential ending
`IfoA` was verified with a successful API call. No Anthropic/Gemini credentials
were passed. Official HealthBench Hard inputs are in
`data/healthbench-hard/live-dev3-20260925-v2`.

| Condition | Completed / planned |
| --- | ---: |
| Full × Static | 9 / 9 |
| User simulator × Static | 9 / 9 |
| Full × Red-team trace | 9 / 9 |
| User simulator × Red-team trace | 9 / 9 |

All 36 assignments executed three revision turns. Twenty saved four distinct
answer snapshots (including initial); sixteen saved three because the third
turn made no answer change. Every referenced answer snapshot is present.
Among 18 red-team assignments, 13 changed the active rubric at least once;
there were 20 changed-rubric transitions in total. Five retained their rubric.

| Audit | Successful / planned unique judgments |
| --- | ---: |
| Rubric score | 148 / 148 |
| Rubric-free absolute score | 45 / 45 |
| Pairwise preference | 36 / 36 |
| RH: full trajectory | 36 / 36 |
| RH: post-update | 36 / 36 |
| RH: final revision | 36 / 36 |
| RH: final artifact | 36 / 36 |

All seven stages completed, with no missing model or failed judgment. Shared
initial artifacts are deduplicated in the unique judgment counts. All four
RH windows yielded 0/36 positive detections and no abstentions. This is an
exploratory small-sample, same-Luna audit, not evidence that RH is absent or
that a stronger independent panel would agree. Project rubric scores are not
an official HealthBench leaderboard evaluation.

## Runtime and cost

Main execution lasted about 15m48s including preparation and final audits;
the revision stage lasted 12m47s. Mac profile: outer queue 1, assignment workers
6, aggregate OpenAI cap 12, internal fanout 4, audit workers 12, 12-core/24-GiB
host. Completed end-to-end smoke preceded scaling.

Saved usage estimate for the main run: **6,445,542 input tokens** (including
3,563,712 cache reads and 1,691,610 cache writes), **242,874 output tokens**, and
**$1.023670**. Including both smoke attempts with usage, the recorded total is
approximately **$1.10**. The tiny authentication probe is immaterial at this
precision. These are estimates, not billing statements; unreported failed-call
usage is excluded. The read-only `usage_snapshot.py` deduplicates hosted response
IDs and cumulative Codex thread usage across saved copies, using Luna standard
short-context rates: $0.20 input / $0.02 cached / $0.25 cache-write / $1.20 output
per million tokens.

## Evidence

Persistent root: `runs/healthbench-hard-local-mac-20260925-v2/`.

- Main receipt: `invocations/20260925T211220Z/receipt.json` (all four CLI stages exit 0).
- Study: `studies/healthbench-hard-factorial-r3-d189fa58c2f7/study.json`.
- Audits: `audits/healthbench-hard-factorial-r3-d189fa58c2f7/` (seven summaries).
- Smoke: `smoke/invocations/20260925T210750Z/receipt.json`.

Runtime fixes published before main execution: signed HealthBench level ordering
(`1ee9e12a`) and explicit isolated Codex app-server API login (`b89b638b`).
The latter passed 15 focused SDK tests; a separate socket-proxy unit test timed
out on this host and remains tracked in CODE_REVIEW.md. Real end-to-end proxy,
authentication, revision, and audit execution passed. Earlier failed attempts
remain preserved; no historical results or unrelated workspace edits were removed.
