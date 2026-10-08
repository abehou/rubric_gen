# HealthBench Result50 pre-revision input transfer

Prepared 2026-10-07 22:27 PDT. Repository: https://github.com/abehou/rubric_gen
Branch: `codex/healthbench-researchqa`.
Archive: `transfers/healthbench-qwen-result50-inputs.tar.gz` (ordinary Git; below 100 MiB).
This branch stages inputs only. No experiment/model calls, regeneration, scientific-output edits, or source-manifest edits were performed.

## Source identity and exact Mac paths

The actual frozen Result50 is the union of retained20 and extension30 in
`/Users/yuenanhuang/Desktop/rubric_gen/experiments/healthbench-hard-result50/manifest50.json`.
It is not `result-001` through `result-050`, and it is not the separate prepared100 inventory.
The source extension YAML selects only the 30 additions; it does not claim to be a single 50-task producer.
Its saved run copy is `/Users/yuenanhuang/Desktop/rubric_gen/runs/healthbench-hard-result50-extension-20261006/experiment.yaml` and is byte-identical to the packaged source YAML.

- **retained20**: config `/Users/yuenanhuang/Desktop/rubric_gen/experiments/healthbench-hard-result20/local.yaml`; materialized tasks `/Users/yuenanhuang/Desktop/rubric_gen/runs/healthbench-hard-challenge20-local-20260926/tasks`; seeds `/Users/yuenanhuang/Desktop/rubric_gen/runs/healthbench-hard-challenge20-local-20260926/seeds`; paraphrases `/Users/yuenanhuang/Desktop/rubric_gen/runs/healthbench-hard-challenge20-local-20260926/paraphrases`; experiment `healthbench-hard-factorial-r3-01eb8a5a9277`.
- **extension30**: config `/Users/yuenanhuang/Desktop/rubric_gen/experiments/healthbench-hard-result50/extension.yaml`; materialized tasks `/Users/yuenanhuang/Desktop/rubric_gen/runs/healthbench-hard-result50-extension-20261006/tasks`; seeds `/Users/yuenanhuang/Desktop/rubric_gen/runs/healthbench-hard-result50-extension-20261006/seeds`; paraphrases `/Users/yuenanhuang/Desktop/rubric_gen/runs/healthbench-hard-result50-extension-20261006/paraphrases`; experiment `healthbench-hard-factorial-r3-654d4cc2a2e6`.

The retained20 selection originally materialized at
`/Users/yuenanhuang/Desktop/rubric_gen/data/healthbench-hard/challenge20-20260926/`;
its source task files match the completed run's materialized tasks byte-for-byte.
The extension30 originally came from the prepared80 at
`/Users/yuenanhuang/Desktop/rubric_gen/data/healthbench-hard/extension80-20260930/`, with selected materialized run task paths recorded individually in the frozen manifest.
The original selection20 manifest is `/Users/yuenanhuang/Desktop/rubric_gen/runs/healthbench-hard-challenge20-local-20260926/tasks/manifest.json`.
The parent selection record is `/Users/yuenanhuang/Desktop/rubric_gen/experiments/healthbench-hard-result100/selection.json`.
The retained Semi/Score-only configuration is `/Users/yuenanhuang/Desktop/rubric_gen/experiments/healthbench-hard-result20/remaining.yaml`;
it reuses the same retained20 seed/paraphrase pools and does not supply another 20 tasks.

Source runtime provenance: `/Users/yuenanhuang/Desktop/rubric_gen/runs/healthbench-hard-result20-semi-score-20260926/runtime-source`,
copied at the original extension preparation to
`/Users/yuenanhuang/Desktop/rubric_gen/runs/healthbench-hard-result50-extension-20261006/runtime-source`.
Preparation records source Git HEAD `0c31ebe97949e8e46617b22b26e92648b451af0f` plus the original dirty runtime snapshot;
that source record is preserved at `source/extension30/preparation.json`.
The completed run receipt is `/Users/yuenanhuang/Desktop/rubric_gen/runs/healthbench-hard-result50-extension-20261006/invocations/20261006T170954Z/receipt.json`.
The transfer does not include or reconstruct historical runtime code.

