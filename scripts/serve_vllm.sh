#!/usr/bin/env bash
set -euo pipefail

model="${1:-Qwen/Qwen3.6-27B}"
port="${2:-43117}"
environment="${3:-vllm}"
tensor_parallel_size="${4:-1}"
endpoint_path="${5:-runs/vllm-endpoints/qwen.endpoint}"

source /juice2/u/abehou/anaconda3/etc/profile.d/conda.sh
conda activate "$environment"
cd /nlp/scr/abehou/rubric_gen
mkdir -p "$(dirname "$endpoint_path")"
if [[ -f "$endpoint_path" ]]; then
  mv "$endpoint_path" "$endpoint_path.stale-${SLURM_JOB_ID:-$$}"
fi

command -v vllm >/dev/null || {
  echo "vllm is not installed in conda environment: $environment" >&2
  exit 1
}

vllm serve "$model" \
  --host 0.0.0.0 \
  --port "$port" \
  --tensor-parallel-size "$tensor_parallel_size" &
server_pid=$!
trap 'kill "$server_pid" 2>/dev/null || true' EXIT TERM INT

until curl -fsS "http://127.0.0.1:$port/health" >/dev/null; do
  kill -0 "$server_pid" 2>/dev/null || { wait "$server_pid"; exit $?; }
  sleep 2
done
specification="http://$(hostname -s):$port/v1::$model"
printf '%s\n' "$specification" > "$endpoint_path"
printf 'ready: %s\n' "$specification"
wait "$server_pid"
