#!/bin/bash
# Serve Ollama on a Nova GPU node and run a client (LLM-as-judge, RAG, OCR) against it.
# Models are PRE-PULLED on the login node into $OLLAMA_MODELS (compute nodes have no
# internet); this job only serves them and runs the client on the SAME node.
#
# Submit:  ssh nova 'cd <dir> && sbatch ollama_server.slurm'
# VERIFY before first use:  ssh nova 'sinfo -o "%P %G"'   (confirm the --gres token)

#SBATCH --job-name=ollama-judge
#SBATCH --gres=gpu:a100:1          # A100 80GB SXM (verified token 2026-05-20). h200 = scarcer/faster.
#SBATCH --cpus-per-task=8
#SBATCH --mem=64G
#SBATCH --time=08:00:00
#SBATCH --output=ollama-judge-%j.out
#SBATCH --error=ollama-judge-%j.out

set -euo pipefail

# --- paths / offline (EDIT $OLLAMA_MODELS to a verified scratch or /work dir, not $HOME) ---
export OLLAMA_MODELS="${OLLAMA_MODELS:-$HOME/ollama_models}"   # pre-populated on the login node
OLLAMA_BIN="${OLLAMA_BIN:-$HOME/ollama/bin/ollama}"           # or: module load ollama && OLLAMA_BIN=ollama
PORT=$(( 11434 + (RANDOM % 1000) ))                          # avoid collisions on shared nodes
export OLLAMA_HOST="127.0.0.1:${PORT}"
export OLLAMA_KEEP_ALIVE=2h
export OLLAMA_MAX_LOADED_MODELS=2     # >1 to host several judges at once (watch VRAM headroom)
export OLLAMA_NUM_PARALLEL=1

echo "host=$(hostname) job=$SLURM_JOB_ID port=$PORT $(date -u +%FT%TZ)"
nvidia-smi --query-gpu=name,memory.total --format=csv,noheader || true

# --- start the server in the background; always tear it down on exit ---
"$OLLAMA_BIN" serve > "ollama-serve-$SLURM_JOB_ID.log" 2>&1 &
SERVE_PID=$!
trap 'kill $SERVE_PID 2>/dev/null || true' EXIT

# --- wait until the API answers (max ~120s) ---
for i in $(seq 1 60); do
  curl -sf "http://${OLLAMA_HOST}/api/tags" >/dev/null && break
  sleep 2
done
curl -sf "http://${OLLAMA_HOST}/api/tags" >/dev/null || { echo "FATAL: ollama not ready"; exit 1; }
echo "ollama ready on http://${OLLAMA_HOST}"
"$OLLAMA_BIN" list

# ============================================================================
# RUN YOUR CLIENT HERE (same node → talks to $OLLAMA_HOST, fully offline).
# Example — multi-judge eval (adapt to eval_llm_judge.py's actual flags):
#   PY="$HOME/judge-env/bin/python"
#   "$PY" eval_llm_judge.py \
#        --provider ollama --base-url "http://${OLLAMA_HOST}" \
#        --judges qwen3.6:35b,gemma4:31b,deepseek-r1:32b \
#        --input runs.jsonl --out judge_out_$SLURM_JOB_ID.jsonl
# ============================================================================
echo "TODO: invoke client against http://${OLLAMA_HOST}"

echo "done $(date -u +%FT%TZ)"
