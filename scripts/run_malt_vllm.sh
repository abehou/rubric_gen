#!/usr/bin/env bash
set -euo pipefail

detection="${1:?usage: run_malt_vllm.sh DETECTION [ENVIRONMENT] [OUTPUT_DIR] [TOP]}"
environment="${2:-harness}"
output_dir="${3:-runs/malt-runs}"
top="${4:-100}"

source /juice2/u/abehou/anaconda3/etc/profile.d/conda.sh
conda activate "$environment"
cd /nlp/scr/abehou/rubric_gen

read -r qwen27_endpoint < runs/vllm-endpoints/qwen36-27b.endpoint
read -r qwen35_endpoint < runs/vllm-endpoints/qwen36-35b-a3b.endpoint

uv run malt \
  --detect "$detection" \
  --output-dir "$output_dir" \
  --vllm "$qwen27_endpoint" \
  --vllm "$qwen35_endpoint" \
  --top "$top" \
  --seed 42 \
  --max-concurrency 30
