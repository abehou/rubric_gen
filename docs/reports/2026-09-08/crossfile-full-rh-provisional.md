# Crossfile full-trajectory RH: provisional stage result

All60 cases have saved full-trajectory records from both auditors (59original +1repair). This is a completed-stage summary, not a fully validated end-to-end result; other audits and the primary native coverage gate are pending.

| Auditor | Confirmed RH /60 | Abstain /60 | RH identification bounds |
|---|---:|---:|---:|
| claude-opus-5 | 7 | 1 | 11.67–13.33% |
| gpt-5.6-sol | 7 | 2 | 11.67–15.00% |

Equal-auditor confirmed RH11.67%, versus priortrace7.50% and static20.00%. The candidate does not improve the priortrace point estimate; no uncertainty or quality conclusion yet. Starting learned rubrics differ on10/20tasks, so do not attribute this contrast solely to the sidecar prompt. Retain the result regardless of the final direction.

## Source summaries

```json
[
  {
    "path": "runs/babel-result20-crossfile-consistency-20260908/trace/audit/biomnibench-da-factorial-r10-f0203f5d69f3/direct_full_trajectory/evaluations/20260909-002336-261156--ensemble--detect-rh--experiment-biomnibench-da-factorial-r10-f0203f5d69f3--source-biomnibench-da-factorial-r10-f0203f5d69f3--window-full_trajectory--max-input-250000--max-output-4096--primary-any_detect/summary.json",
    "sha256": "e1b056ea41e874fc82a2bc1a2f29b6f8330935c96f8b4ef92b08d633ffb79694"
  },
  {
    "path": "runs/babel-result20-crossfile-pair-repair-20260908/trace/audit/biomnibench-da-factorial-r10-f0203f5d69f3/direct_full_trajectory/evaluations/20260908-235808-372511--ensemble--detect-rh--experiment-biomnibench-da-factorial-r10-f0203f5d69f3--source-biomnibench-da-factorial-r10-f0203f5d69f3--window-full_trajectory--max-input-250000--max-output-4096--primary-any_detect/summary.json",
    "sha256": "9b76221b0d51f3107b94c2ed2c0b19d209e64bde7c14f70929df4848af509bc0"
  }
]
```

## Remaining direct windows completed (provisional)

Each window has120 completed auditor records across the same60 cases. All-stage native coverage and quality/gap audits remain pending.

| Window | Sol positive / abstain | Opus positive / abstain | Equal-auditor confirmed RH |
|---|---:|---:|---:|
| Post-update |5/2|3/4|6.67%|
| Final artifact |0/0|0/0|0.00%|
| Final revision |0/0|0/0|0.00%|

Each auditor denominator is60. Priortrace post-update8.33% and final-revision1.67% point estimates are higher, whereas its full-trajectory7.5% is lower. Final-artifact remains0% across controls and candidate. This is mixed endpoint evidence, not uniform policy improvement; wait for quality and paired uncertainty before choosing the next condition.
