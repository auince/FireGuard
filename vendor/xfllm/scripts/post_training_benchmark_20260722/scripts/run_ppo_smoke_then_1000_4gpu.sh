#!/usr/bin/env bash
set -euo pipefail

PROJECT=/opt/datasets/fire-inspection/scripts/post_training_benchmark_20260722
ROOT=/opt/xfagent/artifacts/post_training_benchmark/qwen3vl_hydrant_20260722
LOG=${ROOT}/logs
mkdir -p "${LOG}"

STEPS=1 TRAIN_BATCH_SIZE=4 PPO_MINI_BATCH_SIZE=4 \
  bash "${PROJECT}/scripts/run_ppo_qwen3vl_4b_4gpu.sh" \
  > "${LOG}/ppo_gae_verbose_4b_4gpu_1step_smoke.log" 2>&1

STEPS=1000 TRAIN_BATCH_SIZE=8 PPO_MINI_BATCH_SIZE=8 \
  bash "${PROJECT}/scripts/run_ppo_qwen3vl_4b_4gpu.sh" \
  > "${LOG}/ppo_gae_verbose_4b_4gpu_1000step.log" 2>&1
