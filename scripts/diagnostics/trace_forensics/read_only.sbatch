#!/bin/bash
#SBATCH --job-name=trace-forensic-readonly
#SBATCH --partition=preempt
#SBATCH --qos=preempt_cpu_qos
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=4
#SBATCH --mem=64G
#SBATCH --time=04:00:00
#SBATCH --chdir=/home/aydanh/repos/rubric_gen
#SBATCH --output=/home/aydanh/repos/rubric_gen/runs/slurm-%x-%j.out
#SBATCH --export=NONE
set -euo pipefail
unset OPENAI_API_KEY ANTHROPIC_API_KEY GEMINI_API_KEY GOOGLE_API_KEY
echo 'Read-only forensic allocation; saved-artifact inspection only; no providers or workflow stages.'
exec /bin/sleep 14400
