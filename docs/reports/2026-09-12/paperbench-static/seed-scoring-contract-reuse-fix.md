# PaperBench Results20 seed scoring-contract reuse

Diagnosis recorded 2026-09-11 21:33 EDT, before the runtime edit, against source
`1776460cd252997f45800a04a5fd590f57a64af3` in the fresh isolated worktree
`/home/aydanh/repos/rubric_gen/runs/babel-code/seed-scoring-semantic-reuse`.

No-provider Slurm job `10406478` on `babel-l5-16` validated all 60 original seeds
and the corrected paraphrase pool. All 114 persisted structural-failure tracebacks
enter `fixed_original_judgment` before rejecting the seed contract. The other six
records remain marked running after cancellation; all 120 states are
`judge_in_progress`, with zero completed revisions.

For all 60 master references, the only different scoring-contract field is
`scoring_implementation_sha256`: saved
`1d8f70e89f4a03a4fe96b26c6f4957f03d5a3f373e59b6efe17a901982f3bfb5`, current
`2d515181d9cd21769900038c6c05bd1949021826f2d8a0d21ee880d070c39b03`.
Setup authorizes these 60 reuses; the old checkpoint rejects all 60.

For all 60 selected-neutral optimizer references, exactly three fields differ:
`scoring_implementation_sha256`, `rubric_source` (`task-local` to `rubric-path`),
and `rendered_rubric_sha256`. Setup correctly refuses these reuses. The original
seed workspace must receive a new selected-neutral score; its master score can
be reused. All 120 persisted optimizer identities exactly match the runtime
identities reconstructed from the blocked scientific configuration and inputs.

Across all 60 seeds, master and optimizer comparisons retain the same
`effective_judge_model=gpt-5.6-luna`, `benchmark=paperbench-code-dev`,
`grading_engine=full-rubric-structured`, `review_mode=workspace`, and null
`max_review_chars`, `rubric_set_id`, `rubric_id`, `structured_rubric_sha256`, and
`manifest_sha256`. The master also retains `rubric_source=task-local` and its
exact rendered rubric SHA. No genuine semantic mismatch is being authorized.

The before-edit receipt is `diagnosis-before.json` in the isolated worktree;
`diagnosis-before-snapshot.json` records 2,993 seed files, 224 pool files and
3,078 blocked-study files, all unchanged across the inspection. These are incident
receipts, not new runtime contracts or gates.


## Root cause and correction

The failing call chain was `run_judge_checkpoint` → `fixed_original_judgment` →
`resolve_reference_judgment` → `verify_round_scoring_identity(seeded=True)`.
The selected-neutral score had passed its identity check before this failure.
`_seed_reuse` already used `same_scoring_semantics`, which ignores only the
producer implementation receipt. The checkpoint instead compared the full seed
contract for equality. This contradicted setup for the same validated judgment.

The change in
[controller_scoring.py](../../../../src/rubric_gen/submission_revision/controller_scoring.py)
imports the existing `same_scoring_semantics` and uses it for that seeded
comparison. The explicit rendered-rubric SHA check and full required-field
extraction remain. Setup, seed loading, reference resolution, ordinary scoring,
and scientific configuration are unchanged. Saved implementation provenance is
read as recorded; nothing is rewritten or backfilled.

## Full cohort contract comparison

These values apply to every task/replicate in the table below. “Same” means
identical to the saved seed contract, including null fields.

| Field | Saved seed | Current master | Current selected optimizer |
| --- | --- | --- | --- |
| `scoring_implementation_sha256` | `1d8f70e…` (full value above) | `2d515181…` | `2d515181…` |
| `effective_judge_model` | `gpt-5.6-luna` | Same | Same |
| `benchmark` | `paperbench-code-dev` | Same | Same |
| `grading_engine` | `full-rubric-structured` | Same | Same |
| `review_mode` | `workspace` | Same | Same |
| `max_review_chars` | null | Same | Same |
| `rubric_source` | `task-local` | Same | `rubric-path` |
| `rubric_set_id` | null | Same | Same |
| `rubric_id` | null | Same | Same |
| `structured_rubric_sha256` | null | Same | Same |
| `rendered_rubric_sha256` | Seed/master column below | Same | Selected column below |
| `manifest_sha256` | null | Same | Same |

