# BioMNIBench Original Result20 — current corrected results

Updated 2026-10-12. Eight conditions; each has 20 tasks × 3 replicates = 60 assignments. W/S/H/A and all four gaps are score points. RH reports only full trajectory and final artifact; confirmed-positive counts use all 60 assignments, with abstentions retained rather than relabeled negative.

These tables include the saved-evidence manual corrections documented below, not a new model-generated audit. Raw model judgments, revisions, rubrics, W/A and RH are unchanged. H remains the mean of the original three heldouts. Gaps are computed before rounding. No new provider calls were made for this review or publication.

The displayed RH windows use their original Sol/Opus judgments. Earlier Haiku fallback records for other, omitted windows retain their actual model provenance in the source history.

## gpt-5.6-sol

| Condition | W | S | H | A | W−S | S−H | H−A | W−A | RH full trajectory | RH final artifact |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| Full Static | 96.72 | 87.07 | 86.32 | 64.75 | 9.65 | 0.74 | 21.57 | 31.97 | 20.00% | 1.67% |
| Full RTT | 94.40 | 88.82 | 88.58 | 72.23 | 5.58 | 0.23 | 16.35 | 22.17 | 6.67% | 1.67% |
| User Static | 89.58 | 82.00 | 79.26 | 72.63 | 7.58 | 2.74 | 6.62 | 16.95 | 18.33% | 0.00% |
| User RTT | 89.63 | 80.65 | 80.14 | 79.50 | 8.98 | 0.51 | 0.64 | 10.13 | 5.00% | 0.00% |
| Semi Static | 81.70 | 69.08 | 67.30 | 79.27 | 12.62 | 1.78 | -11.97 | 2.43 | 6.67% | 0.00% |
| Semi RTT | 84.73 | 71.55 | 71.04 | 81.30 | 13.18 | 0.51 | -10.26 | 3.43 | 1.67% | 0.00% |
| Score-only Static | 63.42 | 52.53 | 51.28 | 82.58 | 10.88 | 1.26 | -31.31 | -19.17 | 10.00% | 0.00% |
| Score-only RTT | 71.50 | 62.87 | 62.54 | 81.00 | 8.63 | 0.33 | -18.46 | -9.50 | 1.67% | 0.00% |

Historical abstentions retained: Full Static: full 2, final 0.

## claude-opus-5

| Condition | W | S | H | A | W−S | S−H | H−A | W−A | RH full trajectory | RH final artifact |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| Full Static | 96.72 | 90.97 | 88.77 | 70.17 | 5.75 | 2.20 | 18.60 | 26.55 | 21.67% | 5.00% |
| Full RTT | 94.40 | 89.50 | 88.06 | 77.00 | 4.90 | 1.44 | 11.06 | 17.40 | 3.33% | 1.67% |
| User Static | 89.58 | 82.48 | 81.48 | 68.32 | 7.10 | 1.01 | 13.16 | 21.27 | 21.67% | 0.00% |
| User RTT | 89.63 | 82.12 | 81.06 | 72.27 | 7.52 | 1.06 | 8.79 | 17.37 | 1.67% | 0.00% |
| Semi Static | 81.70 | 72.22 | 71.18 | 80.85 | 9.48 | 1.04 | -9.67 | 0.85 | 6.67% | 0.00% |
| Semi RTT | 84.73 | 75.55 | 75.16 | 79.30 | 9.18 | 0.39 | -4.14 | 5.43 | 0.00% | 0.00% |
| Score-only Static | 63.42 | 57.75 | 55.92 | 80.97 | 5.67 | 1.83 | -25.05 | -17.55 | 3.33% | 0.00% |
| Score-only RTT | 71.50 | 65.30 | 64.94 | 77.35 | 6.20 | 0.36 | -12.41 | -5.85 | 0.00% | 0.00% |

Historical abstentions retained: Full Static: full 2, final 0; Full RTT: full 1, final 0; User Static: full 2, final 0; User RTT: full 2, final 0; Semi RTT: full 0, final 1.

## Evidence and reproducibility

- [Summary](summary.json), [all 960 corrected auditor rows](auditor-rows.json), and [raw pre-review rows](raw-auditor-rows.json).
- [All 102 cumulative criterion corrections](corrections.json), with original clauses/reasons, evidence excerpts and source locations; [latest 43 decisions](targeted-decisions.json), [prior first-pass decisions](first-pass-decisions.json), [prior second-pass decisions](second-pass-decisions.json).
- [Latest review verification](verification.json). Canonical User Static H was reconciled against the V2 pool actually used by the published table, not the older home audit pool.
- The other-machine aggregate values were not used as score targets. Changes are limited to the documented criterion decisions. Historical evaluation paths in JSON identify original retained outputs; they are provenance, not downloadable public files.
