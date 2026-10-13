#!/usr/bin/env bash
set -euo pipefail

TORCHRUN=/opt/conda/envs/training/bin/torchrun
SCRIPT=/opt/datasets/fire-inspection/scripts/post_training_benchmark_20260722/scripts/train_qwen3vl_preference.py
ROOT=/opt/xfagent/artifacts/post_training_benchmark/qwen3vl_hydrant_20260722
DATA=/opt/datasets/fire-inspection/training_data/20260722_hydrant_preference_v2_verbose
RUN=dpo_verbose_4b_4gpu_1000step_seed20260722

mkdir -p "${ROOT}/logs" "${ROOT}/${RUN}"
export CUDA_VISIBLE_DEVICES=0,1,2,3
export WANDB_PROJECT=qwen3vl_hydrant_post_training_benchmark
export TOKENIZERS_PARALLELISM=false

"${TORCHRUN}" --standalone --nproc_per_node=4 "${SCRIPT}" \
  --method dpo \
  --train-jsonl "${DATA}/train.jsonl" \
  --validation-jsonl "${DATA}/validation.jsonl" \
  --output-dir "${ROOT}/${RUN}" \
  --max-steps 1000 \
  --per-device-train-batch-size 1 \
  --per-device-eval-batch-size 1 \
  --gradient-accumulation-steps 2 \
  --learning-rate 1e-6 \
  --warmup-ratio 0.05 \
  --beta 0.1 \
  --max-completion-length 320 \
  --eval-steps 100 \
  --save-steps 50 \
  --save-total-limit 21 \
  --logging-steps 1 \
  --report-to wandb \
  --run-name "${RUN}"
