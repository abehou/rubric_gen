# Canonical compute-only storage — verified checkpoint

All new large datasets, seed/paraphrase pools, revision workspaces, and caches belong under `/data/user_data/aydanh/rubric_gen/`. This persistent NFS4 mount (`nas8:/data/user_data/aydanh`) is accessible across Slurm compute nodes; direct login-node visibility is neither expected nor required. Perform all access, validation, and generation through Slurm. Do not use symlinks to bypass native validation.

Keep code, configurations, launchers, manifests, provenance/hash receipts, and small reports in the home repository. Preserve existing validated home-based Results20 data and historical outputs unchanged. Do not rewrite historical launch configurations. Every newly prepared sbatch execution configuration must resolve large-data inputs and outputs to absolute paths under the canonical root, including paths supplied by its Python launcher or YAML.

## Completed data and pool validation

| Content | Canonical destination (under `/data/user_data/aydanh/rubric_gen/`) | Verified coverage | Evidence |
|---|---|---|---|
| BioMNIBench | `data/biomnibench-da-results45-e1c8ca5e11a6` | 45 tasks, 646 files, 82,681,231,433 bytes | Download 10372571; independent compute validation 10372829 |
| PaperBench | `data/paperbench-51052cede8cc/{all,dev}` | 20 results + 3 dev papers, 479 files, 89,097,628 bytes | Native validation 10372686 |
| BioMNIBench paraphrases | `pools/paraphrases/biomnibench/confirmation-20260909/{original20,additional25}` | 45 tasks, 225 variants; original20 reused, additional25 generated | Job 10372893; both static/trace consumers validated; pools sealed |

BioMNIBench source is frozen `phylobio/BiomniBench-DA@e1c8ca5e11a620087bc48d97888eb69176a1f235`; all files passed canonical Git-blob/LFS checks and SHA256 receipt verification. The 25 additions account for 82,195,617,343 bytes. Existing validated home data were preserved. Authentication reused the cached Hugging Face login without exposing or copying its token.

PaperBench uses the native downloader's frozen `openai/frontier-evals@51052cede8cc608f95bb00346635e03759013e5a`. The prior DNS-failed attempt 10372604 remains recorded; retry 10372686 passed native validation and recorded all file hashes. No PaperBench scientific stages ran.

Independent BioMNIBench validation on babel-l5-16 reported 351,072,681,984 free bytes (approximately 327 GiB) on the 2 TiB mount. This is a checkpoint measurement, not a promise of future capacity. Cross-node operation was also established on babel-l5-28.

## Durable receipts

- `runs/confirmation-data-validated-10372829/result.json`
- `runs/results45-data-prepare-10372571/result.json`
- `runs/paperbench-data-prepare-10372686/result.json`
- `runs/confirmation-paraphrases-10372893/result.json`

## Future generation paths and boundary

- Seeds: `/data/user_data/aydanh/rubric_gen/seeds/biomnibench/confirmation-20260909`.
- Revision/artifact outputs: versioned directories under `/data/user_data/aydanh/rubric_gen/runs/`.
- Workspaces: `/data/user_data/aydanh/rubric_gen/live/`.
- Large caches: `/data/user_data/aydanh/rubric_gen/cache/`.

No new confirmation seed generation, rubric induction, revision, scoring, or auditing has launched. Native seed includes initial scoring and an adversarial artifact; the requested stop-before-scoring boundary still needs resolution before invoking it. Prepared pool-consumer configurations are input validation configurations, not an approved confirmatory scientific treatment. Storage is no longer a blocker.
