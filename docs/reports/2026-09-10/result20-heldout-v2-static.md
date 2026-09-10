# Result20 heldout V2 static baseline

The approved zero-fallback V2 paraphrase prompt regenerated all 471 heldout
wording units. The run used the Result20 20-task dataset, with 60 assignments
for each static condition and heldout rubric scoring only. Frozen seeds,
submissions, validators, auditors, and the original selected/development
variants were reused.

| Condition | H | S−H | H−A |
|---|---:|---:|---:|
| Full feedback static | 87.544 | 1.472 | 20.086 |
| User simulator static | 80.878 | 1.364 | 10.403 |

The User simulator S−H gap is positive and provides a healthy static baseline
for subsequent comparisons.
