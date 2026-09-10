# Canonical data resolves the lost filtering contrast

Read-only job10378062 completed in4seconds. The original Results20 count file matches the canonical45 download receipt SHA256: `3de7312579e44e3f4f6edb4d7519eb95cf0d2287fd688a07a58d892b837ec0e5`. Neither dataset nor any experiment output was modified.

Using all174 sample columns and all58,884genes, the displayed library-size CPM calculation retains:

| Rule | Canonical retained genes | Artifact claim |
|---|---:|---:|
| CPM≥1 in at least10samples |18,940|18,940 (6871a95fd2755c8f) |
| CPM≥1 in at least20samples |18,294|58,884 (8442669919b645a5) |

Library sizes also match the artifact descriptions (9,412,639.84–66,761,183.42). The second artifact's no-removal output is false for the named canonical input. The high-reasoning application credits its declared filtering procedure without resolving the false output; its lost admission is not evidence that the original contrast had no factual basis.

Read-only inspection10378035 additionally shows that f85bcdd9c4ed261e and a9eaa02ddac1f735 have identical filtering code: the only artifact difference is final reported differential-gene counts. That code uses `norm*1e6 > 1` without library-total division. Low reasoning grades these identical filters A/B; high grades both A. Agreement alone therefore does not establish correct application.

Interpretation: higher reasoning repairs the simple table-summary contradiction but does not reliably validate claims against code/data. This criterion also has overlapping descriptors: A credits a specified/applied filter and reported removal count, while C penalizes essentially-all-gene testing without effective filtering. Raw-data execution resolves this particular case, but the application provider did not receive the raw matrix; do not call the numerical check a model-accessible proof or silently inject it into frozen grading.

Stop the high-reasoning candidate under its prospective no-admission-loss gate. Before another provider test, distinguish a general application instruction that follows code/requirement evidence from a change that grants new data-execution tools. Do not add a universal positive-removal requirement merely to admit this criterion, weaken native gates, or alter historical scores. This is a development mechanism case, not an RH outcome or human calibration label.
