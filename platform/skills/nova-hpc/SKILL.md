---
name: nova-hpc
version: 0.1.0
description: Drive ISU's Nova HPC cluster (Slurm, A100 80GB / H200 GPUs, free for ISU faculty) over SSH to run GPU work that doesn't fit the local 4090 — Ollama / LMStudio inference servers, multi-judge LLM-as-judge eval, LoRA / full fine-tuning, Typhoon OCR, and batch experiments. Use when the user wants to run, transfer, or monitor compute on Nova; stage models/data to Nova; serve a local model on a Nova GPU; or submit/track Slurm jobs; or check current Nova GPU availability + specs (free/used per type, VRAM, CUDA cores, bandwidth).
tags: [hpc, nova, slurm, gpu, ollama, lmstudio, llm-judge, fine-tuning, ocr, iastate]
authors:
  - Adisak Sukul <asukul@iastate.edu>
---

# nova-hpc — drive ISU Nova from this machine

Nova (`nova.its.iastate.edu`) is ISU's research cluster: **A100 80GB ×124, H200 141GB ×12,
A100 40GB ×20, L40S 48GB ×16, RTX 6000 48GB ×20, V100 32GB ×22**, Slurm scheduler, free for
ISU faculty. This skill lets the agent orchestrate it over SSH — submit/monitor jobs, serve
models on a GPU, move data — **without the user copy/pasting commands and results**.

## TL;DR golden path
1. **Check the channel:** `ssh -o BatchMode=yes nova 'hostname; nvidia-smi -L 2>/dev/null | head'`
2. **Stage on the LOGIN node** (it has internet): `rsync` data up; pull models/deps.
3. **Submit:** `ssh nova 'cd <dir> && sbatch job.slurm'`
4. **Monitor:** `ssh nova 'squeue --me'` and `ssh nova 'tail -n 50 <job>.out'`
5. **Pull results down:** `rsync -avhP nova:<remote>/ /d/RAG-DSpace/<local>/`

## ⚠️ THE rule that governs everything: compute nodes have NO internet
Login nodes have internet; the GPU **compute nodes (where Slurm jobs run) do not.** Therefore:
- **Pre-stage everything on the login node**: `ollama pull`, `lms get`, `huggingface_hub.snapshot_download`,
  `pip`/`uv` installs — all happen on login, into a shared dir. Jobs then run **fully offline**.
- In job scripts set: `HF_HUB_OFFLINE=1`, `TRANSFORMERS_OFFLINE=1`, a pre-populated `OLLAMA_MODELS`,
  and **never `ollama pull` / `pip install` / `curl` the internet inside a job**.
- **`claude` / the Anthropic API only works on the login node or locally** — never from inside a
  compute-node job. (So: an Opus/Claude step like the PRT hybrid corrector stays *local*, not on Nova.)

## Connection (WORKING 2026-05-21 — driven from WSL2/Ubuntu, NOT Git Bash/PowerShell)
- **Nova forces Duo and disables publickey auth** (server offers only `gssapi/password/keyboard-interactive`).
  No passwordless key login is possible. The working method = **SSH connection multiplexing over an
  interactive master**, set up in **WSL2** — Git Bash/MSYS multiplexing is broken on Windows
  (`read from master failed: Connection reset by peer`) and PowerShell/Windows-OpenSSH has none.
- SSH alias **`nova`** → `adisak@nova.its.iastate.edu` in **WSL** `~/.ssh/config` (`ControlMaster auto`,
  `ControlPath ~/.ssh/cm-%C`, `ControlPersist 8h`, `StrictHostKeyChecking accept-new`). NetID **adisak**
  (ISU *email* asukul@iastate.edu differs). Login node: `nova-login-2`.
- **Open the master (user does this, ~1 Duo per 8h):** in a WSL/Ubuntu terminal run `ssh -fN nova`
  (password + Duo), keep the window open.
- **Drive it (automation):** `wsl -e bash -lc 'ssh -o BatchMode=yes nova "<cmd>"'` reuses the master,
  no re-auth. **Liveness:** `wsl -e bash -lc 'ssh -o BatchMode=yes nova hostname'` → `nova-login-N`.
  If it fails the master lapsed → user re-runs `ssh -fN nova` in WSL.
- **Scripting gotcha:** any `ssh` whose output you pipe into a shell must use `ssh -n` (else it slurps
  stdin and later commands vanish). For multi-step remote work, write a `.sh` and run it as a file.
