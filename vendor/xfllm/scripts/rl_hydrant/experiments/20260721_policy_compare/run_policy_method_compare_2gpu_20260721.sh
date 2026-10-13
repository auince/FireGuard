#!/usr/bin/env bash
set -euo pipefail

EXP_ROOT="/opt/xfagent/artifacts/trl/qwen3vl4b_hydrant_policy_compare_20260721"
SCRIPT_DIR="/opt/datasets/fire-inspection/scripts/rl_hydrant/experiments/20260721_policy_compare"
TRAIN_SCRIPT="$SCRIPT_DIR/train_qwen3vl_hydrant_policy_compare.py"
ACCELERATE="/opt/conda/envs/training/bin/accelerate"
MODEL="/opt/models/qwen3-vl-4b"
SFT_ADAPTER="/opt/xfagent/artifacts/trl/qwen3vl4b_hydrant_sft_grpo_v41_full_20260717/sft_model/checkpoint-400"
TRAIN_JSONL="/opt/datasets/fire-inspection/training_data/20260712_hydrant_rl_expanded_v2/train.jsonl"
WANDB_PROJECT="qwen3vl_hydrant_rl_method_compare"

mkdir -p "$EXP_ROOT/logs"
cd "$SCRIPT_DIR"

{
  echo "started_at=$(date '+%F %T %Z')"
  echo "gpu=1,2"
  echo "model=$MODEL"
  echo "init_adapter=$SFT_ADAPTER"
  echo "train_jsonl=$TRAIN_JSONL"
  echo "frozen_eval=/opt/datasets/fire-inspection/training_data/20260711_hydrant_rl_frozen_eval_v1/eval.jsonl"
  echo "methods=grpo_scaled,bnpo_scaled,dr_grpo_scaled,dr_grpo_unscaled"
  echo "common=max_steps:100,num_generations:8,global_completion_batch:8,reward:v41,seed:20260721"
  sha256sum train_qwen3vl_hydrant_policy_compare.py hydrant_rewards.py hydrant_rewards_v4.py hydrant_rewards_v41.py
  /opt/conda/envs/training/bin/python -c 'import trl,transformers,torch; print("trl="+trl.__version__); print("transformers="+transformers.__version__); print("torch="+torch.__version__)'
} > "$EXP_ROOT/preflight.txt"

run_method() {
  local order="$1"
  local method="$2"
  local loss_type="$3"
  local scale_flag="$4"
  local output_dir="$EXP_ROOT/${order}_${method}"
  local log_file="$EXP_ROOT/logs/${order}_${method}.log"

  mkdir -p "$output_dir"
  echo "[$(date '+%F %T')] START $method" | tee -a "$EXP_ROOT/timeline.log"

  CUDA_VISIBLE_DEVICES=1,2 \
  WANDB_PROJECT="$WANDB_PROJECT" \
  "$ACCELERATE" launch --num_processes 2 \
    "$TRAIN_SCRIPT" \
    --model "$MODEL" \
    --init-adapter "$SFT_ADAPTER" \
    --train-jsonl "$TRAIN_JSONL" \
    --output-dir "$output_dir" \
    --reward-version v41 \
    --limit 1893 \
    --max-steps 100 \
    --max-prompt-length 2048 \
    --max-completion-length 320 \
    --num-generations 8 \
    --per-device-train-batch-size 2 \
    --gradient-accumulation-steps 2 \
    --learning-rate 1e-6 \
    --warmup-ratio 0.03 \
    --lr-scheduler-type cosine \
    --temperature 1.0 \
    --top-p 0.98 \
    --beta 0.02 \
    --loss-type "$loss_type" \
    "$scale_flag" \
    --num-iterations 1 \
    --epsilon 0.2 \
    --save-steps 50 \
    --save-total-limit 2 \
    --seed 20260721 \
    --compliant-fraction 0.35 \
    --class-balanced-sampling \
    --report-to wandb \
    --wandb-project "$WANDB_PROJECT" \
    --wandb-run-name "qwen3vl4b_hydrant_${method}_2gpu_g8_100step_20260721" \
    --disable-broken-vllm \
    2>&1 | tee "$log_file"

  echo "[$(date '+%F %T')] END $method" | tee -a "$EXP_ROOT/timeline.log"
}

run_method 01 grpo_scaled grpo --scale-rewards
run_method 02 bnpo_scaled bnpo --scale-rewards
run_method 03 dr_grpo_scaled dr_grpo --scale-rewards
run_method 04 dr_grpo_unscaled dr_grpo --no-scale-rewards

{
  echo "finished_at=$(date '+%F %T %Z')"
  nvidia-smi --query-gpu=index,memory.used,memory.total,utilization.gpu --format=csv,noheader
} > "$EXP_ROOT/postflight.txt"
