#!/usr/bin/env bash
set -euo pipefail

SFT=/opt/xfagent/artifacts/trl/qwen3vl4b_hydrant_sft_grpo_v41_full_20260717/sft_model/checkpoint-400
ROOT=/opt/xfagent/artifacts/post_training_benchmark/qwen3vl_hydrant_20260722
OUT=${ROOT}/grpo_v41_verbose_4b_4gpu_1000step_seed20260722
SCRIPT_DIR=/opt/datasets/fire-inspection/scripts/rl_hydrant
ACCELERATE=/opt/conda/envs/training/bin/accelerate
RUN=grpo_v41_verbose_4b_4gpu_1000step_seed20260722

test -f "${SFT}/adapter_config.json"
mkdir -p "${OUT}" "${ROOT}/logs"
cd "${SCRIPT_DIR}"

export CUDA_VISIBLE_DEVICES=0,1,2,3
export WANDB_PROJECT=qwen3vl_hydrant_post_training_benchmark

"${ACCELERATE}" launch --num_processes 4 \
  train_qwen3vl_hydrant_grpo.py \
  --model /opt/models/qwen3-vl-4b \
  --init-adapter "${SFT}" \
  --train-jsonl /opt/datasets/fire-inspection/training_data/20260712_hydrant_rl_expanded_v2/train.jsonl \
  --output-dir "${OUT}" \
  --reward-version v41 \
  --limit 1893 \
  --max-steps 1000 \
  --max-prompt-length 2048 \
  --max-completion-length 320 \
  --num-generations 8 \
  --per-device-train-batch-size 2 \
  --learning-rate 1e-6 \
  --warmup-ratio 0.03 \
  --lr-scheduler-type cosine \
  --temperature 1.0 \
  --top-p 0.98 \
  --beta 0.02 \
  --save-steps 50 \
  --save-total-limit 21 \
  --seed 20260722 \
  --compliant-fraction 0.35 \
  --class-balanced-sampling \
  --report-to wandb \
  --wandb-project qwen3vl_hydrant_post_training_benchmark \
  --wandb-run-name "${RUN}" \
  --disable-broken-vllm
