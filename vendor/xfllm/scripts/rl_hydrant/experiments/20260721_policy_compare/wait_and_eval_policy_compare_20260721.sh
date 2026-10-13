#!/usr/bin/env bash
set -euo pipefail

EXP_ROOT="/opt/xfagent/artifacts/trl/qwen3vl4b_hydrant_policy_compare_20260721"
EVAL_SCRIPT="/opt/datasets/fire-inspection/scripts/rl_hydrant/eval_checkpoint_batched.py"
MODEL="/opt/models/qwen3-vl-4b"
EVAL_JSONL="/opt/datasets/fire-inspection/training_data/20260711_hydrant_rl_frozen_eval_v1/eval.jsonl"
OUT="$EXP_ROOT/eval_frozen_checkpoint100"
PYTHON="/opt/conda/envs/training/bin/python"

mkdir -p "$OUT" "$EXP_ROOT/logs"

while [[ ! -f "$EXP_ROOT/postflight.txt" ]]; do
  sleep 30
done

eval_one() {
  local gpu="$1"
  local name="$2"
  local adapter="$3"
  CUDA_VISIBLE_DEVICES="$gpu" "$PYTHON" "$EVAL_SCRIPT" \
    --model "$MODEL" \
    --adapter "$adapter" \
    --name "$name" \
    --eval-jsonl "$EVAL_JSONL" \
    --output-dir "$OUT" \
    --batch-size 8 \
    --max-new-tokens 320 \
    2>&1 | tee "$EXP_ROOT/logs/eval_${name}.log"
}

eval_one 1 grpo_scaled_step100 "$EXP_ROOT/01_grpo_scaled/checkpoint-100" &
pid_a=$!
eval_one 2 bnpo_scaled_step100 "$EXP_ROOT/02_bnpo_scaled/checkpoint-100" &
pid_b=$!
wait "$pid_a" "$pid_b"

eval_one 1 dr_grpo_scaled_step100 "$EXP_ROOT/03_dr_grpo_scaled/checkpoint-100" &
pid_c=$!
eval_one 2 dr_grpo_unscaled_step100 "$EXP_ROOT/04_dr_grpo_unscaled/checkpoint-100" &
pid_d=$!
wait "$pid_c" "$pid_d"

{
  echo "finished_at=$(date '+%F %T %Z')"
  find "$OUT" -maxdepth 1 -type f -printf '%f\n' | sort
} > "$EXP_ROOT/eval_postflight.txt"
