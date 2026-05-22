#!/bin/bash
# Train the Typhoon-corrector LoRA on ISU Nova (single A100 80GB).
#
# Submit from the repo dir on Nova:
#   sbatch tenants/prt/scripts/lora_corrector/nova/train_lora.slurm
#
# NOTE: confirm the exact --gres / partition syntax with Nova's Slurm Script
# Generator (research.it.iastate.edu) — GPU type tokens occasionally differ
# (e.g. gpu:a100-80g:1). The values below are the common Nova form.

#SBATCH --job-name=prt-lora
# --- GPU selection (verified Nova gres tokens, 2026-05-20) ---
# IMPORTANT: on Nova the A100 cards have TWO distinct gres names:
#     gpu:a100        = A100 SXM 80GB  (nova21-gpu-*, nova22-gpu-*)  <- USE THIS
#     gpu:a100-pcie   = A100 PCIe 40GB (nova2x-amp-*)                <- AVOID (will OOM
#                       our no-checkpointing/batch4/1024px config; ~30-50GB needed)
# Requesting gpu:a100 will NEVER land on a 40GB card (different name), so we're safe.
# A100 80GB: abundant (124), usually idle -> fast start.
# To use the (scarcer, faster) H200 instead, swap the lines below — expect a longer queue.
# DO NOT use gh200 (ARM node) — our x86 torch+cu124 wheels won't install there.
#SBATCH --gres=gpu:a100:1
##SBATCH --gres=gpu:h200:1
#SBATCH --cpus-per-task=8
#SBATCH --mem=64G
#SBATCH --time=10:00:00            # generous; A100/1-epoch/5k should finish well under this
#SBATCH --output=prt-lora-%j.out
#SBATCH --error=prt-lora-%j.out

set -euo pipefail

# Compute nodes have no internet — use the model cached by setup_nova_env.sh.
export HF_HUB_OFFLINE=1
export TRANSFORMERS_OFFLINE=1
export PYTHONUNBUFFERED=1

module load cuda 2>/dev/null || true
PY="$HOME/lora-env/bin/python"

# Paths on Nova (staged via rsync; no need for the full repo tree).
SCRIPT="$HOME/lora_corrector/02_train_lora.py"
DATASET_DIR="$HOME/prt-lora-ds"       # rsync'd dataset (train.jsonl/val.jsonl/images)
OUTPUT_DIR="$HOME/prt-lora-out"       # adapter + tensorboard land here

# Set SMOKE=1 (via `sbatch --export=ALL,SMOKE=1 ...`) for a 50-doc validation
# run that proves the Nova path end-to-end before the full 5k dataset exists.
SMOKE_FLAG=""
[ "${SMOKE:-0}" = "1" ] && SMOKE_FLAG="--smoke"

echo "host=$(hostname)  job=$SLURM_JOB_ID  smoke=${SMOKE:-0}  $(date -u +%FT%TZ)"
nvidia-smi --query-gpu=name,memory.total --format=csv,noheader || true

# A100-80GB config: no gradient checkpointing (we have the VRAM -> ~2x faster),
# larger batch, higher image resolution for better OCR fidelity.
"$PY" "$SCRIPT" \
  --dataset-dir "$DATASET_DIR" \
  --output-dir "$OUTPUT_DIR" \
  --base-model Qwen/Qwen2.5-VL-7B-Instruct \
  --epochs 1 \
  --batch-size 4 \
  --grad-accum 2 \
  --max-pixels-factor 1024 \
  --no-grad-checkpointing \
  --lora-r 16 --lora-alpha 32 \
  $SMOKE_FLAG

echo "done $(date -u +%FT%TZ)"
