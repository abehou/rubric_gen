#!/usr/bin/env bash
set -euo pipefail

mode="${1:-submit}"
venv="${2:-.vllm-venv}"
runner="${3:-nlprun}"
if [[ "$mode" != "submit" && "$mode" != "test" ]]; then
  echo "usage: $0 [submit|test] [vllm-virtual-environment] [nlprun-command]" >&2
  exit 2
fi

project_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$project_root"
mkdir -p logs/vllm
mkdir -p runs/vllm-endpoints
dry_run=()
[[ "$mode" == "test" ]] && dry_run=(test)

"$runner" -q sphinx -d h100 -g 8 -c 16 -r 256G -t 1-0 -p low \
  -n qwen36-27b -o logs/vllm/qwen36-27b.out \
  "bash scripts/serve_vllm.sh Qwen/Qwen3.6-27B 43117 $venv 8 runs/vllm-endpoints/qwen36-27b.endpoint" "${dry_run[@]}"

"$runner" -q sphinx -d h200 -g 8 -c 16 -r 256G -t 1-0 -p low \
  -n qwen36-35b-a3b -o logs/vllm/qwen36-35b-a3b.out \
  "bash scripts/serve_vllm.sh Qwen/Qwen3.6-35B-A3B 43583 $venv 8 runs/vllm-endpoints/qwen36-35b-a3b.endpoint" "${dry_run[@]}"
