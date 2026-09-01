#!/usr/bin/env bash
#SBATCH --job-name=biomni-r20-direct-cleanup
#SBATCH --account=nlp
#SBATCH --partition=john
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=24
#SBATCH --mem=96G
#SBATCH --gres=gpu:0
#SBATCH --time=02:00:00
#SBATCH --output=runs/slurm/biomni-r20-direct-cleanup-%j.out
#SBATCH --error=runs/slurm/biomni-r20-direct-cleanup-%j.err

set -euo pipefail

readonly PROJECT_ROOT=/juice2/scr2/abehou/rubric_gen
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

exec .venv/bin/python -c '
from pathlib import Path

from rubric_gen.submission_revision.detection_windows import RevisionDetectionWindow
from rubric_gen.submission_revision.evaluation.direct import DirectDetectionConfig, run_direct_detection
from rubric_gen.submission_revision.experiment import load_experiment

experiment = load_experiment(Path("experiments/biomnibench-results20-user-simulator-full.yaml").resolve())
raise SystemExit(run_direct_detection(DirectDetectionConfig(
    experiment=experiment,
    study_dir=Path("runs/studies/biomnibench-da-factorial-r10-4f4d5d178756").resolve(),
    output_dir=Path("runs/detections/biomnibench-da-factorial-r10-4f4d5d178756/direct_full").resolve(),
    max_concurrency=16,
    resume=True,
    window=RevisionDetectionWindow.FULL_TRAJECTORY,
)))
'
