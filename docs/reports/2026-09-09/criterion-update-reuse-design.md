# Starting-rubric matching for a follow-up

Read-only source inspection; no active experiment changed or new provider work launched.

`submission_revision/pretreatment_reuse.py:source_pool` reloads the source YAML with the executing implementation and compares the derived experiment ID with the declared source ID. `experiment.py:_derived_experiment_id` incorporates `prompt_implementation_sha256()`. Consequently, a prompt implementation change can prevent cross-version source reuse even when the starting-rubric protocol is unchanged. This is an identity-validation constraint; do not override the source ID or relabel saved artifacts.

The current delivery comparison has different starting criteria on 12/20 tasks. Complete and report it as a developmental comparison, with this limitation. If results justify isolating delivery, prefer a fresh paired design in one frozen implementation: an explicit delivery-policy configuration for note versus unchanged control, both referencing one natively validated completed starting pool from that same implementation. Verify identical selected and starting rubrics, seeds, blinding scope, evaluators, and all other configuration before launch. The existing control must remain unchanged by default. This is proposed follow-up design, not an implemented or approved scientific result.

Do not invest in cross-version compatibility machinery or rerun cohorts before current outcomes determine whether this direction merits the cost. Shared seed/paraphrase reuse remains independent of this starting-rubric issue.
