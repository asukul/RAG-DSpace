#!/bin/bash
# Generic single-GPU Python batch job on Nova (fine-tune / OCR / experiment).
# Mirrors the validated tenants/prt/scripts/lora_corrector/nova/train_lora.slurm.
#
# Submit:  ssh nova 'cd <dir> && sbatch gpu_python.slurm'
# VERIFY before first use:  ssh nova 'sinfo -o "%P %G"'   (confirm the --gres token)

#SBATCH --job-name=gpu-py
#SBATCH --gres=gpu:a100:1          # A100 80GB SXM (verified 2026-05-20).
                                   # AVOID gpu:a100-pcie (40GB, OOM risk) and gpu:gh200 (ARM, no x86 wheels).
#SBATCH --cpus-per-task=8
#SBATCH --mem=64G
#SBATCH --time=08:00:00
#SBATCH --output=gpu-py-%j.out
#SBATCH --error=gpu-py-%j.out

set -euo pipefail

# Compute nodes have no internet — rely on what was staged on the login node.
export HF_HUB_OFFLINE=1
export TRANSFORMERS_OFFLINE=1
export PYTHONUNBUFFERED=1
module load cuda 2>/dev/null || true

PY="${PY:-$HOME/venv/bin/python}"   # venv built on the login node via uv

echo "host=$(hostname) job=$SLURM_JOB_ID $(date -u +%FT%TZ)"
nvidia-smi --query-gpu=name,memory.total --format=csv,noheader || true

# --- EDIT: your command ---
"$PY" your_script.py --arg value

echo "done $(date -u +%FT%TZ)"
