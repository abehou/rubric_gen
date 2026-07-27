#!/usr/bin/env bash
set -euo pipefail

detection="${1:?usage: run_malt_vllm.sh DETECTION [ENVIRONMENT] [OUTPUT_DIR] [TOP]}"
environment="${2:-harness}"
output_dir="${3:-runs/malt-runs}"
top="${4:-100}"

source /juice2/u/abehou/anaconda3/etc/profile.d/conda.sh
conda activate "$environment"
cd /nlp/scr/abehou/rubric_gen

uv run malt \
  --detect "$detection" \
  --output-dir "$output_dir" \
  --vllm-ensemble \
  --top "$top" \
  --seed 42 \
  --max-concurrency 30
