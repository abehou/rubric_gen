#!/usr/bin/env bash
set -euo pipefail

detection="${1:?usage: run_malt_vllm.sh DETECTION [OUTPUT_DIR] [TOP]}"
output_dir="${2:-runs/malt-runs}"
top="${3:-100}"

project_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$project_root"

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
