# Selected-rubric feedback reference

The selected rubric defines both the visible rubric and the revision score/base-criterion feedback. Master-rubric judgments are independent measurements; held-out and holistic judgments remain evaluation-only. Dynamic rubrics compose the selected-base score with learned penalties, discarding active regrading of base criteria.

The production correction was already published in migration checkpoint `45f3eeb3d8239ea524aa50e3e8a4d7d095c77ef6`. This focused follow-up preserves that history and extends its unequal-selected/master regression across full, semi, score-only and user-simulator feedback. It introduces no simulator prompt, policy, task, runtime, evaluator or experimental change.

`controller_reference.py` resolves the exact selected judgment; `controller_scoring.py` records its hash binding and independent master measurement; `feedback.py` verifies the active rubric reconstructs from the selected base. The protocol is `selected-base-plus-active-penalties-v1`; completed-study validation and resume reject swapped references or missing markers. Historical mixed-reference runs are not relabeled.

Focused verification:

```bash
PYTHONPATH=src python -m pytest tests/test_submission_revision.py -k 'selected_reference_later_checkpoint_and_resume or fixed_paraphrase_accepts_separate_master_rubric_score'
```

The original correctness-only patch and acceptance evidence are preserved in [prerequisite-code.diff](../investigation/selected-reference-wiring-20260907/prerequisite-code.diff) and [VALIDATED_RESULT.md](../investigation/selected-reference-wiring-20260907/VALIDATED_RESULT.md). No duplicate reapplication or remote history rewrite is needed.