- **Be a good login-node citizen:** only stage / submit / monitor / light-edit there.

## First-run discovery (verify — Nova config drifts; don't trust stale values)
Run once per session/cluster-change and adapt to the answers:
```bash
ssh nova 'sinfo -o "%P %.6D %G %m %f" | sort -u'                 # partitions, GPU gres tokens, mem, features
ssh nova 'scontrol show partition | grep -E "PartitionName|MaxTime|DefaultTime|TRES="'
ssh nova 'module avail 2>&1 | tr "\t" "\n" | grep -iE "cuda|ollama|conda|micromamba|python"'
ssh nova 'echo HOME=$HOME; ls -d /work/* /ptmp/* /scratch/* 2>/dev/null; quota -s 2>/dev/null | tail'
ssh nova 'command -v ollama lms apptainer singularity uv 2>/dev/null'
```

## Verified Nova facts (as of 2026-05-20 — re-verify with `sinfo` if jobs reject/pend)
- **GPU gres tokens** (these matter — a wrong token pends forever or lands on the wrong card):

  | gres | card | use? |
  |---|---|---|
  | `gpu:a100` | **A100 80GB SXM** (nova21/22-gpu-*) | ✅ **default** — abundant (124), usually idle, fast start |
  | `gpu:h200` | H200 141GB | ✅ scarcer/faster → longer queue |
  | `gpu:a100-pcie` | A100 PCIe **40GB** | ⚠️ avoid for big configs (OOM) |
  | `gpu:gh200` | GH200 **ARM** | ❌ avoid — x86 `torch+cu124` wheels won't install |

- **Env without fighting the module tree:** install `uv` user-level (`curl -LsSf https://astral.sh/uv/install.sh | sh`,
  `PATH=$HOME/.local/bin:$PATH`); `torch` cu124 wheels bundle the CUDA runtime and only need the GPU
  **driver** (always present on GPU nodes). `module load cuda/python` is best-effort (`2>/dev/null || true`).
