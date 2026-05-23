# Training the Typhoon-corrector LoRA on ISU Nova

The local RTX 4090 is too slow for the full 5k run (~155s/step → ~50h/epoch).
Nova has **124× A100 80GB** (plus H200, L40S, etc.) and is **free for ISU
researchers** (no node purchase required since 2024). An A100 80GB runs this
job ~5–10× faster than the 4090 (faster card + no gradient checkpointing +
bigger batch) → roughly **a few hours** for 5k / 1 epoch.

## 0. Request access (one-time)

- HPC Cluster Access Request form:
  https://iastate.service-now.com/esc?id=sc_cat_item&sys_id=4c36cbaedb65a8546870467239961913
- Login node: `nova.its.iastate.edu`
- Scheduler: **Slurm** (jobs auto-route to queues by requested resources)
- Slurm Script Generator + docs: https://research.it.iastate.edu/nova
- Support: `researchit@iastate.edu` (formerly `hpc-help@iastate.edu`)

## 1. Set up the env (on the LOGIN node — it has internet)

```bash
ssh <netid>@nova.its.iastate.edu
git clone <this repo>   # or rsync just tenants/prt/scripts/lora_corrector/
cd <repo>/tenants/prt/scripts/lora_corrector/nova
bash setup_nova_env.sh        # venv at ~/lora-env + pre-downloads the base model
```

Compute nodes generally have **no internet**, so the script installs deps AND
caches Qwen2.5-VL-7B on the login node; the job runs offline.

## 2. Transfer the dataset (after the 5k hybrid pairs are built)

Build the dataset (locally or on Nova) with the POSIX-path fix already in
`01_build_dataset.py`, then put it on Nova's fast FS:

```bash
# from the local machine (WSL or PowerShell with rsync/scp):
rsync -avz tenants/prt/data/corrector_lora_dataset/ \
      <netid>@nova.its.iastate.edu:~/prt-lora-ds/
```

`train_lora.slurm` points `--dataset-dir` at `$HOME/prt-lora-ds`. Keep it on
home/parallel FS, never a slow mount (the `/mnt/d` 9P slowness we hit locally
does not exist on Nova, but staging on the node FS is still best).

## 3. Submit the job

```bash
cd <repo>
sbatch tenants/prt/scripts/lora_corrector/nova/train_lora.slurm
```

The script requests `--gres=gpu:a100:1`. **Confirm the exact GPU token** with
the Slurm Script Generator — Nova occasionally uses variants like
`gpu:a100-80g:1`.

## 4. Monitor

```bash
squeue -u <netid>            # queue/running status
tail -f prt-lora-<jobid>.out # live log (Slurm flushes per line, unlike the WSL pipe)
```

## 5. Retrieve the adapter

The LoRA adapter (~190 MB) lands in
`tenants/prt/models/qwen2.5vl-7b-prt-corrector-lora/`. Pull it back:

```bash
rsync -avz <netid>@nova.its.iastate.edu:~/<repo>/tenants/prt/models/qwen2.5vl-7b-prt-corrector-lora/ \
      tenants/prt/models/qwen2.5vl-7b-prt-corrector-lora/
```

Then run inference locally on the 4090 (`03_infer.py`) — inference fits easily
in 24GB; only *training* needed the bigger card.

## Validated training config (from the 4090 de-risk)

- `HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1` — avoid HF network stalls
- 4-bit QLoRA (default); A100 80GB also allows `--bf16` (no quant) if preferred
- `--no-grad-checkpointing` on the A100 (we have VRAM → ~2× faster)
- `--batch-size 4 --grad-accum 2` (A100 80GB headroom)
- `--max-pixels-factor 1024` (better OCR fidelity; 512 was the 4090 VRAM cap)
- Dataset images use POSIX paths (portable across Windows builder / Linux trainer)
- Three code bugs already fixed in `01_build_dataset.py` / `02_train_lora.py`
  (Windows `\` paths, HF Arrow `image=None`, vision-token/truncation mismatch)
