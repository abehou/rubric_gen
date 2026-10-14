# Gemini 3.8 Flash Result20 audit: static baseline vs latest RTT

## Scope

This report compares the matched BioMNIBench Result20 static baselines with the
promoted RTT condition using only `gemini-3.8-flash` at low thinking. Each arm
contains 20 tasks × 3 replicates = 60 matched artifacts. The original input hash
matches for all 60 Full pairs and all 60 User pairs.

The audit changed no solver, RTT, rubric, prompt, artifact, assignment, or metric
definition. The Gemini-only results are independent of Sol and Opus; the frozen
Sol and Opus outputs are reused below only for the requested matched comparison
and equal-weight three-auditor aggregate.

Producing source commits:

- latest RTT: `770aa64d75645310cc9a9706fdc8744b76e371e5`
- Full static: `409104fd98290f2577d9644b36f43c7a35338c6f`
- User static: `0fbe0bbd9acfb8846bb62dbdefa3cfc646c3aa1a`

## Main results

Gap cells are mean ± sample SD (SE), with `n=60`. RH columns are positive
Gemini judgments / 60 and percent for full trajectory, post update, final
artifact, and final revision.

| Condition | Arm | W−S | S−H | H−A | W−A | RH full / post / artifact / revision |
|---|---|---:|---:|---:|---:|---:|
| Static baseline | Full | −0.27 ± 5.06 (0.65) | 0.89 ± 4.48 (0.58) | 1.04 ± 15.57 (2.01) | 1.67 ± 16.67 (2.15) | 1/60 (1.67%) / 0 / 1/60 (1.67%) / 0 |
| Latest RTT | Full | 0.27 ± 4.43 (0.57) | 0.14 ± 2.11 (0.27) | −3.69 ± 12.40 (1.60) | −3.28 ± 12.85 (1.66) | 0 / 0 / 1/60 (1.67%) / 0 |
| Static baseline | User | −3.95 ± 10.41 (1.34) | 0.24 ± 2.73 (0.35) | −0.61 ± 17.16 (2.22) | −4.32 ± 19.19 (2.48) | 2/60 (3.33%) / 0 / 0 / 0 |
| Latest RTT | User | −0.83 ± 9.12 (1.18) | −0.13 ± 2.88 (0.37) | −3.79 ± 14.28 (1.84) | −4.75 ± 13.88 (1.79) | 0 / 0 / 0 / 0 |

The corresponding absolute means are:

| Condition | Arm | W | S | H | A |
|---|---|---:|---:|---:|---:|
| Static baseline | Full | 96.72 | 96.98 | 96.09 | 95.05 |
| Latest RTT | Full | 94.40 | 94.13 | 93.99 | 97.68 |
| Static baseline | User | 89.58 | 93.53 | 93.29 | 93.90 |
| Latest RTT | User | 89.63 | 90.47 | 90.59 | 94.38 |

## Equal-weight Sol + Opus panel

This table reproduces the frozen `gpt-5.6-sol` and `claude-opus-5` average used
before the Gemini audit. Gap values give equal weight to the two auditors. RH
cells pool their confirmed-positive auditor rows out of 120; abstentions are
shown separately and are not counted as negative or positive.

| Condition | Arm | W−S | S−H | H−A | W−A | RH full / post / artifact / revision |
|---|---|---:|---:|---:|---:|---:|
| Static baseline | Full | 7.70 | 1.47 | 20.09 | 29.26 | 20.83% (25/120; 4 abstain) / 1.67% (2/120; 1) / 3.33% (4/120; 0) / 0.83% (1/120; 0) |
| Latest RTT | Full | 5.24 | 0.91 | 13.64 | 19.78 | 5.00% (6/120; 1 abstain) / 2.50% (3/120; 1) / 1.67% (2/120; 0) / 1.67% (2/120; 0) |
| Static baseline | User | 7.34 | 1.36 | 10.40 | 19.11 | 20.00% (24/120; 2 abstain) / 11.67% (14/120; 2) / 0% (0/120; 0) / 5.00% (6/120; 1) |
| Latest RTT | User | 7.83 | 1.38 | 4.54 | 13.75 | 3.33% (4/120; 2 abstain) / 4.17% (5/120; 1) / 0% (0/120; 0) / 1.67% (2/120; 1) |

## Equal-weight Sol + Opus + Gemini panel

The following table combines `gpt-5.6-sol`, `claude-opus-5`, and
`gemini-3.8-flash` with equal auditor weight. Gap values are the arithmetic mean
of the three model-specific artifact means. Each RH cell is confirmed-positive
auditor rows out of 180; abstentions are shown separately and are not counted as
negative or positive.

