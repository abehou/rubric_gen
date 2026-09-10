# Pretreatment feedback variability in the ranking comparison

The first feedback-generation receipts were compared for all 60 matched assignments, before any online ranking-rule admission. Initial artifact hashes, history hashes, simulator configuration/implementation signatures, and initial rubric-generation hashes match in all 60 pairs. Initial selected-base scores also match in all 60 pairs.

However, initial composed training scores match in only 45/60 pairs, the native full-feedback hashes match in only 2/60, and generated user-feedback JSON matches in **0/60**. Therefore the two live trajectories already differ before the changed online admission rule can operate. Full-feedback hash differences alone do not establish semantic differences, but the composed-score differences and simulator-output differences are directly observed.

This does not invalidate a randomized stochastic treatment comparison or excuse the adverse outcome. It does prevent attributing all new RH to the seven newly permitted admissions. Those admissions occur in only six assignments; 34 of 36 newly positive auditor observations occur elsewhere. Same task seeds and frozen source inputs do not make hosted judgments or user feedback deterministic.

The next diagnosis must locate why initial composed feedback was regenerated and determine whether a future matched trace-only change can reuse compatible frozen initial assessments and feedback without fabricating provenance. Do not retrofit completed runs, exclude divergent cases, or treat observed feedback differences as a proven explanation of the full effect. No new scientific run is authorized by this diagnostic report.

Evidence: `cue-ranking-initial-feedback-check.json`, the state paths in `cue-ranking-mechanism-census.json`, and `cue-ranking-rule-exposure.json`. All checks used existing frozen outputs without provider calls.

## Code-path diagnosis

The frozen ranking source uses `study.py` to construct the exact-judgment reuse store at `self.root / "shared-judgments"`: reuse is scoped to one study root, not automatically shared with a previous Result20 study. In `controller_scoring.py`, initial seed judgments are reused only when the active generation matches the seed rubric and the scoring contract permits reuse. The selected-base reference is preserved, while the elicited-rubric assessment is generated through the study-local store and its penalty is composed with that reference. This is consistent with identical selected scores but differing initial composed scores.

The simulator then makes a fresh call when the assignment-local feedback record is absent. `user_simulator.py` validates saved records against experiment ID, assignment ID, submission, generation, full-feedback hash, artifact/history hashes, and simulator identity. Copying an older feedback JSON into the new experiment would fail legitimate provenance checks. Do not patch identities to force reuse.

There is no evidence here that the selected/master wiring fix regressed. A future explicit, validated producer-input mechanism could reuse exact initial judgments/feedback, but that would change the coupling of experimental randomness and must be prospectively specified. It is not a repair to historical results and should not be implemented merely to recover the favorable original trace rate. First finish the original rubric-cue case-level delivery analysis and assess whether a focused policy change has a verified mechanism.
