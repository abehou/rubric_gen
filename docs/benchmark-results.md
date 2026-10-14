# Benchmark results

This branch, `codex/biomnibench-results`, owns BioMNIBench results and the saved PaperBench/Harvey work. HealthBench and ResearchQA remain on `codex/healthbench-researchqa`; `main` is unchanged.

| Benchmark / experiment | Saved scope and status | Report |
|---|---|---|
| BioMNIBench current Result40 | Complete40 tasks × eight conditions × three replicates; separate Sol/Opus-group and average tables, all accepted corrections | [Current Result40](reports/2026-10-13/biomnibench-result40/README.md) |
| BioMNIBench Original20 | Historical20-task report and figures retained | [Original20](reports/2026-10-12/biomnibench-original20/README.md) |
| BioMNIBench dropout | Saved development comparison | [Dropout comparison](reports/2026-09-18/trace-v21-provenance-high-proposer-dropout/README.md) |
| BioMNIBench heldout / execution diagnostics | Saved five-heldout, neutral and evidence-calibrated analyses; separate from current primary Result40 | [Heldout analyses](reports/2026-09-21/trace-v21-complete-public-regression/README.md) · [Development-gap analysis](reports/2026-09-21/trace-v21-result40-development-gap/README.md) |
| PaperBench corrected static Results20 | Complete120 revisions; Sol/Opus and required audit stages complete | [Final baseline](reports/2026-09-12/paperbench-static/selected-neutral-heldout-rigorous-results20-final.md) |
| PaperBench promoted RTT Dev3 | Complete18 assignments and520 logical audit outcomes; no RTT Result20 was launched | [RTT Dev3](reports/2026-09-19/paperbench-rtt-provenance-dev3/README.md) |
| PaperBench completion-control Dev3 | Complete18 assignments and520 logical audit outcomes; candidate not promoted | [Completion control](reports/2026-09-20/paperbench-rtt-completion-control-dev3/README.md) |
| PaperBench foundational mechanism smoke | Development smoke retained separately | [Mechanism smoke](reports/2026-09-20/paperbench-rtt-foundational-control-mechanism-smoke/README.md) |
| Harvey RTT | Harness, Dev3 configuration and complete original branch history retained; saved formal run remains incomplete, not a completed Result20 | [Harness](harvey_harness_evolution.md) · [Original source/checkpoints](https://github.com/abehou/rubric_gen/tree/c648c9e1f4618a4c5ee7e887ba992ad0fe542909) |

The original experiment versions are retained in the consolidation merge history. Historical pilot configurations and scripts require their corresponding source commits; the active runtime was not changed merely to collect results. [Branch/source inventory](reports/2026-10-13/branch-consolidation/README.md) records where each retired branch's work was retained.