## Randomization, prompts, and scientific policies

Both source configurations use assignment randomization seed **20260925**, **3 replicates**, assignment selection `all`, prompt profile `base`, and exactly three revision attempts.
The retained20 dataset selection also records seed **20260925**, `explicit-source-ids-after-rubric-review`, 1,000 official source records.
The parent prepared80 selection records seed **20260930**, content-feature/theme stratification, and no model-outcome filtering.
The frozen30 selection retains six previously used Dev3 source questions and then takes content-ranked tasks within theme quotas:
global_health 6, context_seeking 5, hedging 5, health_data_tasks 5, communication 4, complex_responses 3, emergency_referrals 2.
These are selection identities, distinct from assignment randomization.

Existing clean seeds use Codex `gpt-5.6-luna`, effort `low`, one retry, 1,200-second timeout, null service tier/executable.
Every seed has a separate adversarial elicitation attempt; all 150 attempts validate as included, exit 0.
Their original prompt files are preserved unchanged. Additional rendered `base` and `adversarial` prompt text is recorded per task at `source/prompts/<task>/`;
the native resolver confirmed prompt identity against existing seed-manifest hashes.
Seed owner IDs are `healthbench-hard-factorial-r3-01eb8a5a9277` (60 retained seeds) and `healthbench-hard-factorial-r3-654d4cc2a2e6` (90 addition seeds).
Every existing per-seed content/provenance identity is retained in its unchanged manifest; a compact index is in `source/validation/package-inspection.json`.

Source solvers/W judges use `gpt-5.6-luna low`; RTT generators use `gpt-5.6-luna high`.
Source protocol uses workspace review, `rubric.txt`, no review-character truncation, and original rubric-proposer/simulator settings as written in the unchanged YAML.
The retained first YAML has Full/User-simulator × Fixed/RTT; its Semi/Score-only YAML supplies the other four cells.
The extension YAML binds all eight cells: Full, User-simulator, Semi, Score-only, each crossed with Fixed and Red-team-trace.
Source paraphrases are wording-only `gpt-5.6-luna`, count 5, optimizer variant 0, development variant 1, heldout variants 2–4, two generation retries.
Source outcome audit config is retained as provenance only (6Luna rubric and 6Sol rubric-free panel); no audit artifacts are included.

## Archive contents and unchanged pool manifests

`source/experiment.yaml` is the unchanged actual extension YAML.
`source/dataset-manifest.json` is the unchanged frozen50 manifest.
`source/retained20/` contains the unchanged retained producer YAML, Semi/Score-only YAML, and retained dataset manifest.
`source/parent-selection.json`, the preparation/run receipts, rendered prompt text, and offline validation records explain provenance.
`tasks/<actual-task-id>/` contains each complete materialized task tree, including empty `environment/data/` directories and hidden tests/source records.
`seeds/tasks/<task>/rep-001` through `rep-003` contain:

- unchanged replicate `manifest.json`;
- complete unchanged `submission/workspace/` and `submission/trajectory.stream.jsonl`;
- `initial_judgment/score_validation.json`, `evaluation.json`, and `usage.json`;
- complete unchanged `elicitation_attempt/workspace/` and `elicitation_attempt/run/{prompt.txt,trajectory.stream.jsonl,status.json}`.

`paraphrases/tasks/<task>/variant-000` through `variant-004` contain both `.txt` and `.json` for every variant.
`seeds/manifest.json` is the unchanged retained20 pool marker; the extension marker is identical and is independently retained at `source/extension30/seed-pool-manifest.json`.
Native seed resolution accepts the union because identities reside in each replicate manifest.

**There was no original combined50 paraphrase manifest.**
`paraphrases/manifest.json` is the unchanged retained20 manifest (100 variants);
`source/extension30/paraphrase-pool-manifest.json` is the unchanged extension30 manifest (150 variants).
All 250 variant pairs live at the requested unified `paraphrases/tasks/` paths.
The retained root works for a result-001/002/003 subset; a native addition-cohort view uses the second unchanged manifest as described below.
A single native50 paraphrase-pool validation is not claimed: the retained manifest lacks the addition task records.
No union manifest or fabricated compatibility metadata was created.

