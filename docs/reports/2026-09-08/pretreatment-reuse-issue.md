# Starting-rubric reuse: efficiency and comparison quality

The cross-file policy run10366421 reused native seeds and sealed paraphrases, but regenerated offline-elicited starting rubrics. Its initial preparation used up to20task workers and then a one-request tail before revision workers began; a low provider-slot count during that phase was not evidence that max_concurrency60 had been reduced.

New and previous trace starting learned criteria differ on10/20tasks (da12-2,13-3,13-6,14-1,14-3,14-8,15-2,16-1,18-7,19-6). Seed artifacts and selected-base rubrics remain fixed. The current experiment should continue as exploratory evidence; differences cannot be attributed cleanly to the sidecarprompt alone. No currentjob restarted orsourceartifactmodified.

Two reuse constraints:

1. The existing source loader accepted only completed, rejecting current completed_scope studies. Fixed using native scope/fullledger validation;22focusedtests pass, including unfinishedscope,wrongcondition,missingrecord andsourceimmutability checks. This fix is on mainonly, not injected into running frozen code.
2. The evolution implementation hash includes red_team.py even for offline startingrubric construction. Changing a sidecar prompt therefore prevents native reuse across those identities. This remains unresolved. A future phase-specific fingerprint may permit safe reuse when the offline protocol is unchanged, but must not retrofit hashes into historical pools; generate a fresh current-format pool when necessary and preserve its provenance.

Future launch preparation should explicitly validate and reuse a sealed startingrubric pool, as well as seeds/paraphrases, before claiming a matched policy-only comparison. Do not silently bypass current provenance checks to save time.

## Phase identity fix

Implemented offline-only exclusion of red_team.py from generation cache identity; full revision and online identities retain it, and all shared induction/protocol code remains bound. A sealed-generation roundtrip proves sidecar-only edits reuse exact bytes with no provider calls, while shared-protocol edits fail validation. Existing pools are not relabeled; generate a fresh pool under this implementation before using it across subsequent sidecar variants. Running experiment code remains frozen.
