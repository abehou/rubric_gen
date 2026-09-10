# Higher reasoning repairs arithmetic but loses one admission

Frozen26e464d; native preparation10377995, application10378006, report10378007. Nine contexts/57calls complete with zero failed attempts in93seconds Slurm elapsed; peakRSS135220KiB. Only Luna application reasoning low→high; all prompts, criteria, pair evidence, models and native gates unchanged. Reused fresh low-effort controls10377313 after exact request/candidate checks.

| Context | Low admissions | High admissions | Changed criterion–artifact levels |
|---|---:|---:|---:|
| da-10-1 rep-001 | 0 | 0 | 2/6 |
| da-10-1 rep-002 | 0 | 0 | 2/6 |
| da-10-1 rep-003 | 0 | 0 | 1/7 |
| da-10-3 rep-001 | 0 | 0 | 2/6 |
| da-10-3 rep-002 | 0 | 0 | 2/6 |
| da-10-3 rep-003 | 0 | 0 | 4/12 |
| da-12-2 rep-001 | 1 | 1 | 0/6 |
| da-12-2 rep-002 | 0 | 0 | 1/8 |
| da-15-1 rep-002 | 2 | 1 | 2/12 |

## Preidentified factual checks

- Mean/median contradiction repaired: artifact98cbccf0d975c69e is C and reason correctly computes mean0.632/median0.602 rather than claimed0.7072/0.7043. Consistent counterpart947b8f75dcde87ae remains A, avoiding the earlier numerical-prompt missing-proof regression.
- Universe/code contradiction retained at C for c6b08f8ca144fd01; consistent universe cases remain A. This correction was also present in fresh low-effort controls, so it is not a new advantage.
- Admission decreases from3criteria/two contexts to2criteria/two contexts. da12-2rep1 retains its admission; da15-1rep2 retains executable-validity but loses Effective low-expression filtering. A no-removal artifact8442669919b645a5 changes C→A; another artifact a9eaa02ddac1f735 changes B→A despite a previously alleged CPM implementation mismatch.

The filtering criterion's A level allows a defined/applied filter with removal counts, while C penalizes testing essentially all genes without an effective filter. The new rationale follows the stated filter without resolving this effectiveness tension. This is a criterion/application issue requiring artifact inspection, not grounds to alter gates or declare high reasoning superior.

The prospective no-admission-loss gate fails. Do not promote the high-effort setting or launch revisions. The arithmetic repair is a localized diagnostic success, not evidence of RH reduction or calibrated accuracy. Read-only job10378035 inspects the frozen filtering contrast before any further provider test. All null/adverse outcomes are retained; no BioMNIBench completion checkbox advances.
