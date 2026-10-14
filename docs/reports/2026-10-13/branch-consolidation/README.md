# Branch consolidation — 2026-10-13

GitHub keeps three branches: `main`, `codex/healthbench-researchqa`, and `codex/biomnibench-results`. The consolidated branch starts from the complete corrected Result40 publication `e5d27c8`; current score rows, tables, corrections and actual model provenance are retained exactly.

Completed at23:39 PDT: all nine obsolete remote branches were deleted after publication and ancestry verification. GitHub now exposes exactly the three branches above; main and HealthBench/ResearchQA heads are unchanged. Consolidation commit `1a6e59e4959c0a59b3d82df069ef24db04b68a43` preserves every retired tip.

The consolidation merge preserves every retired branch tip as an ancestor. Useful saved reports, figures and experiment configurations are materialized in their existing directories; competing files use the most recent recorded update. Runtime source and tests remain identical to the Result40 publication. Historical alternative runtime implementations are accessible at the source commits below, rather than silently changing the current scientific method.

| Retired branch | Preserved tip | Content retained |
|---|---|---|
| aydan-red-team | `bacb280241e05601e34d3c43dccb638fbace85ff` | Already contained in Result40 history |
| aydan-red-team-dropout | `b3b0727dec051845a7427f7a75a9b8c3cd2d94fc` | Phase1 report and implementation history |
| codex/harvey-rtt-dev3 | `c648c9e1f4618a4c5ee7e887ba992ad0fe542909` | Harvey harness, configurations, smoke script and source history |
| codex/result40-development-gap-diagnostic | `bd2c764c424699d0bc7489cd7f4c816f2f60b736` | Development-gap diagnostic reports/data/configurations |
| codex/result40-rtt-gap-improvement-pilot | `e09f5fcadcbe6e3824199710349859912fe985dc` | Pilot configurations, recovery scripts and source history |
| codex/trace-v21-complete-public-regression | `e1367c348b3e590744b58cd9e795ba07922abd56` | Heldout and execution analyses, configurations and source history |
| codex/trace-v21-provenance-result20-babel | `f6a0ac8fa6c7f95afedf7152c90883e7ebd1c733` | Original20 figures/evidence and completed PaperBench RTT Dev3 report |
| codex/trace-v21-provenance-result40-babel | `e5d27c8e9a2bbae8d884fa3da7dcb04b0feb156e` | Current complete Result40 publication and all earlier history |
| codex/trace-v21-result50-babel | `bcc353c4d44304958e4effeb4f53ebe91d2ea2ba` | Result50 extension configurations and source history |

[Exact imported paths and original versions](inventory.json) · [Benchmark result index](../../../benchmark-results.md).

BioMNIBench-only dropout/Gemini reports from the retained HealthBench/ResearchQA branch are also available here. Two completed/development PaperBench reports were collected from the existing local integration checkout. Existing Mac/Babel working directories, saved runs and uncommitted changes are retained; branch deletion removes only the obsolete GitHub branch references, and the listed commits remain recoverable from this branch's history.
