#!/usr/bin/env bash
set -euo pipefail

TORCHRUN=/opt/conda/envs/training/bin/torchrun
SCRIPT=/opt/datasets/fire-inspection/scripts/post_training_benchmark_20260722/scripts/train_qwen3vl_preference.py
ROOT=/opt/xfagent/artifacts/post_training_benchmark/qwen3vl_hydrant_20260722
RUN=dpo_4b_4gpu_100step_seed20260722

mkdir -p "${ROOT}/logs" "${ROOT}/${RUN}"
nvidia-smi --query-gpu=index,name,memory.used,memory.total,utilization.gpu --format=csv,noheader \
  > "${ROOT}/${RUN}/gpu_preflight.txt"

export CUDA_VISIBLE_DEVICES=0,1,2,3
export WANDB_PROJECT=qwen3vl_hydrant_post_training_benchmark
export TOKENIZERS_PARALLELISM=false

"${TORCHRUN}" --standalone --nproc_per_node=4 "${SCRIPT}" \
  --method dpo \
  --output-dir "${ROOT}/${RUN}" \
  --max-steps 100 \
  --per-device-train-batch-size 1 \
  --per-device-eval-batch-size 1 \
  --gradient-accumulation-steps 2 \
  --learning-rate 5e-7 \
  --warmup-ratio 0.05 \
  --beta 0.1 \
  --eval-steps 20 \
  --save-steps 20 \
  --logging-steps 1 \
  --report-to wandb \
  --run-name "${RUN}"

nvidia-smi --query-gpu=index,name,memory.used,memory.total,utilization.gpu --format=csv,noheader \
  > "${ROOT}/${RUN}/gpu_postflight.txt"
