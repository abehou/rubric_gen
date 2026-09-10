# BioMNIBench canonical inventory audit — 2026-09-08

Canonical development: **da-3-4, da-11-1, da-18-1**, three replicates each, from experiments/biomnibench-dev3.yaml. Canonical Result20: **da-10-1, da-10-3, da-12-2, da-12-4, da-13-1, da-13-3, da-13-5, da-13-6, da-14-1, da-14-3, da-14-8, da-15-1, da-15-2, da-15-7, da-15-8, da-16-1, da-18-5, da-18-7, da-19-1, da-19-6**, three replicates each, from experiments/biomnibench-results20.yaml. These reference factorial configs are not the smaller active tuning launch configs.

## Canonical benchmark bytes

All **23 tasks / 442 files** are present and match the public canonical [phylobio/BiomniBench-DA](https://huggingface.co/datasets/phylobio/BiomniBench-DA/tree/e1c8ca5e11a620087bc48d97888eb69176a1f235) revision **e1c8ca5e11a620087bc48d97888eb69176a1f235**. The transferred Hugging Face download metadata names this revision;fresh public metadata confirms it is still upstream main. Compared complete file lists,sizes,and Git blob SHA-1 or LFS SHA-256 as appropriate;also recorded independent SHA-256 for every local file. This is content verification,not existence-only checking.

| Task | Files | Status |
|---|---:|---|
| da-3-4 | 7 | All upstream hashes match |
| da-11-1 | 16 | All upstream hashes match |
| da-18-1 | 9 | All upstream hashes match |
| da-10-1 | 8 | All upstream hashes match |
| da-10-3 | 9 | All upstream hashes match |
| da-12-2 | 8 | All upstream hashes match |
| da-12-4 | 8 | All upstream hashes match |
| da-13-1 | 8 | All upstream hashes match |
| da-13-3 | 7 | All upstream hashes match |
| da-13-5 | 8 | All upstream hashes match |
| da-13-6 | 8 | All upstream hashes match |
| da-14-1 | 7 | All upstream hashes match |
| da-14-3 | 7 | All upstream hashes match |
| da-14-8 | 8 | All upstream hashes match |
| da-15-1 | 10 | All upstream hashes match |
| da-15-2 | 18 | All upstream hashes match |
| da-15-7 | 16 | All upstream hashes match |
| da-15-8 | 9 | All upstream hashes match |
| da-16-1 | 224 | All upstream hashes match |
| da-18-5 | 9 | All upstream hashes match |
| da-18-7 | 9 | All upstream hashes match |
| da-19-1 | 9 | All upstream hashes match |
| da-19-6 | 20 | All upstream hashes match |

The da-18-1 directory contains instruction.md,task.toml,environment/Dockerfile,the three input tables,and tests/rubric.txt plus judge/test scripts. Dockerfile COPY sources all exist. Input files:data_clinical_sample.txt742508bytes,data_cna.txt1856420bytes,data_mutations.txt2433396bytes. Instruction SHA-2564bb6bbda20df45a308004b518233548056661e825e404f3268ab25d8a2d862e8;master rubric SHA-2567d773f04c056fb4da68dc706f0ce78c2f9cc30b9d08a023d3f2b182e87d53698. All match upstream;no corrupt/missing canonical files and **nothing restored**. Docker /app paths are canonical container paths,not missing Mac files.

## Why the third task was unused

The saved investigation/autonomous-dev3-20260907/plan.yaml explicitly distinguishes two tuning tasks from validation_tasks:[da-18-1] and reserves its current-phase outcome inspection until candidate freeze. This is present in migration commit45f3eeb and experiment records,not an inference from missing data. Earlier historical Mac experiments did use da-18-1;the reserved current-phase validation is not a claim that the task has never been inspected. Preserve the canonical three-task definition and do not silently consume the reserve or redefine dev3 as two tasks.

## Generated seeds and paraphrases are a separate migration gap

Babel has **no top-level seeds/ directory or runs/rubric-paraphrases/ directory**. The user-specified Mac seeds/biomnibench/luna-dev3/tasks/da-18-1 is not present;current canonical YAMLs instead reference native-prompt-dev3/results20 seed pools,which also are absent. No da-18-1 seed manifests or paraphrase variants were found in transferred runs/investigation. The canonical master rubric is present;generated variants are not the same as benchmark files.

Active two-task science uses transferred task-specific seed/paraphrase pools under runs/autonomous-dev3-20260907,with all three saved seeds and five variants for each task;native validation and content identities passed at launch. Their absolute Mac origin paths remain provenance and resolve through the current validated input workflow. They are unchanged by this audit. Their manifest SHA-256/path inventory is generated-inputs.json in the audit receipt.

The preserved Mac transfer recipe in docs/BABEL_HANDOFF.md copied data plus selected runs/investigation,but omitted seeds/ and runs/rubric-paraphrases/. This explains the scope of missing generated pools;it does not explain the intentional tuning split,which predates migration. Current canonical YAMLs are therefore **data-complete but not input-pool launch-ready** on Babel.

Hugging Face cannot restore model-generated seeds or paraphrases. GITHUB_BACKUP.md and current public release metadata document native-prompt-results20 seeds and red-team-results20 paraphrases in revision-seeds-paraphrases.tar.gz,1619400925bytes,SHA-256155706072d6c4f5647c7b8f8b409fe3abc005049c23b99175fb23324fbfee24a. No dev3 pool is documented in that release. The archive has not been downloaded or inspected internally in this audit,so do not claim old seeds pass current validation. Recovery must preserve archive/member provenance,stage without overwriting outputs,and use only genuine current validation. Never fabricate old-run resume compatibility;unsupported historical inputs require the current workflow,not renamed metadata.

An asynchronous question requests a Babel-accessible Mac dev3 backup path. Continue active policy jobs meanwhile. Before full dev3/Result20,resolve the missing generated pools and exact frozen seed identity;do not silently substitute newly generated seeds for the user's saved ones.

## Model/runtime and cleanup

README Gemini3.6 is corrected to **Gemini3.8 Flash**. Both canonical YAMLs and default panel already use Sol/Opus/Gemini3.8;provider thinking remains low and Sol/Opus settings unchanged. Historical model/price records are preserved. No provider call was made:existing Gemini429/prepayment-credit failure remains in force. Current Sol/Opus job configs are unchanged.

README now states canonical task IDs and Python3.12/frozen uv/shared60 Slurm guidance;historical Mac handoff has an explicit supersession banner. Cleanup policy is docs/RUNS_CLEANUP_POLICY.md;no run removed. Full three-task dev3 validation plus quality-preserving policy evidence still precede Result20. Existing jobs10356519/10356523 remain owned and uninterrupted.

Evidence directory:runs/babel-overnight-20260907/biomnibench-data-audit-20260908. inventory.json contains all442 hashes and canonical config hashes;hf-main.json and hf-e1c8ca5e11a620087bc48d97888eb69176a1f235.json preserve upstream metadata;generated-inputs.json separates missing generated pools;github-release-inventory.json records remote backup digests. The private audit_biomnibench_data.py only reads source data and writes a new report. No dataset restoration allocation was needed because all canonical files were intact.
