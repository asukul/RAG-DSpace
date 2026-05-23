#!/bin/bash
#SBATCH --job-name=prt-typhoon-ocr
#SBATCH --partition=nova
#SBATCH --account=adisak-lab
#SBATCH --gres=gpu:a100:1
#SBATCH --cpus-per-task=12
#SBATCH --mem=80G
#SBATCH --time=12:00:00
#SBATCH --output=%x-%j.out
#SBATCH --error=%x-%j.out
# Serve Typhoon-OCR on an A100 and OCR a staged manifest of PRT PDFs.
# Override via: sbatch --export=ALL,MANIFEST=...,PDF_BASE=...,OUTDIR=...,PAR=8,EXTRA=--keep-markdown
set -uo pipefail

# (1) Pin ollama to the EXACT allocated GPU by UUID (robust on shared/heterogeneous nodes;
#     `unset CUDA_VISIBLE_DEVICES` was inconsistent → CPU fallback on some nodes).
unset GPU_DEVICE_ORDINAL ROCR_VISIBLE_DEVICES HIP_VISIBLE_DEVICES
export CUDA_VISIBLE_DEVICES="$(nvidia-smi --query-gpu=uuid --format=csv,noheader 2>/dev/null | head -1)"
[ -z "$CUDA_VISIBLE_DEVICES" ] && { echo "FATAL: no GPU UUID from nvidia-smi"; exit 1; }

# (2) Nova's driver is 13.0, so ollama auto-picks the bundled cuda_v13 runner, which is
#     BROKEN for vision (degenerate output). Force cuda_v12 by moving v13 aside. Self-healing
#     so this stays correct even after an ollama reinstall/upgrade.
if [ -d "$HOME/ollama/lib/ollama/cuda_v13" ]; then
  mkdir -p "$HOME/ollama_disabled"
  mv "$HOME/ollama/lib/ollama/cuda_v13" "$HOME/ollama_disabled/cuda_v13.$(date +%s)" 2>/dev/null || true
fi

MODELS="${OLLAMA_MODELS:-/ptmp/tavanapo-lab/adisak/ollama_models}"
MANIFEST="${MANIFEST:-/ptmp/tavanapo-lab/adisak/typhoon/queue.csv}"
PDF_BASE="${PDF_BASE:-/ptmp/tavanapo-lab/adisak/typhoon/pdfs}"
OUTDIR="${OUTDIR:-/ptmp/tavanapo-lab/adisak/typhoon/papers_text_typhoon}"
PAR="${PAR:-8}"
EXTRA="${EXTRA:-}"          # e.g. EXTRA=--keep-markdown to retain tables/page-numbers
OLB="$HOME/ollama/bin/ollama"
OCRPY="$HOME/ocr-env/bin/python"
SCRIPT="$HOME/ocr_nova_typhoon.py"

export OLLAMA_MODELS="$MODELS"
PORT=$(( 30000 + RANDOM % 5000 ))
export OLLAMA_HOST="127.0.0.1:$PORT"
export OLLAMA_KEEP_ALIVE=4h
export OLLAMA_NUM_PARALLEL="$PAR"
export OLLAMA_MAX_LOADED_MODELS=1

echo "host=$(hostname) job=$SLURM_JOB_ID port=$PORT par=$PAR $(date -u +%FT%TZ)"
nvidia-smi --query-gpu=name,memory.total --format=csv,noheader || true
mkdir -p "$OUTDIR"

# start ollama on the GPU node; tear down on exit
"$OLB" serve > "$HOME/ollama-serve-$SLURM_JOB_ID.log" 2>&1 &
SP=$!
trap 'kill $SP 2>/dev/null || true' EXIT
for i in $(seq 1 60); do curl -sf "http://$OLLAMA_HOST/api/tags" >/dev/null 2>&1 && break; sleep 2; done
curl -sf "http://$OLLAMA_HOST/api/tags" >/dev/null 2>&1 || { echo "FATAL: ollama not ready"; exit 1; }
echo "ollama up on http://$OLLAMA_HOST"; "$OLB" list

OLLAMA_HOST="$OLLAMA_HOST" OLLAMA_MODEL="scb10x/typhoon-ocr1.5-3b" \
  "$OCRPY" "$SCRIPT" --manifest "$MANIFEST" --pdf-base "$PDF_BASE" --out-dir "$OUTDIR" --parallel "$PAR" $EXTRA
echo "OCR rc=$?  done $(date -u +%FT%TZ)"
