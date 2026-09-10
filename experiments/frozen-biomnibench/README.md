# Frozen BioMNIBench baseline configurations

The formal conditions are **Full feedback** and **User simulator**, crossed with **Static rubric** and **Red-team trace**. The accepted baseline and available outcomes are in the [checkpoint report](../../docs/reports/2026-09-09/baseline-freeze/README.md).

These YAMLs are byte-identical provenance snapshots of the producing configurations, with hashes and original paths in [manifest.json](manifest.json). **Do not launch these snapshots against their historical output directories.** They preserve execution scopes, internal condition IDs, source pools and provider settings; they are not new-run or fabricated resume configurations. Later runs require explicitly authorized fresh output paths under `/data/user_data/aydanh/rubric_gen/` and native compatibility validation of shared inputs.

The generic `biomnibench-dev3.yaml` and `biomnibench-results20.yaml` retain the benchmark inventory/full-factorial design. This directory identifies the accepted four-cell research checkpoint; other experimental YAMLs and investigation scripts are historical, not accepted method choices.

Internal provenance: simulator version `rubric-cue`; scientific implementation0fbe0bb plus scoped input reuse314ea3d and duplicate evidence30ae38e, assembled as7cf34ef. The active scientific source exactly matches that assembly. Restoring source does not change producer identities or make prior generation caches compatible with a changed implementation hash.
