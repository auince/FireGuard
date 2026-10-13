#!/usr/bin/env bash
set -euo pipefail

PROJECT=/opt/datasets/fire-inspection/scripts/post_training_benchmark_20260722
ROOT=/opt/xfagent/artifacts/post_training_benchmark/qwen3vl_hydrant_20260722
LOG=${ROOT}/logs
mkdir -p "${LOG}"

# Respect unrelated jobs on the shared server.  A momentary gap is not enough:
# multi-process launchers may briefly release CUDA contexts while restarting
# workers.  Require all four GPUs to remain compute-process-free for ten
# consecutive minutes before taking the allocation.
idle_checks=0
idle_checks_required=20
while [ "${idle_checks}" -lt "${idle_checks_required}" ]; do
  if nvidia-smi --query-compute-apps=pid --format=csv,noheader | grep -Eq '[0-9]'; then
    idle_checks=0
  else
    idle_checks=$((idle_checks + 1))
  fi
  sleep 30
done

bash "${PROJECT}/scripts/run_dpo_verbose_1000step_4gpu.sh" \
  > "${LOG}/dpo_verbose_1000step_4gpu.log" 2>&1

bash "${PROJECT}/scripts/run_grpo_v41_1000step_4gpu.sh" \
  > "${LOG}/grpo_v41_verbose_1000step_4gpu.log" 2>&1

date --iso-8601=seconds > "${ROOT}/LONG_DPO_GRPO_QUEUE_COMPLETE"
