# attack_defense_v2.1 implementation receipt

The production snapshot keeps the first passing `attack_defense_v2` recipe and
adds only the mechanical duplicate-title guard requested after the two failed
assignments. The scientific prompts, attacker, source schedule, pair selection,
diagnosis/compiler/application semantics, native support and margin gates,
penalties, reminder renderer, solver, simulator, auditors, task set and endpoint
definitions are unchanged.

The guard uses the renderer's exact normalization:

```text
" ".join(title.casefold().split())
```

Before insertion, a candidate is rejected with `duplicate_criterion_title` when
that normalized title collides with a base criterion, an active learned rule not
listed in the candidate's valid replacement set, or an already accepted candidate
in the same update. Rejected candidates are not renamed, redrawn, merged, or
reserved. A same-title learned-rule replacement is allowed only when it exactly
removes that rule. A final uniqueness assertion remains before rubric rendering.

The two saved failures are reproduced by the tests as candidate-local structural
rejections. Case/whitespace folding, base collisions, active-rule collisions,
valid replacement, same-update reservation, failed-first-candidate behavior, and
noncollision legacy behavior are covered. Provider-free focused suites passed:

```text
tests/test_trace_defense_v21.py tests/test_trace_defense_v2.py tests/test_rubric_evolution.py: 109 passed
tests/test_revision_evaluation.py tests/test_trace_defense_v2.py tests/test_trace_defense_v21.py: 92 passed
```

The source snapshot used by the scientific run is `f403b4c4a14eca1e9d61ddfc8c6aa323fda02abc`.
The v2.1 guard is in `621fb7c`; the audit-only identity adapter and consumer
recovery records are in `c43a921f9f187cda8659304547ec8849a5f5ba7c`. The production
freeze and all file hashes are in the linked `execution-freeze.json`.

