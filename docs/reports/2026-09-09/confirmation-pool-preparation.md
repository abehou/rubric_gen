# BioMNIBench confirmation shared-input preparation

Preparation only; no induction, revision, downstream scoring or audit is authorized by this side task.

The pre-existing Results45 inventory from2026-09-08 is retained without outcome selection. Results30 is original20 plus the first10 additional tasks in that same frozen order. Both tiers use3replicates, randomization seed20260820, native base seed profile and configured gpt-5.6-luna low model; paraphrases retain count5, selected0/development1, gpt-5.6-luna and existing retry settings. Exact lists/settings and source hashes: `investigation/confirmation-pools-20260909/freeze.json`. Frozen execution source1314fac will be used; no new downstream outcomes inform this preparation.

## Prerequisites

The previous shared canonical-data restoration stopped at HTTP401 GatedRepoError for the first additional task. A new read-only Slurm check inspects both repository and shared storage and credential presence without printing credentials or making provider calls. No repeat anonymous download is authorized as a workaround. Full canonical file hashes must pass before generation; size checks alone are insufficient.

Native seed generation includes a separate adversarial seed artifact and an initial rubric judgment. Clarification has been requested whether the instruction to stop before scoring permits these existing seed-stage components. No seed call until that boundary is resolved; no fabricated score/compatibility metadata.

## Reuse and sealing

Validate the existing20task pools natively and preserve successful cells. New pool material must retain original provenance; never overwrite the historical pool. Before static or dynamic consumption, validate both consumers against the same shared seed/paraphrase paths and compare task/replicate artifact hashes and selected/heldout paraphrase hashes byte-for-byte. Seal completed pool files and a complete hash/provenance receipt; keep failures and logs outside the sealed content. Do not claim expansion coverage or resume compatibility until native checks pass.

Planned coverage: Results30=90seed blocks/150paraphrase variants; Results45=135seed blocks/225variants. Existing20task material is reusable only after validation. No new successful generation is claimed yet.

## 11:44 EDT — data prerequisite checked

Data-only job10372102 completed. Both repository and shared destination contain only the original20tasks by file presence/size; all25frozen additions are missing. No configured Hugging Face credential was found. Earlier pinned download returned401GatedRepoError; no repeat anonymous download or generation attempted. Existing authorized credential/data path requested, without requesting token text. Thus no new seed/paraphrase cells generated; expansion coverage remains0/25newtasks. Native seed-stage scoring clarification is also still pending. Current Result20 is unaffected,43/60revisions complete at this check.

## Authenticated download resumed

User verified cachedHFloginKira265; job10372571 uses the standard cached login with token=True, without reading/printing/copying credential content. Frozen additional-only download now progresses,37/45tasks hash-verified at the latest check. Prior authentication failure logs retained. New generation remains held by the subsequently requested login/compute storage-access gate and native seed-stage scoring clarification.
