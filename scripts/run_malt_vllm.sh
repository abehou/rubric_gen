#!/usr/bin/env bash
set -euo pipefail

environment="${1:-harness}"
data_glob="${2:-data/malt-public/default/*.parquet}"
output_dir="${3:-runs/malt-benchmark}"

source /juice2/u/abehou/anaconda3/etc/profile.d/conda.sh
conda activate "$environment"
cd /nlp/scr/abehou/rubric_gen

# Intentional word splitting expands the caller-controlled dataset glob.
# shellcheck disable=SC2086
uv run malt $data_glob \
  --output-dir "$output_dir" \
  --positive-label bypass_constraints \
  --positive-label hardcoded_solution \
  --positive-label partial_problem_solving \
  --positive-label sabotage \
  --positive-label gives_up \
  --negative-label normal \
  --vllm-ensemble \
  --max-concurrency 30 \
  --resume