Native resolver/consumer inspection found no further required seed files beyond those included.
Standalone `submission/status.json` and `submission/snapshot.json`, stderr logs, and failed solver attempts are not read by `resolve_seed` or fresh revision setup;
the required source status is already inside the seed manifest. They are excluded.
Initial judgments and seed-generation trajectories are archival integrity evidence; they are not Qwen W judgments.

Old shared pretreatment rubrics are excluded: their generation/proposer contract records `gpt-5.6-luna` and original experiment/blinding identity.
`StudyRunner._prepare_pretreatment_rubric` creates a fresh baseline when no pretreatment source is specified, so those old learned rubrics are not prerequisite input files.
The preserved clean/adversarial workspaces provide the pretreatment contrasts. A new all-Qwen proposer must create its own pretreatment under its own run identity.
No old revision studies/trajectories, revised/final answers, simulator outputs, online RTT outputs, detection/audit outputs, credentials/auth state, `.env`, environments, caches, or weights are included.
The copied input paths were checked for forbidden names/symlinks and credential token/private-key patterns; no matches were found.

## Validation and measured sizes

Native `load_experiment`, `HEALTHBENCH_HARD.validate_task`, `SeedSetRunner._validate_pool_manifest`, `resolve_seed`, and `validate_paraphrase_run` passed under both the current Mac source and saved producer runtime.
Task checks additionally compare actual source IDs with frozen selection records and saved official `prompt_id`, native rubric rendering, native instruction rendering, and retained original materialization bytes.
Each cohort's paraphrase manifest was validated against its actual source config, covering all variant metadata/digests and immutable rubric structure.
Required copied files were compared byte-for-byte to their originals, without rewriting any source.
Coverage: **50 unique tasks / 150 seed replicates / 250 paraphrase variants** (500 variant files), including result-001, result-002, result-003.
Missing required files: **0**. Source input validation failures: **0**.
Reports: `source/validation/current.json`, `producer.json`, `package-inspection.json`.

The final archive was also extracted into a fresh directory: every file and directory matched the staging tree, every regular file matched its staged bytes, and all members were safe relative regular files/directories. Native validation after extraction and operational path relocation again passed 50 tasks, 150 seeds, and 250 paraphrases, using the two unchanged cohort manifests.

| Measurement | Bytes | MiB |
| --- | ---: | ---: |
| Required task/seed/paraphrase payload, result-001–003 | 761,623 | 0.726340 |
| Required task/seed/paraphrase payload, all50 | 14,871,420 | 14.182491 |
| Shared source/provenance/validation records and pool manifests | 1,134,858 | 1.082285 |
| Three-task payload plus all shared transfer records | 1,896,481 | 1.808625 |
| Full extracted archive file payload, including all transfer records | 16,006,278 | 15.264776 |
| Compressed all50 `.tar.gz` | 2,562,138 | 2.443445 |

Sizes sum logical regular-file bytes, excluding filesystem allocation, directory blocks, and the separate SOURCE document; compressed size includes tar headers.
The first two rows include all requested archival judgments/trajectories and complete workspaces, not just answer text.

## Skipjack retrieval and extraction

```sh
git clone --single-branch --branch codex/healthbench-researchqa https://github.com/abehou/rubric_gen.git healthbench-input-transfer
mkdir -p /absolute/skipjack/path/healthbench-result50-inputs
tar -xzf healthbench-input-transfer/transfers/healthbench-qwen-result50-inputs.tar.gz -C /absolute/skipjack/path/healthbench-result50-inputs
```

