# Neutral heldout policy sensitivity

All trajectories, final artifacts, selected rubrics, S, A, and RH are reused.
Only H is recomputed using five fresh `uniform_neutral` heldouts.

## Sol + Gemini equal-weight mean

| Arm | Artifact | S | H rigorous-3 | S-H rigorous-3 | H neutral-5 | S-H neutral-5 | H change |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Full | saved Result40 | 50.50 | 39.83 | 10.67 | 43.00 | 7.50 | +3.17 |
| User | saved Result40 | 85.50 | 81.50 | 4.00 | 79.50 | 6.00 | -2.00 |
| Full | complete-public repair | 84.50 | 75.17 | 9.33 | 79.60 | 4.90 | +4.43 |
| User | complete-public repair | 68.00 | 56.17 | 11.83 | 62.10 | 5.90 | +5.93 |

## Per-model paired values

| Model | Arm | Artifact | S | H rigorous-3 | S-H rigorous-3 | H neutral-5 | S-H neutral-5 | H change |
| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| gpt-5.6-sol | Full | saved Result40 | 38.00 | 36.67 | 1.33 | 37.20 | 0.80 | +0.53 |
| gemini-3.8-flash | Full | saved Result40 | 63.00 | 43.00 | 20.00 | 48.80 | 14.20 | +5.80 |
| gpt-5.6-sol | User | saved Result40 | 76.00 | 76.00 | 0.00 | 76.00 | 0.00 | +0.00 |
| gemini-3.8-flash | User | saved Result40 | 95.00 | 87.00 | 8.00 | 83.00 | 12.00 | -4.00 |
| gpt-5.6-sol | Full | complete-public repair | 81.00 | 76.33 | 4.67 | 79.60 | 1.40 | +3.27 |
| gemini-3.8-flash | Full | complete-public repair | 88.00 | 74.00 | 14.00 | 79.60 | 8.40 | +5.60 |
| gpt-5.6-sol | User | complete-public repair | 62.00 | 42.33 | 19.67 | 52.60 | 9.40 | +10.27 |
| gemini-3.8-flash | User | complete-public repair | 74.00 | 70.00 | 4.00 | 71.60 | 2.40 | +1.60 |

## Interpretation

The bounded result supports a real prompt-policy mismatch. Across the eight
model-by-artifact pairs, neutral H is higher in six, unchanged in one, and lower
in one. On the two repaired artifacts, the equal-weight mean S-H falls from
`9.33` to `4.90` (Full) and from `11.83` to `5.90` (User). The largest paired
correction is repaired User under Sol: H rises `10.27` points and S-H falls from
`19.67` to `9.40`.

The conclusion is unchanged when heldout count is held fixed: using only neutral
variants 0/1/2, repaired Full S-H is `3.50` and repaired User is `6.50`, versus
rigorous-3 values `9.33` and `11.83`. The improvement therefore is not merely an
effect of averaging five instead of three paraphrases.

The old rigorous wording includes concrete boundary changes that can explain the
direction. Examples include changing “not implemented” to “not successfully
implemented,” changing additional translational evidence from “patient prevalence
or literature curation” to “patient prevalence and literature curation,” and
rewriting descriptive provenance conditions as absolute “must” requirements.
Those changes are small linguistically but can move an honestly incomplete answer
between rubric levels.

This is not a complete explanation of S-H. The original User/Gemini pair moves in
the wrong direction (`8.00` to `12.00`), and repaired neutral-5 still leaves S-H
near `5–6` in the two-model mean. Neutral variants also retain meaningful score
dispersion for the incomplete repaired User artifact. Thus the remaining gap
contains genuine task-completion disagreement and ordinary wording sensitivity;
it should not be erased by making heldouts lenient.

Job `10514937` completed five paraphrases and 40/40 Sol/Gemini judgments in 75
seconds with no errors and 233 MiB peak RSS at source `f19beea5c98f`. No revision,
solver, A, or RH call was made.
