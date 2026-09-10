# Completed pretreatment validation guard

## Corrected finding

Full call-order inspection shows RubricProposer.elicit_rubric invokes _load_completed_generation before constructing a request cache or entering _produce. Completed-generation metadata comparison already rejects a changed producer identity without provider calls. The earlier report of a potential cache miss causing provider work for an intact completed generation was not supported and is withdrawn.

The added early guard only improves error locality and avoids rebuilding saved evidence before detecting an incompatible identity. It does not resolve a demonstrated provider-call bug or enable cross-version reuse. Existing source artifacts remain immutable.

Validation:93tests passed across test_pretreatment_reuse.py, test_rubric_generation.py and test_rubric_evolution.py. New cases cover missing/mismatched/matching identity and unchanged files. No scientific provider calls.

Frozen cue reuse still requires explicit immutable-input provenance, not pretending the source used current code. Native current-format evidence revalidation can establish semantic compatibility separately from producer identity. Do not bypass existing metadata checks or silently regenerate the starting rubric.
