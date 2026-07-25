#!/usr/bin/env bash
set -euo pipefail

mode="${1:-submit}"
environment="${2:-vllm}"
runner="${3:-nlprun}"
if [[ "$mode" != "submit" && "$mode" != "test" ]]; then
  echo "usage: $0 [submit|test] [conda-environment]" >&2
  exit 2
fi

cd /nlp/scr/abehou/rubric_gen
mkdir -p logs/vllm
dry_run=()
[[ "$mode" == "test" ]] && dry_run=(test)

"$runner" -m sphinx9 -g 1 -r 120G -t 1-0 -p low \
  -n malt-qwen36 -o logs/vllm/qwen36.out \
  "bash scripts/serve_vllm.sh Qwen/Qwen3.6-27B 43117 '$environment' 1" "${dry_run[@]}"

"$runner" -m sphinx10 -g 1 -r 120G -t 1-0 -p low \
  -n malt-glm47 -o logs/vllm/glm47.out \
  "bash scripts/serve_vllm.sh zai-org/GLM-4.7-Flash 44783 '$environment' 1" "${dry_run[@]}"

"$runner" -m sphinx11 -g 1 -r 120G -t 1-0 -p low \
  -n malt-gpt-oss -o logs/vllm/gpt-oss.out \
  "bash scripts/serve_vllm.sh openai/gpt-oss-120b 45991 '$environment' 1" "${dry_run[@]}"
