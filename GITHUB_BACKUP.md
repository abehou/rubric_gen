# Aydan red-team backup — 2026-09-06

Branch: `aydan-red-team` in `abehou/rubric_gen`.

This is a backup of the completed Results20 v7 experiment: 240 assignments,
seven audit stages, 9,327 unique judgments, Luna solver/proposer and
Sol / Claude Opus 5 / Gemini 3.8 Flash audits. See the
[report](runs/reports/20260905-redteam-v7/REPORT.md) and
[coverage receipt](runs/reports/20260905-redteam-v7/audit-coverage-complete.json).

## Download the original experiment outputs

Large outputs are GitHub Release assets, not Git blobs or Git LFS pointers:

https://github.com/abehou/rubric_gen/releases/tag/aydan-red-team-backup-20260906

| Asset | Contents restored under repository root |
| --- | --- |
| `revision-seeds-paraphrases.tar.gz` | Complete `runs/studies/20260905-redteam-v7`, the referenced `seeds/biomnibench/native-prompt-results20`, and `runs/rubric-paraphrases/biomnibench/red-team-results20` |
| `audits-reports-acceptance.tar.gz` | Complete three-model audit-v2 outputs, final reports, provider-availability-v7 small acceptance study/audit, and the local `runs/logs` snapshot |
| `provenance.tar.gz` | Complete `runs/provenance/20260905-redteam-v7`, including frozen sources, historical attempts, recovery archives, and final verification archives |

Exact asset bytes and SHA-256 values are in
[GITHUB_BACKUP_MANIFEST.json](GITHUB_BACKUP_MANIFEST.json). Each archive is below
GitHub's per-release-asset limit. Repository code, readable reports, and private
analysis/recovery helpers are committed directly to the branch.

## Restore

Clone this branch into a **new directory**, download the three assets into that
directory, verify their SHA-256 values against the manifest (`shasum -a 256
<asset>` on macOS), then extract from the repository root:

```sh
tar -xzf revision-seeds-paraphrases.tar.gz
tar -xzf audits-reports-acceptance.tar.gz
tar -xzf provenance.tar.gz
```

Do not extract over a newer working experiment. The archives preserve the
original relative directory layout and unmodified experiment records, including
original absolute provenance paths. Do not replace old path strings or hashes
to pretend the results were generated elsewhere; current validation may require
the original layout for identity-sensitive resume operations. Reading reports
and raw records does not require provider keys.

## Scope and privacy

The user explicitly approved public upload of complete experiment outputs on
2026-09-06. API credentials, `.env*`, local environments, and external account
configuration are excluded. Local scans check configured provider secrets,
common provider/GitHub key signatures, private-key headers, and sensitive
filenames without printing secret values. Scanning is a precaution, not proof
that arbitrary sensitive information can never exist in a model transcript.

This backup includes v7 formal outputs and its acceptance/recovery evidence,
not every unrelated historical study in the local `runs/` directory. The source
benchmark dataset directory `data/`, package environments, and external Codex
account/session stores are not bundled; install dependencies and obtain any
required benchmark inputs separately before attempting new runs. The complete
saved v7 generation/evaluation artifacts and referenced seed outputs are bundled.

The backup commit is newer than the frozen experimental source identity because
it adds reports, backup documentation, and helpers. Preserve and consult the
archived runtime source/provenance when interpreting the completed experiment.
