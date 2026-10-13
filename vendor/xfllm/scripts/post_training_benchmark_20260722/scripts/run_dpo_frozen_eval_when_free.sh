#!/usr/bin/env bash
set -euo pipefail

PY=/opt/conda/envs/training/bin/python
SCRIPT=/opt/datasets/fire-inspection/scripts/post_training_benchmark_20260722/scripts/eval_qwen3vl_preference_checkpoint.py
ROOT=/opt/xfagent/artifacts/post_training_benchmark/qwen3vl_hydrant_20260722
RUN_ROOT=${ROOT}/dpo_4b_4gpu_100step_seed20260722
EVAL_ROOT=${ROOT}/frozen_eval/dpo_4b_4gpu_100step_seed20260722
LOG_ROOT=${ROOT}/logs

mkdir -p "${EVAL_ROOT}" "${LOG_ROOT}"

# Never evict an unrelated job. Start the four independent evaluation workers
# only after the server reports no active GPU compute process.
while nvidia-smi --query-compute-apps=pid --format=csv,noheader | grep -Eq '[0-9]'; do
  sleep 30
done

steps=(40 60 80 100)
for gpu in 0 1 2 3; do
  step=${steps[$gpu]}
  name=dpo_step${step}
  CUDA_VISIBLE_DEVICES=${gpu} "${PY}" "${SCRIPT}" \
    --preference-adapter "${RUN_ROOT}/checkpoint-${step}" \
    --name "${name}" \
    --output-dir "${EVAL_ROOT}" \
    --batch-size 4 \
    > "${LOG_ROOT}/${name}_frozen_eval.log" 2>&1 &
done
wait
date --iso-8601=seconds > "${EVAL_ROOT}/EVAL_COMPLETE"
