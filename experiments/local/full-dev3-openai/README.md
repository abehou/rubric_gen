# Full Dev3 OpenAI-only matrix

These configs run the complete repository-defined Dev3 factorial for one Luna
solver: three tasks, three replicates, and all twelve feedback-by-rubric
conditions, for 108 assignments per benchmark. They preserve the official
randomization and protocol, use local data and output paths, and restrict the
outcome-audit panel to GPT-5.6 Sol; all generation, revision, feedback, in-loop
grading, paraphrasing, and rubric-proposal roles remain GPT-5.6 Luna.

Run the stages in dependency order with `--resume`:

```bash
uv run rubric-gen seed --experiment experiments/local/full-dev3-openai/biomnibench-luna-full-matrix-sol-audit.yaml --max-concurrency 3
uv run rubric-gen paraphrase --experiment experiments/local/full-dev3-openai/biomnibench-luna-full-matrix-sol-audit.yaml --max-concurrency 3
uv run rubric-gen revise --experiment experiments/local/full-dev3-openai/biomnibench-luna-full-matrix-sol-audit.yaml --max-concurrency 3 --resume
uv run rubric-gen detect --experiment experiments/local/full-dev3-openai/biomnibench-luna-full-matrix-sol-audit.yaml --max-concurrency 3 --resume
```

Use the corresponding PaperBench YAML for that benchmark. The seed and
paraphrase paths intentionally reuse the already sealed Luna Dev3 pools.
