# Saved learning-path findings before outcome audit completion

This is a provider-free analysis of the **complete 120-assignment revision cohort**, using execution snapshot `106863b2ca1bfb543be3d6660aaeca56baec15af`. It does not establish an RH or quality effect. The authoritative audit was still waiting for the shared audit-study slot when these findings were recorded. No scientific prompt, schema, threshold, judgment or output was changed in response.

## Very little new learned coverage reached the solver

| Quantity | Full | User |
| --- | ---: | ---: |
| Completed assignments | 60 | 60 |
| Live updates / sidecar checkpoints | 318 | 465 |
| Nonidentical public sidecar outputs | 318 | 465 |
| Assignments with an online proposal | 23 | 33 |
| Online proposed criteria, counting update appearances | 101 | 204 |
| Assignments with an online admission | 1 | 0 |
| Online admission events | 1 | 0 |
| Assignments with a focused reminder before turn 1 | 21 | 21 |

All assignments completed without a separate revision recovery run. The structured learner recorded 12 Full and 22 User provider-failure attempts, recovered within the existing bounded request contract. This is distinct from scientifically unsuccessful diagnosis/application output. Nonidentical artifacts and `attack_created` narration do not prove successful attacks.

Full made 318 solver turns and retained 258 changed revisions; all 60 assignments ended under the unchanged no-change rule. User made 465 turns and retained 433 changed revisions; 32 ended by no-change and 28 at the maximum revision count. These terminal reasons are completed outcomes, not timeouts or missing assignments.

The User arm's focused reminders therefore came from unchanged frozen offline rules. A passing offline rule can be delivered proactively under this treatment, so zero online admission does not imply treatment equivalence to the historical trace or static arm. The bundled timing, feedback construction and sampled continuations also remain relevant; endpoints cannot yet be inferred.

All Full focused reminders also came from frozen offline rules. The one new rule, in Full da-15-2/rep-003, passed every subsequent optimizer application and never received a focused reminder: a penalized offline rule took the turn-1 priority slot. It **was nevertheless exposed verbatim in ordinary Full feedback at turn 1** and subsequent turns. [Timing lineage](timing-rule-lineage.csv) records actual prompt offsets/hashes separately from focused-reminder exposure, preventing a false claim of no intervention.

## Invalid replacement references block diagnosis

Of unique assignment-local diagnosis request-cache entries, **126/236 Full (53.4%)** and **210/369 User (56.9%)** returned an invalid learned-rule replacement reference. Scope mismatches occurred in 27 and 49 entries respectively; these categories can overlap. These counts remove repeated generation references to the same cached response.

The saved examples show the model trying to name **frozen base-rubric criteria** when the supplied active learned-rule list is empty. For example, Full da-10-1/rep-003 returns `Criterion 1: Loading Data and Validating the Schema`; User da-18-7/rep-002 returns `Criterion 1: Cohort Selection`. Both requests supply no replaceable learned-rule IDs. Those titles cannot replace a learned criterion and are rejected. These are actual returned strings, not an inferred explanation from admission counts.

[Diagnosis replacement examples](diagnosis-replacement-examples.json) include the supplied ID list, returned replacements, diagnosis status, gap cause, exact request path and SHA256. The unchanged implementation checks membership in the current learned-rule IDs before compilation. It does not rewrite the base rubric or silently reinterpret these responses as new criteria.

## Literal quotation failures compound across required artifacts

| Arm / stage | Unique saved request entries | Entries with quote/witness failure | Invalid quoted spans |
| --- | ---: | ---: | ---: |
| Full quality ordering | 673 | 219 | 269 |
| User quality ordering | 1,315 | 435 | 522 |
| Full diagnosis | 236 | 42 | 50 |
| User diagnosis | 369 | 66 | 82 |
| Full blind application | 346 | 189 | 268 |
| User blind application | 950 | 526 | 761 |

The diagnosis quotation counts are separate from the invalid replacement references above. A failed decisive quality witness prevents a defensible ordering from entering induction. A supported relation with invalid attributed quotes cannot compile. A candidate needs every required blind application: one bad quote in one required artifact blocks the entire candidate before native support/margin checks, even when other quotes in that response match.

The recheck uses each request's actual inline public bytes and native literal-membership function. No failed quote was found to be an exact match in its attributed artifact. In a verified User da-14-1/rep-001 example, two application quotes match their supplied artifact and a third fails after the judge omits Markdown formatting. Other examples join separated public spans with `...` inside one purported literal quotation.

For **application** failures, retrospective text diagnostics find:

| Invalid-span category | Full | User |
| --- | ---: | ---: |
| Ordered public spans joined with ellipses | 81 | 261 |
| Ellipsis joins plus markup/whitespace differences | 9 | 14 |
| Markup/whitespace differences | 29 | 59 |
| Whitespace only | 16 | 62 |
| JSON-escaped representation | 0 | 2 |
| Still unmatched under these diagnostic transforms | 133 | 363 |

These transformations **do not repair the evidence**, prove scientific correctness, establish that the relation is supported, or change admission. The residual unmatched category is not automatically fabrication; it requires further context to classify. Conversely, finding all ellipsis-separated fragments does not establish that joining them preserves their meaning. [Quote-binding summary](quote-binding-summary.json) reports all stages, while [public examples](quote-binding-examples.json) preserve failed quotations and nearby actual public text with source hashes.

## What this does and does not establish

Only **seven Full candidates and one User candidate** reached native admission decisions: Full had one acceptance and six aggregate-margin failures; User had one semantic-validation failure. Most evaluated candidates were already structurally ineligible because of required applications. Thus these saved records support diagnosis-ID compliance and exact public-evidence production as substantial observed bottlenecks. They do not show that relaxing support/margin thresholds would help, nor that the rejected candidates would have passed those thresholds if their source errors were removed.

The prescribed pipeline correctly retains the unsuccessful responses and does not resample scientifically unfavorable outputs. Its prompt/schema interface nevertheless elicited many responses that could not be consumed. Tests prove the implemented checks and routing, not that the model reliably follows the intended scientific protocol. The complete outcome panel is still required to determine the developmental bundle's RH, gap and quality results.

All detailed generation, proposal, validation and delivery receipts are linked by [pipeline lifecycle](pipeline-lifecycle.csv), [failures](pipeline-failures.csv), [relations](pipeline-relations.csv) and [large-table receipts](raw-table-receipts.json). No follow-up variant is authorized by these diagnostics.
