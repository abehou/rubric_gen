# Pair-attribution clarification: do not promote

Diagnostic10376113 completed36/36cells in118.6seconds with0retries; analysis10376132completed. Frozen9contexts (8deterministically selected plus discoveryanchor), original versus clarification instructions crossedwithoriginal/swapped A/B presentation. No revisions or outcomeaudits.

| Endpoint | Control | Clarification |
|---|---:|---:|
| ID-mapped preference agreement across orders |42/51 (82.4%)|37/51 (72.5%)|
| Ties across both orders |1/102|5/102|
| Non-anchor agreement |38/46|35/46|

These are context-pair counts, potentially correlated/repeated, not a population reliability estimate. Order agreement is not correctness. Both prompts identify the discoveryanchor correctly in bothorders; the historical attribution error does not recur there, so it cannot demonstrate the intervention improved the anchor.

## Independently checkable adverse case

Context4 pair_3587e0d5c4401620: the saved exact diff changes artifact_18d263b47aeb0755's PhaSepDB mean0.849 to artifact_207cf8035e900e86's0.749. The clarification/original response instead says artifact_207cf8035e900e86 contains the erroneous0.849 and prefers artifact_18d263b47aeb0755. This attribution is false regardless of which mean is scientifically correct. Explicitly naming IDs and quoting text does not guarantee correct source binding. Its swapped-order response prefers the otherartifact.

Context0 responses additionally refer to corroborating artifacts/results elsewhere. The request contains several artifacts and pairs, so independent-claim support versus cross-artifact borrowing needs checking. This wording alone is not proof of contamination: identical shared context may legitimately corroborate a claim. Context3 also changes from tie to preference under swapping.

## Decision and next minimum work

Reject this clarification before expensive revisions: the prespecified diagnostic does not establish better attribution and order consistency is worse. Preserve all judgments; do not select the favorable order or rewrite historical preferences. No RH/gap/quality completion criterion is advanced.

Next inspect whether multi-pair evidence packing creates cross-pair attribution errors, using saved request contents. If verified, a separate isolated **single-pair versus original full-context assessment** diagnostic is appropriate, keeping the original instructions/model and both orders. It must preserve each pair's complete two artifacts and task; it is an explicitly different request shape, never called an exact original control. No criterion admission, simulator, solver, or outcome-auditor changes. A favorable diagnostic would still require a new prospective trace-only decision before revisions.

Evidence: `cue-pair-attribution-analysis.json`, `cue-pair-context-index.json`; shared raw calls `/data/user_data/aydanh/rubric_gen/runs/cue-pair-attribution-20260909/calls-10376113/`.
