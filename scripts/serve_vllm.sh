#!/usr/bin/env bash
set -euo pipefail

model="${1:?usage: serve_vllm.sh MODEL PORT VENV TENSOR_PARALLEL_SIZE ENDPOINT_PATH HF_HOME}"
port="${2:-43117}"
venv="${3:-.vllm-venv}"
tensor_parallel_size="${4:-8}"
endpoint_path="${5:-runs/vllm-endpoints/qwen36-27b.endpoint}"
hf_home="${6:-/juice2/u/nlp/data/abe_models/huggingface}"

project_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$project_root"
mkdir -p "$(dirname "$endpoint_path")"
mkdir -p "$hf_home"
export HF_HOME="$hf_home"
if [[ -f "$endpoint_path" ]]; then
  mv "$endpoint_path" "$endpoint_path.stale-${SLURM_JOB_ID:-$$}"
fi

vllm_executable="$venv/bin/vllm"
if [[ ! -x "$vllm_executable" ]]; then
  echo "vLLM is not installed at $vllm_executable" >&2
  echo "Run: UV_PROJECT_ENVIRONMENT=$venv uv sync --extra vllm" >&2
  exit 1
fi

"$vllm_executable" serve "$model" \
  --host 0.0.0.0 \
  --port "$port" \
  --tensor-parallel-size "$tensor_parallel_size" \
  --max-model-len 262144 \
  --reasoning-parser qwen3 \
  --enable-auto-tool-choice \
  --tool-call-parser qwen3_coder \
  --language-model-only &
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