- **Filesystem (confirmed 2026-05-21):** scratch = **`/ptmp`** (Lustre, ~147 TB free; files unused 60 d
  are purged) → models + big datasets go here (e.g. `/ptmp/tavanapo-lab/...`). `$HOME` (`/home/adisak`,
  16 TB NFS, quota'd) = code only. `/lss` = backed-up storage for keep-forever results.
- **Submit target (confirmed 2026-05-21):** `--partition=nova` (default) `--account=adisak-lab`
  `--gres=gpu:a100:1` (QOS `normal`; `scavenger` = preemptible). Second account: `tavanapo-lab`.
- **No `ollama`/`uv`/`conda`/`apptainer` on PATH and no `ollama` module** → install the static `ollama`
  binary + `uv` into `$HOME` on the login node. CUDA is a module (`cuda/12.4.1` matches our torch cu124 wheels).

## File transfer (Git Bash ↔ Nova; `D:\` shows as `/d/`)
```bash
rsync -avhP --info=progress2 /d/RAG-DSpace/<path>/ nova:<dest>/      # up
rsync -avhP nova:<remote>/results/ /d/RAG-DSpace/<path>/             # down
```

## Check GPU availability ⭐ (trigger: "what GPUs are free on Nova?", "check Nova GPUs", "Nova GPU availability")
Run the bundled **`gpu_avail.sh`** and show its table. It merges **LIVE** Slurm counts
(`sinfo` on Nova) with a **STATIC** NVIDIA datasheet spec table (Slurm doesn't track VRAM/cores/bandwidth).
```bash
# from WSL — sinfo runs on Nova, awk runs locally:
bash ~/gpu_avail.sh                                              # user's copy (also: alias `gpus`)
tr -d '\r' < platform/skills/nova-hpc/gpu_avail.sh | bash        # version-controlled copy
```
Columns: `GPU(gres) | FREE USE TOT` (live) `| VRAM CUDA MEM-BW FP16T ARCH` (datasheet). Notes:
`a100`=80 GB confirmed from jobs; `rtx_6000`/`rtx_pro_6000`/`v100` specs are approximate
(confirm with `nvidia-smi` in a job if it matters). **For typhoon-OCR (3B, ~22 GB) the limiter is
bandwidth + FP16 throughput, not VRAM** → H200 > A100 > L40S; L40S/RTX-6000 are good fallbacks when
A100s are tight. (Quick raw view, no specs: `ssh nova "sinfo -N -h -O 'NodeHost:18,Gres:26,GresUsed:26' | grep gpu:a100:"`.)

## Slurm cheat-sheet (all via the `nova` alias)
```bash
ssh nova 'cd <dir> && sbatch job.slurm'                                  # submit
ssh nova 'sbatch --export=ALL,SMOKE=1 job.slurm'                         # pass env vars
ssh nova 'squeue --me'                                                   # my queue
ssh nova "squeue -j <id> -o '%.18i %.9P %.8T %.10M %.6D %R'"             # one job
ssh nova 'tail -n 80 <job>-<id>.out'                                     # logs (poll; avoid blocking tail -f)
ssh nova 'sacct -j <id> --format=JobID,State,ExitCode,Elapsed,MaxRSS,ReqTRES%40'   # post-mortem
ssh nova 'scancel <id>'                                                  # cancel
ssh -t nova 'salloc --gres=gpu:a100:1 --time=1:00:00 --mem=64G --cpus-per-task=8'   # interactive (needs TTY+Duo → user runs)
```

## Workflow A — Ollama inference server on a Nova GPU  ⭐ (multi-judge, RAG, OCR)
The pattern for LLM-as-judge runs and any Ollama workload. **Models are pre-pulled on the login node**;
the job serves them and runs the client **on the same node** (no internet needed at job time).

**Step 1 — login node, once per model (has internet):**
```bash
ssh nova 'export OLLAMA_MODELS=$HOME/ollama_models; mkdir -p $OLLAMA_MODELS
          # ollama as a module, else install the static binary to $HOME (no sudo):
          command -v ollama || { curl -L https://github.com/ollama/ollama/releases/latest/download/ollama-linux-amd64.tar.zst -o ~/o.tzst && mkdir -p ~/ollama && tar --zstd -xf ~/o.tzst -C ~/ollama; }   # then force cuda_v12 on driver-13 nodes — see OCR recipe
          OLLAMA=${OLLAMA:-$HOME/ollama/bin/ollama}
          $OLLAMA serve & sleep 5
          for m in qwen3.6:35b gemma4:31b deepseek-r1:32b; do $OLLAMA pull "$m"; done
          kill %1'
```
**Step 2 — submit the server+client job:** see `templates/ollama_server.slurm`. It picks a free port,
sets `OLLAMA_MODELS`/`OLLAMA_HOST`, raises `OLLAMA_MAX_LOADED_MODELS`/`OLLAMA_NUM_PARALLEL` for
multi-judge, waits for `/api/tags`, runs the client, tears down.

**Multi-judge tips:** host several judges in one job (`OLLAMA_MAX_LOADED_MODELS=N`, watch VRAM) **or**
one job per judge for cross-node parallelism. Point `eval_llm_judge.py` (multi-judge mode) at
`http://$OLLAMA_HOST`. To reach the server from your laptop/login node:
`ssh -N -L 11434:<computenode>:<PORT> nova` (usually unnecessary — prefer client-in-job).

## Workflow B — LMStudio / llama.cpp on Nova
- LMStudio is GUI-first; headless via the **`lms` CLI** + `lms server start --port <p>` (OpenAI-compatible
  `/v1`). `lms get <model>` needs internet → **login node**. AppImage on HPC: `APPIMAGE_EXTRACT_AND_RUN=1`
  (FUSE is often missing on compute nodes).
- **Honest guidance:** Ollama is the smoother HPC path and you already script against it. For raw GGUF
  serving without a GUI, **`llama.cpp`'s `llama-server`** (build once on a login/CPU node) is the most
  HPC-friendly. Reach for LMStudio only for models you specifically need through it.

## Workflow C — Batch GPU Python (fine-tune / OCR / generic)
- See `templates/gpu_python.slurm`. **Worked, validated example:** the Typhoon-corrector LoRA at
  `tenants/prt/scripts/lora_corrector/nova/` (`setup_nova_env.sh` builds the env + pre-downloads the
  model on login; `train_lora.slurm` runs offline on an A100). Copy that pattern.
- **Thai OCR (typhoon-ocr):** VALIDATED end-to-end — see the dedicated recipe below. Only the GPU OCR
  step runs on Nova; the Opus hybrid corrector stays local (subscription, no Anthropic on Nova).

## Recipe: Thai OCR on Nova (typhoon-ocr) — VALIDATED 2026-05-22 ⭐
Generalizes to any Thai DSpace repo. Files (in `tenants/prt/scripts/`): `ocr_nova_typhoon.py`,
`nova_typhoon_ocr.slurm` (single A100), `nova_typhoon_ocr_array.slurm` (N-way array),
`nova_build_typhoon_manifest.py`; plus `stage_typhoon.sh` (in `$HOME`).
1. **One-time per cluster:** install ollama (`ollama-linux-amd64.tar.zst` from GitHub releases →
   `$HOME/ollama`) + `ollama pull scb10x/typhoon-ocr1.5-3b` (login node) into `$OLLAMA_MODELS` on `/ptmp`;
   make an `~/ocr-env` venv with `pymupdf` (via uv).
2. **Per repo:** build a manifest (`doc_id,pdf_path` of image-only docs needing OCR), then
   `bash stage_typhoon.sh <N>` — symlink-renames each PDF to `<doc_id>.pdf`, `rsync -L`s to
   `/ptmp/.../pdfs`, uploads the manifest + scripts.
3. **Run:** `ssh nova 'cd ~ && sbatch nova_typhoon_ocr_array.slurm'` (6 A100s, ~1/6 docs each via modulo
   shard; bump `--array`/`NSHARD` for more) or the single-GPU `nova_typhoon_ocr.slurm`. rsync results back.
**Three non-obvious fixes baked into the slurm/script (without them: crashes or garbage):**
- **Force `cuda_v12`** — Nova driver 13.0 auto-picks the bundled `cuda_v13` runner, which is BROKEN for
  vision (degenerate `<|vision_end|>` output). The slurm moves cuda_v13 aside (self-healing).
- **`unset CUDA_VISIBLE_DEVICES`** — Slurm sets it to 0, breaking ollama's GPU discovery (falls back to CPU).
- **typhoon's NATIVE prompt** + `strip_degenerate()` (sparse/cover pages) + per-request `num_ctx`
  (avoids the 256k auto-context CUDA VMM SIGABRT). Output flattens Markdown→plain by default
  (`EXTRA=--keep-markdown` to retain tables/page-numbers for table-heavy repos).

## Gotchas (carry forward)
- **Vision models (typhoon-ocr) on Nova: force `cuda_v12`** (driver-13 `cuda_v13` is broken for vision),
  `unset CUDA_VISIBLE_DEVICES`, use the model's native prompt via `/api/generate`, cap `num_ctx`. Don't
  leave old jobs running (concurrent writers + skip-guard ⇒ stale files); `scancel -u $USER` + wipe out-dir between config changes.
- `--gres` token must match `sinfo %G` **exactly**, or the job pends/rejects.
- `$HOME` has a quota → models + big data go on scratch/`/work`.
- Compute nodes are **offline** → pre-stage; set `*_OFFLINE=1`; no in-job `pull`/`pip`/`curl`/`claude`.
- `ControlPersist 24h` (WSL `~/.ssh/config`): long Slurm jobs are unaffected (detached from SSH), but
  **monitoring ssh calls need a live master** — reopen with `ssh -fN nova` in WSL if it expires.
- `--time` hard-kills jobs → checkpoint long runs.
- GH200 is ARM — x86 wheels won't install.
- Don't run heavy/long processes on login nodes.

## Quick reference
| Want | Command |
|---|---|
| Channel up? | `ssh -o BatchMode=yes nova true && echo OK` |
| What GPUs/partitions? | `ssh nova 'sinfo -o "%P %G %m"' \| sort -u` |
| Push data | `rsync -avhP /d/RAG-DSpace/X/ nova:X/` |
| Submit | `ssh nova 'cd D && sbatch job.slurm'` |
| Watch | `ssh nova 'squeue --me'` |
| Tail log | `ssh nova 'tail -n 80 job-<id>.out'` |
| Why pending/failed | `ssh nova 'sacct -j <id> --format=JobID,State,ExitCode,Elapsed'` |
| Pull results | `rsync -avhP nova:out/ /d/RAG-DSpace/out/` |

> Docs: research.it.iastate.edu (Slurm Script Generator confirms gres/partition). Support: researchit@iastate.edu.
