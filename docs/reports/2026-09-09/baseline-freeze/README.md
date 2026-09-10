# BioMNIBench frozen baseline — available Result20 results

Formal feedback conditions are **Full feedback** and **User simulator**. Policies are **Static rubric** and **Red-team trace**. The baseline is accepted; joint trace mitigation has not yet been established. No new revisions or audits were run for this checkpoint.

20 frozen tasks, three planned replicates; Sol/Opus equal-weight per-auditor means. The two static arms and User simulator trace each have60/60 assignments. Full feedback trace has59/60: da-16-1 replicate1 failed an infrastructure invariant; its cancelled repair contributes nothing. Static60 remains the canonical baseline; inferential Full feedback comparisons use only the matching59 in each arm.

| Condition | Policy | n | Trajectory RH | Artifact RH* | W | W_train | S | H | A | W−S | S−H | H−A | W−A |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| Full feedback | Static rubric | 60 | 20.83% | 3.33% | 96.72 | 96.72 | 89.02 | 87.52 | 67.46 | 7.70 | 1.50 | 20.06 | 29.26 |
| User simulator | Static rubric | 60 | 20.00% | 0.00% | 89.58 | 89.58 | 82.24 | 82.12 | 70.47 | 7.34 | 0.12 | 11.65 | 19.11 |
| Full feedback | Red-team trace | 59 | 26.27% | 3.39% | 95.54 | 95.37 | 87.56 | 87.01 | 65.40 | 7.98 | 0.55 | 21.61 | 30.14 |
| User simulator | Red-team trace | 60 | 7.50% | 0.00% | 91.97 | 91.63 | 82.70 | 82.78 | 70.97 | 9.27 | -0.08 | 11.81 | 20.99 |

*Final-artifact rates use the unchanged, uncalibrated auditor. They are a measurement-sensitivity limitation, not proof of absent artifact RH. Threshold remains >5;5 is abstention. Gemini3.8 Flash is configured but has no results because credits were unavailable.

## Interpretation

Both static arms have accepted trajectory-RH headroom and W−S, H−A, W−A gaps. User simulator S−H≈0.12 is consistent with wording-only heldout generalization; it is not a baseline failure. The0.83percentage-point Full feedback/User simulator trajectory difference is descriptive, not demonstrated separation.

User simulator trace reduces trajectory RH20%→7.5% (paired task95% interval for change−22.50 to−4.17pp), but W−S and W−A increase by1.925 and1.883points. Holistic change+0.50 has95% interval[−3.19,+4.12]; no demonstrated loss is not proven noninferiority.

Full feedback trace is a provisional59-case comparison: trajectory change+5.08pp, W−S+0.47, W−A+0.87, A−1.99 versus the matched static59. Task-equal95% intervals respectively[−4.17,+14.17]pp,[−2.05,+2.87],[−2.48,+4.35],[−5.30,+1.38]. These do not establish mitigation or conclusive harm. See the [matched coverage/provenance record](../cue-full-provisional59.md).

## Audit coverage and bounds

Rates below are confirmed per-auditor rates; brackets extend to include abstentions, not confidence intervals. Panel union is separately labeled.

| Condition / policy | Window | Confirmed–upper (%) | Panel union–upper (%) | Auditor disagreements | Mean monitor score |
|---|---|---:|---:|---:|---:|
| Full feedback / Static rubric | full trajectory | 20.83–24.17 | 25.00–26.67 | 5 | 2.82 |
| Full feedback / Static rubric | post update | 1.67–2.50 | 3.33–5.00 | 3 | 0.83 |
| Full feedback / Static rubric | final artifact | 3.33–3.33 | 6.67–6.67 | 4 | 1.05 |
| Full feedback / Static rubric | final revision | 0.83–0.83 | 1.67–1.67 | 1 | 0.71 |
| User simulator / Static rubric | full trajectory | 20.00–21.67 | 28.33–30.00 | 11 | 2.50 |
| User simulator / Static rubric | post update | 11.67–13.33 | 15.00–16.67 | 5 | 1.85 |
| User simulator / Static rubric | final artifact | 0.00–0.00 | 0.00–0.00 | 0 | 0.72 |
| User simulator / Static rubric | final revision | 5.00–5.83 | 6.67–8.33 | 3 | 1.04 |
| Full feedback / Red-team trace | full trajectory | 26.27–29.66 | 30.51–32.20 | 6 | 3.31 |
| Full feedback / Red-team trace | post update | 3.39–3.39 | 3.39–3.39 | 0 | 1.03 |
| Full feedback / Red-team trace | final artifact | 3.39–5.08 | 5.08–8.47 | 4 | 1.09 |
| Full feedback / Red-team trace | final revision | 3.39–4.24 | 5.08–6.78 | 3 | 0.95 |
| User simulator / Red-team trace | full trajectory | 7.50–10.83 | 10.00–15.00 | 6 | 1.72 |
| User simulator / Red-team trace | post update | 8.33–11.67 | 13.33–16.67 | 7 | 1.42 |
| User simulator / Red-team trace | final artifact | 0.00–0.00 | 0.00–0.00 | 0 | 0.72 |
| User simulator / Red-team trace | final revision | 1.67–4.17 | 1.67–6.67 | 3 | 0.67 |

[Machine-readable results, existing paired uncertainty, auditor counts, monitor histograms and source hashes](results.json) · [Case metrics](case-metrics.csv) · [Gap/artifact plot](gaps-and-artifact-rh.png) · [Trajectory plot](trajectory-rh.png).

Internal provenance only: revised simulator version `rubric-cue`, scientific source0fbe0bb, Full feedback trace producer314ea3d. This release adds the approved30ae38e duplicate-evidence fix; it does not relabel earlier results as produced with that fix. [Field/hash compatibility decision](../cue-full-compatibility.md).

The approved zero-fallback Result20 heldout V2 static baseline regenerated all 471 wording units. See the [heldout V2 static result](../../2026-09-10/result20-heldout-v2-static.md); the User simulator S−H gap is now a healthy positive baseline.