All three replicates of each task were independently loaded and checked. Each
row represents three seed judgments used across the two feedback conditions.
The saved score-validation identity also equals its seed-manifest identity in
all 60 cases.

| Task | Replicates checked | Saved seed / current master rendered SHA | Current selected-neutral rendered SHA |
| --- | --- | --- | --- |
| adaptive-pruning | 1, 2, 3 | `eee3c49d68a02dee837222f4c8eb38ccea923167741956db554f170c1b4d4ae6` | `f4c6237974163af9dffcd822a204563587183865fe1e885f9143bddecf32f45e` |
| all-in-one | 1, 2, 3 | `c042648e814dd6ecb75046c72695c04e9bf081c6f3663f5bf0490c6b9daf9dd5` | `37a4494b19fe4881b17ca807d32eb8ffe5fe1572a883d907432bb1bf551c606b` |
| bam | 1, 2, 3 | `afe48f8367dcd2ade926636a710e7de0cca0009a5e76421a1a7799e4eed3bddd` | `cb3e157dc2527b6173f236d38f43c47538adb71913c24be143fcb77e65a29e19` |
| bbox | 1, 2, 3 | `5a8958e79e5c0e768b1759a1673dc5864089e5fab1900e53678feae0fb0d9d59` | `8385932ae7470367384f4a39c2a75eb11b3091c9545b85f0b8587b19a5e4626b` |
| bridging-data-gaps | 1, 2, 3 | `68b16245c0af81e55b7b4f69c4dbb6c0dcbc4a21d020008040f31897729e2d88` | `d78dfeb220fee0b93b541ea827bd7a554bf7bf6f74049faa4f3156f2fee6bb8c` |
| fre | 1, 2, 3 | `b2d0ea40a3ae111a1cdfeb558f69fb99498073bbcfb3ce2e8cf4f4577d19504c` | `71c5765f2b129aa90189b4ddafe56773d1247b92894706e0df229128b55b82da` |
| ftrl | 1, 2, 3 | `1f2f4e94c97e86d8cb6707fdb53233deef92280dcbda98204ee1fc26cdbb01eb` | `5fc2e5bec8aec3e3689d7a0f63fe58c514ba6e2d10111c67c3b171810adaccd7` |
| lbcs | 1, 2, 3 | `65b116ecdad34540287cac416c9c9ebe65c36f384be3241cd61baa14e6b94460` | `994f490b267ce0bcfc511641f91925dbc39555ae609c20f1881789a755b63e19` |
| lca-on-the-line | 1, 2, 3 | `25de171b12075805d9c4e9bd6327b4d2de44e88d9285382850794224d0a18db2` | `6750de638fc187a119228e6728d84b580e56663f0406fd7cf2f3a3b9c50a7d5d` |
| mechanistic-understanding | 1, 2, 3 | `23f66975c8d2401646a2e95a22e6383021e19106a9cbaa25538b15263bbeecd9` | `ab9a1c185b48d56fd262ae5670dcb50d47444812731dbbfd03ed685008b24d80` |
| pinn | 1, 2, 3 | `d2a51156f4eacd8b82e412f4e340fc9afafe7f3fe84effef75404e4ed9a72f49` | `fbc05bee223f38c41dab08d3941390ef166c72f6cbb42e59c80214fb5111846a` |
| rice | 1, 2, 3 | `6ca31fb935f3ab5ee74bde7d4b4f7f3c4f75e2b12468a6a82e8a7302453df278` | `e88939ff678a52abbc5ee9034a87a8dcef9f5f3bddb474050859df3e117eb57d` |
| robust-clip | 1, 2, 3 | `2729121f5f8395913545a1c9c4674117b1f8c362c16125f90bf5dc2a87707c16` | `e22df7059b879efc720a9d1b23956f7ac5770e00a4dd340383a45dd46ec64e28` |
| sample-specific-masks | 1, 2, 3 | `0405274662d84b306994515c5afc60c39d4593b6f4a1b03514c48029e2fdf634` | `92c509e398903d56984cf45ee427adced351addbc6246732f64825eb40e3b8a7` |
| sapg | 1, 2, 3 | `56ea360f65cfe059d00043f66b5ad9fa75c6d9dff4d399b5c5aca8dca7db1b15` | `e4a3530d58cd4689098412cc134b6d4e241718be8c52b003af682939f86b120a` |
| sequential-neural-score-estimation | 1, 2, 3 | `24d1afa4b5b801ac86edb727a746b214c8a57fdc7adea4bb3ce5e1199375cf3d` | `83b52921e7402066e8b0e2277aff6fea75b0d9e35587d54cb3245831a8f3b9ee` |
| stay-on-topic-with-classifier-free-guidance | 1, 2, 3 | `43c660ad7307e6e8b25dd0cddc561920cb376f458fb3a71dd176d7cd3c0bb45d` | `a1da9e6cf0eb065a35daf0ace04ced65e5a100bba55ff45c6fea4eef6e9b37d9` |
| stochastic-interpolants | 1, 2, 3 | `7041c4a9ab520d03749e24942db56d57a08fb36fbba8cfb8bd0160072cb5d604` | `e1be25d508b01c1c433e63e65c9e0bc145f56dbd5d246173053e6dcaf97fa697` |
| test-time-model-adaptation | 1, 2, 3 | `046e16ac0559838a25b9c2ff4a49a3bf98d704258bb68ac2ad3b229d10f61261` | `4714e2930f3eeab3367d5225df45405736a888679b3c05db96b58f13ffc0de4f` |
| what-will-my-model-forget | 1, 2, 3 | `f8dc749421f38d85565a453dd58113a1f7df50708dcf9b27f6eaf8bca7122cee` | `9e3ef3ff13a8a1dc6a9864bfc2f5bbfaef77b1b7a73224688f35d1f15810d27b` |

