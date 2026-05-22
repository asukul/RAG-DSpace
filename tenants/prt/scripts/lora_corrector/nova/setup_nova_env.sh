#!/usr/bin/env bash
# Set up the LoRA training env on the ISU Nova HPC cluster.
#
# RUN THIS ON THE LOGIN NODE (nova.its.iastate.edu) — it has internet.
# Compute nodes generally do NOT, so we install deps AND pre-download the
# base model here; the Slurm job then runs fully offline.
#
# Usage:
#   ssh <netid>@nova.its.iastate.edu
#   cd <repo>/tenants/prt/scripts/lora_corrector/nova
#   bash setup_nova_env.sh
set -euo pipefail

VENV="$HOME/lora-env"
PY="$VENV/bin/python"

echo "=== [1/5] modules NOT required (kept best-effort) ==="
# We deliberately avoid depending on Nova's module tree:
#   - uv installs its own Python 3.10 (next step),
#   - the torch cu124 wheels bundle the CUDA runtime and only need the GPU
#     driver, which is always present on Nova GPU nodes.
# So these loads are optional convenience only and never fatal.
module load python 2>/dev/null || true
module load cuda   2>/dev/null || true
echo "  python: $(command -v python3 || echo '(uv will provide one)')"

echo "=== [2/5] get uv (user-level, no sudo) ==="
if ! command -v uv >/dev/null 2>&1; then
  curl -LsSf https://astral.sh/uv/install.sh | sh
fi
export PATH="$HOME/.local/bin:$PATH"

echo "=== [3/5] create venv + install training stack (CUDA 12.4 wheels) ==="
uv venv "$VENV" --python 3.10
uv pip install --python "$PY" torch torchvision --index-url https://download.pytorch.org/whl/cu124
uv pip install --python "$PY" \
  "transformers>=4.49,<5" "peft>=0.13" "trl>=0.12" "accelerate>=1.0" \
  "bitsandbytes>=0.44" "qwen-vl-utils>=0.0.8" "datasets>=2.20" \
  "pillow>=10" "tensorboard" "nltk" "rouge-score"

echo "=== [4/5] CUDA sanity (login node may have no GPU — ok; verify in the job) ==="
"$PY" - <<'PYEOF'
import torch
print("torch", torch.__version__, "| cuda build", torch.version.cuda,
      "| GPU visible here:", torch.cuda.is_available())
PYEOF

echo "=== [5/5] pre-download base model (login node has internet) ==="
"$PY" - <<'PYEOF'
from huggingface_hub import snapshot_download
p = snapshot_download("Qwen/Qwen2.5-VL-7B-Instruct")
print("CACHED_AT", p)
PYEOF

echo "=== DONE. venv: $VENV ; model cached in ~/.cache/huggingface ==="
echo "Next: rsync the dataset to \$HOME/prt-lora-ds, then sbatch train_lora.slurm"
