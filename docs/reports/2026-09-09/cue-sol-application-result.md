# Application model comparison: no admission advantage for Sol

Completed 17:22 EDT. Job10377313 / report10377314, frozen abcb8c1. All18cells and114calls completed with0failed attempts in82seconds; peakRSS182192KiB. Native payload, admission-replay and source-hash gates passed.

| Context | Historical Luna admissions | Fresh Luna | Sol |
|---|---:|---:|---:|
| da-10-1 rep-001 | 0 | 0 | 0 |
| da-10-1 rep-002 | 0 | 0 | 0 |
| da-10-1 rep-003 | 0 | 0 | 0 |
| da-10-3 rep-001 | 0 | 0 | 0 |
| da-10-3 rep-002 | 0 | 0 | 0 |
| da-10-3 rep-003 | 0 | 0 | 0 |
| da-12-2 rep-001 | 0 | 1 | 1 |
| da-12-2 rep-002 | 0 | 0 | 0 |
| da-15-1 rep-002 | 2 | 2 | 2 |

Both fresh arms admit3criteria across2/9contexts. The prior Luna applications admitted2criteria in1/9contexts. The extra acceptance in da-12-2 rep-001 appears in both arms, so it cannot be credited to Sol.

Relative to historical Luna, fresh Luna changes15/69criterion-artifact levels; Sol changes19/69. These are variability/disagreement counts in a selected mechanism sample, not accuracy estimates. All prompts, criteria, inputs and gates were fixed; only the model differs between fresh arms.

## Preidentified factual checks

- da-10-3 rep-001: both models still giveA to the artifact whose listed catGRANULE values average0.632 but whose answer claims0.707. Both rationales falsely say the summaries reconcile. Increasing model size at unchanged low reasoning did not repair this error.
- da-12-2 rep-002: both models now giveC to the artifact that claims full pathway membership while its code still intersects the restricted universe. The corrected application does not secure admission: the proposed criterion replaces an existing criterion and the prospective aggregate margins do not strictly improve the required gaps.

## Decision and next step

Do not adopt the Sol application model or launch revisions from this diagnostic: there is no advantage over fresh Luna, and the arithmetic error persists. Distinguish faulty applications from shared genuine defects and replacement penalties that leave margins unchanged. Do not relax admission gates or count a lower training reward as better artifact quality.

The next narrowly justified candidate is an application-instruction clarification requiring a concrete numerical consistency check when a criterion concerns computed summaries; claims of a successful self-audit/supersession are not themselves evidence. Freeze and test that single change with the same saved criteria/artifacts and unchanged Luna model before any production adoption. Do not regenerate pair assessments/proposals, revisions or outcome audits.

No BioMNIBench completion checkbox advances; no confirmation launch. Full-trajectory and final-artifact outcome auditors remain unchanged.