Use an absolute persistent Skipjack storage path in place of the example; extraction includes only relative archive members.
Pilot task IDs: `result-001`, `result-002`, `result-003`; set tasks_dir to extracted `tasks/`, seed input to `seeds/`, and paraphrase input to `paraphrases/`.
Keep the original seed-generator identity and paraphrase-model provenance when resolving these existing inputs; those fields describe the producers, not the new revision-time models.
Set revision-time solver/W/proposer/simulator/RTT roles in a **new** Qwen configuration; do not edit the packaged source YAML or any input manifest.
Source YAML paths are original Mac provenance, not ready-to-run Skipjack paths.

For extension30 native pool validation/use, make a local view with the original addition manifest:

```sh
cd /absolute/skipjack/path/healthbench-result50-inputs
mkdir -p native-pools/extension30-paraphrases
cp source/extension30/paraphrase-pool-manifest.json native-pools/extension30-paraphrases/manifest.json
cp -a paraphrases/tasks native-pools/extension30-paraphrases/tasks
```

This copies existing bytes, does not regenerate variants, and preserves both original pool manifests.
The extra retained20 task directories are ignored by a configuration selecting the actual addition30 IDs.
Later full50 use must resolve these two original pools explicitly or add ordinary input-routing support; do not patch/merge manifests merely to pass validation.
For read-only source-YAML validation, native `RUBRIC_GEN_PATH_MAP_FILE` supports operational relocation while retaining source identity:
map each original tasks root to extracted `tasks/`, both seed roots to extracted `seeds/`, retained paraphrase root to extracted `paraphrases/`, and addition paraphrase root to the native addition view.

### Fresh Qwen judgment compatibility constraint

The current native resolver validates these seed files unchanged, but `controller_setup._seed_reuse` compares the seed judge execution contract with the requested revision judge.
An in-memory check changing only `effective_judge_model` from `gpt-5.6-luna` to `Qwen3.5-9B` reproduces:
`seeded initial judgment uses a different scoring contract for judge execution`.
Thus an unmodified current revision controller cannot yet begin fresh Qwen W judging from these archived Luna-judged seeds.
Skipjack must implement/support fresh initial judgments while retaining archival seed identity; no seed regeneration, manifest mutation, or code change was made for this transfer.
All-Qwen runtime execution is untested and was not authorized here. Input transfer validation success does not claim revision-time compatibility.

## Actual frozen50 task list

