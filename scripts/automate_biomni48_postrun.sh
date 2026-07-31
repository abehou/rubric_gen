#!/usr/bin/env bash
set -uo pipefail

REPO="/juice2/scr2/abehou/rubric_gen"
TASKS="${REPO}/data/biomnibench-da"
SEEDS="${REPO}/runs/biomnibench-seeds/codex-luna-top4"
STATIC="${REPO}/runs/biomnibench-revisions/static_base_vs_diligent"
AGENT="${REPO}/runs/biomnibench-revisions/agent_evolution_base_vs_diligent"
AUTOMATION="${REPO}/runs/automation/biomni48-postrun-20260728"
RH_OUTPUT="${REPO}/runs/malt-runs/biomni-rh-all48-automated"
RF_OUTPUT="${REPO}/runs/biomnibench-rubric-free/all48-automated"
MAX_EVALUATION_ATTEMPTS=20

mkdir -p "${AUTOMATION}"
cd "${REPO}" || exit 1

log() {
  printf '%s %s\n' "$(date --iso-8601=seconds)" "$*"
}

batch_files=(
  "${STATIC}"/{base,diligent}/{full,semi,score_only}/batch.json
  "${AGENT}"/{base,diligent}/{full,semi,score_only}/batch.json
)

log "Waiting for the 12 original batches to leave running state."
while :; do
  running=0
  for batch in "${batch_files[@]}"; do
    if [[ ! -f "${batch}" || "$(jq -r '.status' "${batch}")" == "running" ]]; then
      running=$((running + 1))
    fi
  done
  (( running == 0 )) && break
  log "Original batches still running: ${running}/12"
  sleep 60
done

resume_static_failure() {
  uv run biomnibench-agent revise \
    "${TASKS}/da-11-1" \
    --seed-run-dir "${SEEDS}" \
    --experiment-dir "${STATIC}/base/full/da-11-1" \
    --revision-rounds 10 --provider codex --model gpt-5.6-luna \
    --judge gpt-5.6-luna --rubric rubric.txt --feedback-policy full \
    --rubric-evolution static --prompt base --review trace \
    --sandbox --allow-network --retries 5 --resume
}

resume_agent_full_failure() {
  uv run biomnibench-agent revise \
    "${TASKS}/da-11-1" \
    --seed-run-dir "${SEEDS}" \
    --experiment-dir "${AGENT}/diligent/full/da-11-1" \
    --revision-rounds 10 --provider codex --model gpt-5.6-luna \
    --judge gpt-5.6-luna --rubric rubric.txt --feedback-policy full \
    --rubric-evolution agent --rubric-proposer-model gpt-5.6-luna \
    --rubric-proposer-step-limit 12 --prompt diligent --review trace \
    --sandbox --allow-network --retries 5 --resume
}

resume_agent_score_failure() {
  uv run biomnibench-agent revise \
    "${TASKS}/da-10-3" \
    --seed-run-dir "${SEEDS}" \
    --experiment-dir "${AGENT}/diligent/score_only/da-10-3" \
    --revision-rounds 10 --provider codex --model gpt-5.6-luna \
    --judge gpt-5.6-luna --rubric rubric.txt --feedback-policy score_only \
    --rubric-evolution agent --rubric-proposer-model gpt-5.6-luna \
    --rubric-proposer-step-limit 12 --prompt diligent --review trace \
    --sandbox --allow-network --retries 5 --resume
}

recoveries=(
  "${STATIC}/base/full/da-11-1/state.json:resume_static_failure"
  "${AGENT}/diligent/full/da-11-1/state.json:resume_agent_full_failure"
  "${AGENT}/diligent/score_only/da-10-3/state.json:resume_agent_score_failure"
)

for recovery in "${recoveries[@]}"; do
  state=${recovery%%:*}
  function_name=${recovery#*:}
  attempt=0
  while [[ "$(jq -r '.phase' "${state}")" != "completed" ]]; do
    phase=$(jq -r '.phase' "${state}")
    state_age=$(( $(date +%s) - $(stat -c %Y "${state}") ))
    if [[ "${phase}" != "failed_turn" && ${state_age} -lt 600 ]]; then
      log "Recovery target is already active (${phase}, age ${state_age}s): ${state}"
      sleep 60
      continue
    fi
    attempt=$((attempt + 1))
    log "Recovery ${function_name}, attempt ${attempt}."
    "${function_name}" || true
    [[ "$(jq -r '.phase' "${state}")" == "completed" ]] && break
    if (( attempt >= 20 )); then
      log "Recovery exhausted for ${state}."
      touch "${AUTOMATION}/FAILED"
      exit 1
    fi
    sleep 60
  done
done

shopt -s nullglob
experiments=(
  "${STATIC}"/{base,diligent}/{full,semi,score_only}/da-*
  "${AGENT}"/{base,diligent}/{full,semi,score_only}/da-*
)
if (( ${#experiments[@]} != 48 )); then
  log "Expected 48 experiments, found ${#experiments[@]}."
  touch "${AUTOMATION}/FAILED"
  exit 1
fi
for experiment in "${experiments[@]}"; do
  if [[ "$(jq -r '.phase' "${experiment}/state.json")" != "completed" ]]; then
    log "Experiment is not complete after recovery: ${experiment}"
    touch "${AUTOMATION}/FAILED"
    exit 1
  fi
done
touch "${AUTOMATION}/ALL_48_REVISIONS_COMPLETE"

run_dirs=(
  "${STATIC}"/{base,diligent}/{full,semi,score_only}
  "${AGENT}"/{base,diligent}/{full,semi,score_only}
)

for ((attempt=1; attempt<=MAX_EVALUATION_ATTEMPTS; attempt++)); do
  log "MALT reward-hacking audit attempt ${attempt}."
  resume_args=()
  (( attempt > 1 )) && resume_args+=(--resume)
  uv run malt \
    --detect rh \
    --biomnibench-run-dir "${run_dirs[@]}" \
    --tasks-dir "${TASKS}" \
    --agent-ensemble --agent-step-limit 12 \
    --max-retries 5 --max-concurrency 6 \
    --output-dir "${RH_OUTPUT}" \
    "${resume_args[@]}" && {
      touch "${AUTOMATION}/MALT_RH_COMPLETE"
      break
    }
  sleep 120
done
if [[ ! -f "${AUTOMATION}/MALT_RH_COMPLETE" ]]; then
  log "MALT reward-hacking audit exhausted retries."
  touch "${AUTOMATION}/FAILED"
  exit 1
fi

run_args=()
for experiment in "${experiments[@]}"; do
  run_args+=(--run-dir "${experiment}")
done
for ((attempt=1; attempt<=MAX_EVALUATION_ATTEMPTS; attempt++)); do
  log "Rubric-free evaluation attempt ${attempt}."
  uv run biomnibench-agent rubric-free \
    "${run_args[@]}" \
    --output-dir "${RF_OUTPUT}" \
    --models gpt-5.6-sol claude-opus-4-8 gemini-3.1-pro-preview \
    --max-concurrency 6 --max-retries 5 --resume && {
      touch "${AUTOMATION}/RUBRIC_FREE_COMPLETE"
      break
    }
  sleep 120
done
if [[ ! -f "${AUTOMATION}/RUBRIC_FREE_COMPLETE" ]]; then
  log "Rubric-free evaluation exhausted retries."
  touch "${AUTOMATION}/FAILED"
  exit 1
fi

touch "${AUTOMATION}/SUCCESS"
log "All 48 revisions, MALT RH detection, and rubric-free judging completed."
