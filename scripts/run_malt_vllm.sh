#!/usr/bin/env bash
set -euo pipefail

environment="${1:-harness}"
output_dir="${2:-${BULK:?BULK must be set}/rubric_gen/runs/malt-benchmark}"
top="${3:-100}"

source /juice2/u/abehou/anaconda3/etc/profile.d/conda.sh
conda activate "$environment"
cd /nlp/scr/abehou/rubric_gen

uv run malt \
  --output-dir "$output_dir" \
  --vllm-ensemble \
  --top "$top" \
  --seed 42 \
  --max-concurrency 30