## Tests and no-provider validation

The regression subset first produced **2 failures and 13 passes** on the old
runtime. Both failures were the observed seeded-contract error: one at optimizer
reuse and one at master reuse after selected-rubric rescoring. With the fix,
**15/15 pass**. Coverage includes:

- Same-version and older-implementation seed reuse through a complete initial
  checkpoint, with judge/solver execution forbidden and seed bytes preserved.
- Every one of the 11 scientific contract fields changed independently:
  execution changes fail setup; rubric changes disable reuse; forced seeded
  verification rejects all mismatches.
- An independent rendered-rubric binding check even when saved/current contract
  dictionaries otherwise agree.
- A changed selected-neutral rubric receives one fake current score on the
  identical seed workspace and trajectory, while the older master judgment is
  reused with zero master calls. Its saved provenance remains unchanged.

The broader verification passed **240 tests**:

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src \
  /home/aydanh/repos/rubric_gen/.venv/bin/python -m pytest -q \
  tests/test_submission_revision.py tests/test_revision_seeds.py \
  tests/test_submission_revision_judge.py tests/test_judgment_reuse.py \
  tests/test_rubric_paraphrases.py tests/test_experiment.py \
  tests/test_full_rubric_judge.py tests/test_submission_revision_artifacts.py
```

Post-fix Slurm job `10406738` on `babel-l5-16` passed using the actual inputs:

- **60/60 original seed blocks pass native integrity loading**, including their
  workspace, trajectory, saved judgment, and manifest provenance.
- **60/60 master reuse decisions and seeded checkpoints agree and accept**;
  the actual fixed-original reference resolver returns the original saved files.
- **0/60 selected optimizer seed judgments are reusable**; forced seed reuse
  still rejects every differing selected contract. All 120 persisted optimizer
  identities match the reconstructed runtime identities.
- **20 tasks × 5 paraphrases pass native pool validation**. This includes replay
  of criterion request provenance and repair records under the configured role
  policy: selected **0 neutral**, development **1 neutral**, heldouts
  **2/3/4 rigorous-V2**.
- Across before-edit and after-edit snapshots, **2,993 seed files, 224 pool files,
  and 3,078 blocked-study files are byte-identical**, including file membership.

Both diagnostic jobs used 2 CPUs, 8 GiB and a 30-minute allocation on
`preempt/preempt_cpu_qos`. They imported only the isolated source through
`PYTHONPATH`, disabled Python bytecode writes, and used the existing Python
environment at
`/data/user_data/aydanh/rubric_gen/cache/paperbench-static-v2-20260910/environment/bin/python`.
The private diagnostic patched network connections and judge execution to raise,
constructed native revision dependencies, and called native seed loading,
paraphrase validation, setup, seeded verification, and fixed-original reference
resolution directly. It did not call the controller's workflow runner.

Receipts retained in the isolated worktree: `diagnose_seed_reuse.py`,
`diagnosis-before.json`, `diagnosis-after.json`, their `*-snapshot.json` files,
and allocation logs `diagnosis-before-10406478.out` and
`diagnosis-after-10406738.out`. No new runtime gate, frozen contract, or
compatibility whitelist was added. No hosted provider calls, solver turns,
audits, scientific aggregation, seed regeneration, or paraphrase regeneration
occurred.

## Restart recommendation (not executed)

Use a **fresh revision-study namespace**. Native resume is not guaranteed safe:
`StudyRunner._validate_manifest_identity` rejects the available configuration
with `study resume identity differs from the experiment`. The study records the
removed temporary YAML
`runtime-throughput-final/experiments/babel/paperbench-static-selected-neutral-heldout-rigorous-results20-final.yaml`.
All 120 assignment states remain `judge_in_progress`; 114 have structural
failures and six were interrupted, with zero valid completed revisions.
Passing seed-semantic checks does not establish valid recovery of every partial
assignment, live workspace, and saved attempt. Mutating recovery was not invoked.
Keep the entire blocked tree as failure evidence.

Preserved blocked study:
`/data/user_data/aydanh/rubric_gen/runs/paperbench-static-selected-neutral-heldout-rigorous-20260912/results20/study/paperbench-code-dev-factorial-r10-08ba4d2c0d00`.

Retain these exact inputs:

- Seeds:
  `/data/user_data/aydanh/rubric_gen/runs/paperbench-static-v2-20260910/results20/seeds`.
- Corrected pool:
  `/data/user_data/aydanh/rubric_gen/runs/paperbench-static-selected-neutral-heldout-rigorous-20260912/results20-final-pool/paraphrases`.

The proposed output base is
`/data/user_data/aydanh/rubric_gen/runs/paperbench-static-selected-neutral-heldout-rigorous-20260912/results20-seed-reuse-fixed`,
with `study/{experiment_id}` and `audit/{experiment_id}` beneath it. The new
namespace was absent during validation. The scientific experiment ID remains
`paperbench-code-dev-factorial-r10-08ba4d2c0d00`; storage changes do not alter the
scientific identity.

A storage-only overlay is prepared locally at
`experiments/babel/paperbench-static-selected-neutral-heldout-rigorous-results20-seed-reuse-fixed.yaml`
in the isolated worktree. It is not included in the narrow publication. To
recreate it in a checkout of the published fix, copy
`experiments/babel/paperbench-static-selected-neutral-heldout-rigorous-results20.yaml`
and change only these four `dag.*.output_dir` values:

```yaml
seed: /data/user_data/aydanh/rubric_gen/runs/paperbench-static-v2-20260910/results20/seeds
paraphrase: /data/user_data/aydanh/rubric_gen/runs/paperbench-static-selected-neutral-heldout-rigorous-20260912/results20-final-pool/paraphrases
revise: /data/user_data/aydanh/rubric_gen/runs/paperbench-static-selected-neutral-heldout-rigorous-20260912/results20-seed-reuse-fixed/study/{experiment_id}
detect: /data/user_data/aydanh/rubric_gen/runs/paperbench-static-selected-neutral-heldout-rigorous-20260912/results20-seed-reuse-fixed/audit/{experiment_id}
```

No-provider configuration check `10406988` completed successfully: native loading
accepts the overlay, all 120 assignment identities and every non-DAG payload
field are unchanged, and both proposed output paths are absent. The local receipt
is `restart-config-10406988.out`; the checker only loads and compares configuration.

After separate authorization for the scientific run, use the commit containing
this fix as the execution source. From its isolated checkout, the recommended
revision command is:

```bash
sbatch --parsable --cpus-per-task=32 --mem=256G \
  --job-name=pb-results20-seed-reuse-fixed \
  scripts/babel/experiment.sbatch --profile results20 revise \
  --experiment experiments/babel/paperbench-static-selected-neutral-heldout-rigorous-results20-seed-reuse-fixed.yaml
```

This uses 32 assignment/request workers with the existing aggregate provider cap
of 60. It consumes the validated pools directly, in a fresh study directory,
without invoking seed or paraphrase generation. Complete native revision
validation before launching `detect` against the same overlay in the fresh
audit namespace. Neither command was launched in this session.
