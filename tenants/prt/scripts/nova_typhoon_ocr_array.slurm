#!/bin/bash
#SBATCH --job-name=prt-typhoon-array
#SBATCH --partition=nova
#SBATCH --account=adisak-lab
#SBATCH --gres=gpu:a100:1
#SBATCH --cpus-per-task=12
#SBATCH --mem=80G
#SBATCH --time=08:00:00
#SBATCH --array=0-5
#SBATCH --output=%x-%A_%a.out
#SBATCH --error=%x-%A_%a.out
# 6-way parallel Typhoon-OCR: each array task OCRs 1/6 of the manifest (modulo shard)
# on its own A100. All tasks share the staged PDFs + write the same out-dir (distinct
# doc_ids; skip-guard prevents collisions). Override NSHARD if you change --array.
set -uo pipefail
NSHARD=6

# (1) Pin ollama to the EXACT allocated GPU by UUID. Slurm's CUDA_VISIBLE_DEVICES=0 broke
#     discovery, and `unset` was INCONSISTENT (CPU fallback on shared/heterogeneous nodes).
#     nvidia-smi inside the cgroup shows only the allocated GPU, so its UUID is unambiguous.
unset GPU_DEVICE_ORDINAL ROCR_VISIBLE_DEVICES HIP_VISIBLE_DEVICES
export CUDA_VISIBLE_DEVICES="$(nvidia-smi --query-gpu=uuid --format=csv,noheader 2>/dev/null | head -1)"
[ -z "$CUDA_VISIBLE_DEVICES" ] && { echo "FATAL: no GPU UUID from nvidia-smi"; exit 1; }
# (2) Force cuda_v12 (driver-13 auto-pick of cuda_v13 is broken for vision). Self-healing.
if [ -d "$HOME/ollama/lib/ollama/cuda_v13" ]; then
  mkdir -p "$HOME/ollama_disabled"
  mv "$HOME/ollama/lib/ollama/cuda_v13" "$HOME/ollama_disabled/cuda_v13.$(date +%s).$SLURM_ARRAY_TASK_ID" 2>/dev/null || true
fi

MODELS="${OLLAMA_MODELS:-/ptmp/tavanapo-lab/adisak/ollama_models}"
MANIFEST="${MANIFEST:-/ptmp/tavanapo-lab/adisak/typhoon/queue.csv}"
PDF_BASE="${PDF_BASE:-/ptmp/tavanapo-lab/adisak/typhoon/pdfs}"
OUTDIR="${OUTDIR:-/ptmp/tavanapo-lab/adisak/typhoon/papers_text_typhoon}"
PAR="${PAR:-8}"
EXTRA="${EXTRA:-}"
OLB="$HOME/ollama/bin/ollama"; OCRPY="$HOME/ocr-env/bin/python"; SCRIPT="$HOME/ocr_nova_typhoon.py"

export OLLAMA_MODELS="$MODELS"
PORT=$(( 30000 + (RANDOM % 5000) + SLURM_ARRAY_TASK_ID ))
export OLLAMA_HOST="127.0.0.1:$PORT"
export OLLAMA_KEEP_ALIVE=4h
export OLLAMA_NUM_PARALLEL="$PAR"
export OLLAMA_MAX_LOADED_MODELS=1

echo "host=$(hostname) array=$SLURM_ARRAY_JOB_ID task=$SLURM_ARRAY_TASK_ID/$NSHARD port=$PORT $(date -u +%FT%TZ)"
nvidia-smi --query-gpu=name --format=csv,noheader || true
mkdir -p "$OUTDIR"

"$OLB" serve > "$HOME/ollama-serve-$SLURM_ARRAY_JOB_ID-$SLURM_ARRAY_TASK_ID.log" 2>&1 &
SP=$!
trap 'kill $SP 2>/dev/null || true' EXIT
for i in $(seq 1 60); do curl -sf "http://$OLLAMA_HOST/api/tags" >/dev/null 2>&1 && break; sleep 2; done
curl -sf "http://$OLLAMA_HOST/api/tags" >/dev/null 2>&1 || { echo "FATAL: ollama not ready"; exit 1; }
echo "ollama up on http://$OLLAMA_HOST"
# fail fast if ollama fell back to CPU instead of the GPU (don't waste the slot for hours)
sleep 3
grep -q "library=CUDA" "$HOME/ollama-serve-$SLURM_ARRAY_JOB_ID-$SLURM_ARRAY_TASK_ID.log" \
  || { echo "FATAL: ollama on CPU (no GPU discovered) — aborting task"; exit 1; }

OLLAMA_HOST="$OLLAMA_HOST" OLLAMA_MODEL="scb10x/typhoon-ocr1.5-3b" \
  "$OCRPY" "$SCRIPT" --manifest "$MANIFEST" --pdf-base "$PDF_BASE" --out-dir "$OUTDIR" \
  --parallel "$PAR" --shard-index "$SLURM_ARRAY_TASK_ID" --shard-count "$NSHARD" $EXTRA
echo "task $SLURM_ARRAY_TASK_ID rc=$? done $(date -u +%FT%TZ)"
