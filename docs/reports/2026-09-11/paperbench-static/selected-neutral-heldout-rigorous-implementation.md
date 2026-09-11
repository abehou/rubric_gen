# 2026-09-11: Selected-neutral / heldout-rigorous implementation

The intended intervention compares neutral selected score S with stricter heldout
score H; successful manipulation should lower H relative to S and make S−H
positive. This implementation does not measure that outcome.

The completed diagnostic at
`docs/reports/2026-09-10/paperbench-static/uniform-rigorous-v2-diagnostic.md`
established that PaperBench variants 0–4 all used rigorous-V2. The original request
path confirms that behavior. That completed run remains a valid, unchanged uniform
rigorous-V2 control. The neutral instructions match Git revision `47463ca^`
byte-for-byte; the rigorous instructions match the pre-change HEAD byte-for-byte.
The supplied diagnostic and baseline YAMLs were already untracked locally; they
remain outside this implementation commit. The derived configs are standalone.

The single optional setting is:

```yaml
rubric_paraphrases:
  prompt_policy: selected_neutral_heldout_rigorous
  count: 5
  selected_variant: 0
  development_variant: 1
  model: gpt-5.6-luna
  max_retries: 2
```

| Variant | Configured role | Opt-in instructions | Default instructions |
|---|---|---|---|
| 0 | selected | neutral/original | rigorous-V2 |
| 1 | development | neutral/original | rigorous-V2 |
| 2 | heldout | rigorous-V2 | rigorous-V2 |
| 3 | heldout | rigorous-V2 | rigorous-V2 |
| 4 | heldout | rigorous-V2 | rigorous-V2 |

The runner selects neutral instructions for the configured selected/development
IDs, and rigorous instructions for every other index in `range(count)`. Tests also
reserve IDs 3 and 4 to prove role-based selection. There are no benchmark-specific
branches. Missing `prompt_policy` preserves the original payload and uniform
rigorous behavior; an unsupported explicit value fails config validation.

Only instruction selection changes. Criterion-wise requests, model, timeout,
retries, concurrency, numeric protection, wording/schema/structural validation,
duplicate-title repair, metadata, resume, output layout and scoring are unchanged.
Existing request provenance still records the actual instructions/evidence digest;
Git prompt text, config roles and request evidence support reconstruction. No new
hashing layer, gate, frozen contract, fallback or public command was added.

Exact implementation files:

- `src/rubric_gen/submission_revision/paraphrase_protocol.py`: original neutral text and policy name.
- `src/rubric_gen/submission_revision/paraphrases.py`: select instructions before the existing retry/request path.
- `src/rubric_gen/submission_revision/experiment.py`: validate the optional policy.
- `tests/test_rubric_paraphrases.py`: production request capture, five variants, nonstandard roles, provenance, resume, repair, numeric protection and retry exhaustion under both policies.
- `tests/test_experiment.py`: config validation/identity and provider-free PaperBench request demonstrations.
- `experiments/babel/paperbench-static-selected-neutral-heldout-rigorous-dev3.yaml`.
- `experiments/babel/paperbench-static-selected-neutral-heldout-rigorous-results20.yaml`.
- `docs/reports/2026-09-11/paperbench-static/selected-neutral-heldout-rigorous-implementation.md` (this document).

Both derived YAMLs were compared as parsed objects against the supplied baseline
YAMLs. The only differences are the opt-in and four fresh stage namespaces under
`/data/user_data/aydanh/rubric_gen/runs/paperbench-static-selected-neutral-heldout-rigorous-20260911/{dev3,results20}/`.
Tasks, three replicates, seeds, models/effort, revision/feedback protocols,
workspace review, auditor panel/budgets, five variants and role IDs are identical;
the only conditions remain `full-static` and `user-simulator-static`.

Validation:

```bash
.venv/bin/python -m pytest -q tests/test_rubric_paraphrases.py tests/test_experiment.py tests/test_submission_revision.py tests/test_submission_revision_artifacts.py tests/test_babel_portability.py tests/test_paperbench.py
```

Result: **211 passed**. The focused paraphrase/config subset passes **107 tests**.
For the review commit, the same six-file suite was also run on an isolated checkout
of current remote commit `b69160d3189c74a2abdafe99ff510900cea811cb`, using
`PYTHONPATH=src /home/aydanh/repos/rubric_gen/.venv/bin/python -m pytest -q` with
the same test paths: **201 passed, 1 skipped**. The skipped portability test needs
transferred local evidence absent from that checkout; synthetic resume tests pass.
The remote was 13 commits ahead, so this preserves both its history and the
original dirty worktree.
An additional run including `tests/test_experiment_matrix.py` yielded 215 passes
and two existing failures: `test_biomni_and_paperbench_use_one_exact_factorial_per_tier`
and `test_biomni_results_focused_feedback_factorial_reuses_shared_inputs` expect old
BioMNIBench relative pool paths. Those tests and YAMLs match pre-change HEAD; the
committed configs already use canonical NFS paths. They were left untouched.

Reproduce the request demonstration with:

```bash
.venv/bin/python -m pytest -q -s tests/test_experiment.py -k paperbench_prompt_policy_requests
```

Result: **4 passed**, printing the table above for both derived configs and again
with the opt-in omitted. It calls production `ParaphraseRunner._generate_group`
through `_paraphrase_request`, captures the actual `StructuredRequest` in the
injected generation operation, and returns synthetic fixture wording. Dataset
access uses tiny temporary fixtures; this is not validation of the NFS dataset.
The demonstration creates no pool directory and makes no hosted provider calls.

Compatibility concern: existing pool validation does not compare instruction
policy, and resume semantics intentionally remain unchanged. Never point the
opt-in config at an old or differently configured pool; use the supplied fresh
namespaces. Existing valid default pools resume without mutation. The opt-in is
already included in existing experiment identity derivation; no new identity
mechanism is needed.

No scientific provider run, scientific paraphrase-pool generation, revision, audit or results
rewrite occurred. Completed PaperBench pools/judgments/results/reports, historical
provenance, both original PaperBench YAMLs and all BioMNIBench active/frozen
configs/pools/results were untouched. Unrelated pre-existing worktree changes,
including the root experiment/review logs, remain untouched and unstaged.
