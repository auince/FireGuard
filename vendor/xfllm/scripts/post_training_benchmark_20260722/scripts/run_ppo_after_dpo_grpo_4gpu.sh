#!/usr/bin/env bash
set -euo pipefail

PREVIOUS_QUEUE_PID=${PREVIOUS_QUEUE_PID:?set PREVIOUS_QUEUE_PID}
PROJECT=/opt/datasets/fire-inspection/scripts/post_training_benchmark_20260722
ROOT=/opt/xfagent/artifacts/post_training_benchmark/qwen3vl_hydrant_20260722
LOG=${ROOT}/logs

while [ ! -f "${ROOT}/LONG_DPO_GRPO_QUEUE_COMPLETE" ]; do
  if ! kill -0 "${PREVIOUS_QUEUE_PID}" 2>/dev/null; then
    echo "DPO/GRPO queue exited without completion marker" \
      > "${LOG}/ppo_queue_blocked.txt"
    exit 1
  fi
  sleep 30
done

bash "${PROJECT}/scripts/run_ppo_smoke_then_1000_4gpu.sh"
date --iso-8601=seconds > "${ROOT}/LONG_PPO_QUEUE_COMPLETE"