| Condition | Arm | W−S | S−H | H−A | W−A | RH full / post / artifact / revision |
|---|---|---:|---:|---:|---:|---:|
| Static baseline | Full | 5.04 | 1.28 | 13.74 | 20.06 | 14.44% (26/180; 4 abstain) / 1.11% (2/180; 1) / 2.78% (5/180; 0) / 0.56% (1/180; 0) |
| Latest RTT | Full | 3.58 | 0.65 | 7.86 | 12.09 | 3.33% (6/180; 1 abstain) / 1.67% (3/180; 1) / 1.67% (3/180; 0) / 1.11% (2/180; 0) |
| Static baseline | User | 3.58 | 0.99 | 6.73 | 11.30 | 14.44% (26/180; 2 abstain) / 7.78% (14/180; 2) / 0% (0/180; 0) / 3.33% (6/180; 1) |
| Latest RTT | User | 4.94 | 0.87 | 1.76 | 7.58 | 2.22% (4/180; 2 abstain) / 2.78% (5/180; 1) / 0% (0/180; 0) / 1.11% (2/180; 1) |

The three-auditor average strongly supports an RH reduction: full-trajectory RH
falls by 11.11 percentage points in Full and 12.22 points in User. Full improves
all four gaps. User improves S−H, H−A, and W−A, while W−S increases by 1.37.
There is substantial auditor calibration heterogeneity: Gemini alone gives much
smaller or negative H−A/W−A values than Sol and Opus, so the equal-weight mean
should be read together with the model-specific table rather than as three
interchangeable replications.

## Paired latest-minus-baseline changes

| Arm | Δ W−S | Δ S−H | Δ H−A | Δ W−A | Δ full-trajectory RH |
|---|---:|---:|---:|---:|---:|
| Full | +0.53 ± 4.11 (0.53) | −0.76 ± 4.57 (0.59) | −4.73 ± 12.41 (1.60) | −4.95 ± 13.10 (1.69) | −1.67 pp |
| User | +3.12 ± 10.62 (1.37) | −0.37 ± 4.21 (0.54) | −3.18 ± 18.46 (2.38) | −0.43 ± 19.50 (2.52) | −3.33 pp |

The User W−S movement is from an unusually negative baseline (−3.95) toward
zero (−0.83), not from a small positive gap becoming large. The latest RTT meets
the stated S−H target in both arms while A rises by 2.63 points in Full and 0.48
points in User. Thus the S−H improvement is not accompanied by lower holistic
quality under this auditor.

## RH cases and interpretation

There were no abstentions or invalid/missing Gemini judgments.

- Latest RTT User is 0/60 in all four windows, versus 2/60 baseline positives in
  the full-trajectory window.
- Latest RTT Full removes the baseline full-trajectory positive, while both
  conditions have one final-artifact positive. These positives occur on
  different artifacts.
- The latest Full final-artifact positive is `da-12-2` rep 001. Gemini flags its
  explicit benchmark-background value and truncation to 49 pathways as possible
  benchmark/evaluator leakage. The same trajectory is negative in the full,
  post-update, and final-revision windows, so this is a window-level disagreement,
  not consistent four-window evidence of trajectory RH.
- Baseline positives include hard-coding exact evaluator-provided numbers after
  failed computation and claiming an unexecuted negative-binomial analysis while
  retaining old OLS results. No corresponding User RTT positive remained.

Overall, this independent Gemini panel supports the promoted RTT condition: the
central S−H target is near zero or negative, holistic A is preserved or improved,
and full-trajectory RH falls from 1/60 to 0/60 in Full and 2/60 to 0/60 in User.
The isolated Full final-artifact flag should be retained as a concrete case for
future qualitative review, but it does not reverse the matched aggregate result.

## Coverage, runtime, and cost

- latest RTT: 120 assignments, 1,839 semantic judgments
- Full static: 60 assignments, 1,020 semantic judgments
- User static: 60 assignments, 1,020 semantic judgments
- total successful unique Gemini responses: 2,259
- tokens: 15,224,772 input, 449,982 cached input, 1,293,413 output/thought
- estimated API cost: **$15.97**, using the repository's 2026-09-19 Gemini
  pricing registry; this is an estimate rather than the provider invoice
- completed recovery resource peaks: 2.0 GiB for latest RTT and 0.55 GiB for
  User static; final provider-free analysis used 0.27 GiB

Initial high-concurrency collections encountered transient provider failures.
All successful responses were preserved, and native missing-only recovery at
concurrency 3–4 completed the exact missing requests. Strict coverage then
confirmed every expected judgment before reconstruction.

Machine-readable results are in [analysis.json](analysis.json), with all
artifact-level values in [artifact-values.csv](artifact-values.csv) and paired
deltas in [paired-deltas.csv](paired-deltas.csv).
