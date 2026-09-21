#!/usr/bin/env bash
#SBATCH --partition=general
#SBATCH --gres=gpu:1
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=4
#SBATCH --mem=32G
#SBATCH --time=00:30:00
#SBATCH --no-requeue
#SBATCH --account=dfried
#SBATCH --job-name=r40fb-config
#SBATCH --output=/home/aydanh/runs/r40fb-config-%j.out
#SBATCH --error=/home/aydanh/runs/r40fb-config-%j.err
source experiments/trace-v21-execution-verified-provenance-result40-feedback/common.sbatch
exec /home/aydanh/repos/rubric_gen/.venv/bin/python \
  experiments/trace-v21-execution-verified-provenance-result40-feedback/make_configs.py
