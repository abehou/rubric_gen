#!/usr/bin/env bash
#SBATCH --job-name=biomni-r20-detect
#SBATCH --account=nlp
#SBATCH --partition=john
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=24
#SBATCH --mem=96G
#SBATCH --gres=gpu:0
#SBATCH --time=08:00:00
#SBATCH --output=runs/slurm/biomni-r20-detect-%j.out
#SBATCH --error=runs/slurm/biomni-r20-detect-%j.err

set -euo pipefail

readonly PROJECT_ROOT=/juice2/scr2/abehou/rubric_gen
readonly EXPERIMENT=experiments/biomnibench-results20-user-simulator-full.yaml
readonly STUDY=runs/studies/biomnibench-da-factorial-r10-4f4d5d178756
readonly STUDY_MANIFEST="$STUDY/study.json"
readonly DETECT_CONCURRENCY=16
readonly GEMINI_KEY_FILE="$PROJECT_ROOT/runs/secrets/gemini_api_key"

cd "$PROJECT_ROOT"

if [[ ! -r "$GEMINI_KEY_FILE" ]]; then
    echo "Gemini API key file is missing or unreadable." >&2
    exit 1
fi
export GEMINI_API_KEY
GEMINI_API_KEY="$(<"$GEMINI_KEY_FILE")"
if [[ -z "$GEMINI_API_KEY" ]]; then
    echo "Gemini API key file is empty." >&2
    exit 1
fi
unset GOOGLE_API_KEY

while true; do
    study_status="$(.venv/bin/python -c \
        'import json,sys; print(json.load(open(sys.argv[1]))["status"])' \
        "$STUDY_MANIFEST")"
    case "$study_status" in
        completed|failed)
            break
            ;;
        pending|running)
            sleep 30
            ;;
        *)
            echo "Unexpected study status: $study_status" >&2
            exit 1
            ;;
    esac
done

exec .venv/bin/rubric-gen detect \
    --experiment "$EXPERIMENT" \
    --study-dir "$STUDY" \
    --max-concurrency "$DETECT_CONCURRENCY" \
    --resume
