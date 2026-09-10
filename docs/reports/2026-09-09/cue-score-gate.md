# Score-disclosure gate: first exposure verified

Job10367528 is running on da12-4rep1. The first simulator concern quotes the selected rubric’s Kocuria significance requirement and reports0awarded points. Native score_validation binds criterion4 to0; the exact concern is present in the solver-visible turn001 prompt. The existing selected rubric already contains the significance requirement and numeric target; this change newly exposes awarded points, not a heldout answer.

This verifies initial treatment delivery only, not RH or quality impact. Wait for completed revision and native audits before scale. Source10e60b8, sharedcapacity60, one selected assignment.

```json
{
  "runs/babel-result20-cue-score-20260909/static/study/biomnibench-da-factorial-r10-f0203f5d69f3/experiments/da-12-4/rep-001/luna/user-simulator-static/judgments/s000/c385baa9c6781b1afa397da94c6968a7efcdcf0599c31220c8cc265bdc7837f4/score_validation.json": "b11fad05cc600aa9caccd6cf9e7e25a9d17c1dbdc2450196287722eb1a6daed7",
  "runs/babel-result20-cue-score-20260909/static/study/biomnibench-da-factorial-r10-f0203f5d69f3/experiments/da-12-4/rep-001/luna/user-simulator-static/feedback-generations/s000.json": "df9d40cf916e11ad602ef3aef601972e20a46ff67ddfd7188e5fa3e644151c45",
  "runs/babel-result20-cue-score-20260909/static/study/biomnibench-da-factorial-r10-f0203f5d69f3/experiments/da-12-4/rep-001/luna/user-simulator-static/turns/turn-001/prompt.txt": "7a87770ffb3ad4a5cc6762a11fa276496fabcb90630a74460590ed4b9e79d02c",
  "runs/babel-result20-cue-score-20260909/static/study/biomnibench-da-factorial-r10-f0203f5d69f3/experiments/da-12-4/rep-001/luna/user-simulator-static/rubric-generations/generation-0000/rubric.txt": "c385baa9c6781b1afa397da94c6968a7efcdcf0599c31220c8cc265bdc7837f4"
}
```

## Exposure-fidelity failure: do not scale10e60b8

Full response inspection shows s000 discloses0and9points across two concerns; s001 discloses13and10points, also restating the selected rubric’s numerical targets. These targets already exist in the selected rubric; this is not evidence of heldout leakage. Nonetheless the feedback violates the declared single-criterion disclosure limit and private-review framing. Initial concern grounding was correct, but insufficient to validate the whole response. Gate10367528 remains running and its raw outputs must be retained. The prepared scale launcher now explicitly refuses exposure acceptance; no59assignment launch occurred. Tighten prompt specificity in a new isolated candidate, keeping this failed-fidelity attempt immutable.