| Task ID | Official source ID | Producer cohort | Required payload bytes |
| --- | --- | --- | ---: |
| result-001 | 57f45e92-df59-41df-957d-a4206c671e76 | retained20 | 232,316 |
| result-002 | 6130eee2-2de4-428c-81c3-3464b2c171e3 | retained20 | 226,124 |
| result-003 | ef79e596-9fa3-4fdc-8d6d-3a23ffe6d31c | retained20 | 303,183 |
| result-004 | a7dac6a9-eab5-4c01-882c-dbf6c774d7c3 | retained20 | 378,913 |
| result-005 | 2b7f5235-8176-439f-a8fd-314d8d5f550b | retained20 | 430,066 |
| result-006 | 63e4e0d4-0cb1-442e-8316-8c12a6e3ec14 | retained20 | 299,481 |
| result-007 | 7ca2ba7c-40c6-4b07-9285-181e8563a080 | retained20 | 233,034 |
| result-008 | 9914f37a-8063-4f7c-baa7-b97745b610e6 | retained20 | 282,443 |
| result-009 | 45943bf5-d013-4a13-8acc-f177a813d612 | retained20 | 279,396 |
| result-010 | d69bf5a4-0318-4f99-9cb8-e3c40651c18e | retained20 | 310,270 |
| result-011 | c2fb9729-d1a2-46ea-875c-4b826fccae4e | retained20 | 265,316 |
| result-012 | adbb1db8-5f20-486f-ad56-2b5c39b68013 | retained20 | 277,129 |
| result-013 | b2256875-a184-4447-a53a-34e8a10fba8b | retained20 | 344,286 |
| result-014 | 3485437a-1365-4a91-8cab-a5b0342b1884 | retained20 | 246,268 |
| result-015 | 1e93a526-e2b4-42a1-901a-d6697bb0ead9 | retained20 | 310,394 |
| result-016 | c30dee7b-0cbc-41a8-8436-49b5ea9065b9 | retained20 | 338,712 |
| result-017 | 9e2670fc-2237-492a-afed-d6d198cb673c | retained20 | 381,634 |
| result-018 | 92355c7b-20b1-4741-8528-f07f2f9e7365 | retained20 | 342,453 |
| result-019 | d90e1686-8a91-42b0-90a0-9f09c4b110ee | retained20 | 357,721 |
| result-020 | e91caaef-849e-43b7-8c3e-1afbbff51844 | retained20 | 304,711 |
| result-021 | 1ca222ed-cc79-4e78-9ca3-3547e7b37e3a | extension30 | 235,300 |
| result-022 | 47a50742-10ba-462a-84bb-a119bfe360af | extension30 | 196,467 |
| result-023 | 5f539a2c-85f4-4cc9-8790-e1b23d950954 | extension30 | 228,635 |
| result-024 | b947fc6f-1d50-4e3f-b679-8484529b787b | extension30 | 204,345 |
| result-025 | d546badf-e07b-44a1-bb32-373f263d7458 | extension30 | 191,509 |
| result-026 | d716ca0e-52b9-491b-92b4-1d74e450314c | extension30 | 197,266 |
| result-027 | c0435430-080a-486b-9a6b-8ab25b7b5db1 | extension30 | 304,311 |
| result-028 | ccdcfb68-edfc-47b1-b010-6cf41a77c363 | extension30 | 368,963 |
| result-029 | a819f3b5-3d2f-4330-8868-0e482c96ef02 | extension30 | 328,803 |
| result-030 | 78400c61-14c5-411b-b153-2a26dab7542d | extension30 | 267,687 |
| result-031 | 1f5e62a4-3949-49f8-afce-bc84cfbc6f12 | extension30 | 335,666 |
| result-032 | 62b6848d-7811-4994-a9d7-48437d1e5841 | extension30 | 242,793 |
| result-043 | 0c128afb-be6e-4ea8-b9c2-07cd97e3d8d3 | extension30 | 346,718 |
| result-044 | 3e2283a5-81de-4fac-a1d3-60bcc2762eb9 | extension30 | 408,384 |
| result-045 | 87fa64df-bb0b-417a-b853-0306486aae73 | extension30 | 344,484 |
| result-046 | 1854ebb0-59f1-442b-bfde-1c82dcb31152 | extension30 | 352,176 |
| result-047 | 4bef196d-54dc-4a9d-8fc3-fc6a595c5ddc | extension30 | 414,515 |
| result-057 | 037cdb42-109a-44f5-90f1-09b731842fb2 | extension30 | 340,050 |
| result-058 | 1847f8a8-f3d5-4f04-be2a-5df8b533d85a | extension30 | 258,011 |
| result-059 | 0ac03af4-04e5-489c-9e2c-00aa04fb5575 | extension30 | 304,056 |
| result-060 | 2130cd26-6181-489e-acab-23c549e772ee | extension30 | 234,785 |
| result-061 | ededbafb-a080-473c-8826-97b683a38dff | extension30 | 302,831 |
| result-071 | 0b2e5afc-8672-4157-a71e-5c52fbec828e | extension30 | 265,083 |
| result-081 | e2e23ff7-9eb5-4fb0-b6a8-e7d68f3ab694 | extension30 | 385,787 |
| result-082 | 9c3e21ff-3059-4e96-896a-144e67a065bb | extension30 | 327,252 |
| result-083 | 8e706833-319d-4a28-9ecf-048d28055e79 | extension30 | 310,715 |
| result-090 | b9439cdc-296d-4a31-ad83-4118486f6d8a | extension30 | 310,411 |
| result-091 | 1cd1c06f-d27d-49c1-83a0-b3d427a2976b | extension30 | 222,138 |
| result-092 | a5646305-0705-4ade-9868-83abba55d996 | extension30 | 240,736 |
| result-098 | d539a642-0ab5-4ed2-af54-1ed542320448 | extension30 | 257,693 |
