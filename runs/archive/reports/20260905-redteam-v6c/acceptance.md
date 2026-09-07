# Acceptance v6c — complete after transport recovery

Verified 2026-09-05 13:40 CST. Four development revision assignments are complete,
and all **153/153 semantic audit judgments** are present across Sol, Claude Opus 5
and Gemini 3.8 Flash. This is operational acceptance on da-18-1, not Results20
outcome evidence or a test of the scientific hypotheses.

| Stage | Judgments | Final missing/failed |
|---|---:|---:|
| Direct full trajectory | 12 | 0 |
| Direct post-update | 12 | 0 |
| Direct final artifact | 12 | 0 |
| Direct final revision | 12 | 0 |
| Rubric score | 78 | 0 |
| Rubric-free absolute | 15 | 0 |
| Pairwise preference | 12 | 0 |

The private read-only coverage checker verified exact assignment/model coverage,
unique direct records and their saved completed score files, no excluded assignments,
complete model panels, and equality of planned/successful/used semantic counts.
All 48 direct judgments returned no RH detected, with no abstentions; this tiny
development check is not a comparative Results20 finding.

The first v6c attempt (13:25–13:33, concurrency 6) completed 136/153 judgments,
with 17 Gemini failures. It was archived before supported serial resume at 13:35:36,
which completed at about 13:40 with exit 0. Previously completed judgments were
reused by the normal current-format validator; failures were retried, not relabeled
or dropped. The completed coverage does not establish that intermittent physical
network problems have disappeared.

- First-attempt archive:
  `runs/provenance/20260905-redteam-v6c/acceptance-audit-first-attempt-20260905-1340.tar.gz`
  (filename stamp is nominal; actual archive/start time was 13:35 CST), SHA-256
  `390541150b1d135cedcdc476942123c95f59227c0dbd20c1244d68c2f3b9fdf5`.
- Resume log:
  `runs/logs/biomni-redteam-acceptance-v6c-audit-resume-c1-20260905-1340.log`.
- Source revisions:
  `runs/preflights/exact-newlines-v6b/biomnibench-da-factorial-r3-b07888ff76df`.
- Complete audit:
  `runs/preflight-detections/gemini-transport-v6c/biomnibench-da-factorial-r3-b07888ff76df`.

During serial audit recovery only the independent solver adapter and its unit test
changed for v6d headless plotting; all frozen v6c audit source files and all three
rubric/direct/score implementation hashes remain unchanged. The four completed
revision trajectories were not modified or rerun. The formal study uses a new v6d
namespace and source archive, not a relabeling of this acceptance run.
