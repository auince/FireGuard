#!/usr/bin/env bash
set -euo pipefail

CONDA_ENV="${CONDA_ENV:-training}"
# The current training torch/NCCL stack segfaults even on a tiny 2-GPU DDP
# smoke test. Default to the verified single-GPU path; override both variables
# explicitly after fixing the distributed runtime.
CUDA_VISIBLE_DEVICES="${CUDA_VISIBLE_DEVICES:-0}"
NPROC_PER_NODE="${NPROC_PER_NODE:-$(awk -F',' '{print NF}' <<< "$CUDA_VISIBLE_DEVICES")}"

MODEL="${MODEL:-/opt/models/Qwen3-VL-8B-Instruct}"
DATA_DIR="${DATA_DIR:-/opt/datasets/fire-inspection/training_data/20260627_hydrant_auto_visible_reasoning_v3}"
TRAIN_JSONL="${TRAIN_JSONL:-$DATA_DIR/train.jsonl}"
EVAL_JSONL="${EVAL_JSONL:-$DATA_DIR/val.jsonl}"
OUTPUT_DIR="${OUTPUT_DIR:-/opt/xfagent/artifacts/trl/qwen3vl8b_hydrant_auto_visible_reasoning_v3_sft_lora_20260627}"
DO_EVAL="${DO_EVAL:-1}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TRL_SFT_SCRIPT="${TRL_SFT_SCRIPT:-$SCRIPT_DIR/train_trl_qwen3vl_sft.py}"
HF_HOME="${HF_HOME:-/opt/datasets/fire-inspection/cache/huggingface}"
HF_DATASETS_CACHE="${HF_DATASETS_CACHE:-$HF_HOME/datasets}"

MAX_SEQ_LEN="${MAX_SEQ_LEN:-8192}"
# Qwen3-VL expands each image into many vision tokens. With eager attention,
# multi-megapixel inputs can OOM or crash inside native distributed collectives.
# Keep this bounded unless you switch to a lower-memory attention backend.
MIN_IMAGE_PIXELS="${MIN_IMAGE_PIXELS:-3136}"
MAX_IMAGE_PIXELS="${MAX_IMAGE_PIXELS:-1048576}"
PER_DEVICE_TRAIN_BATCH_SIZE="${PER_DEVICE_TRAIN_BATCH_SIZE:-1}"
PER_DEVICE_EVAL_BATCH_SIZE="${PER_DEVICE_EVAL_BATCH_SIZE:-1}"
GRADIENT_ACCUMULATION_STEPS="${GRADIENT_ACCUMULATION_STEPS:-4}"
DATALOADER_NUM_WORKERS="${DATALOADER_NUM_WORKERS:-0}"
LEARNING_RATE="${LEARNING_RATE:-2e-4}"
NUM_TRAIN_EPOCHS="${NUM_TRAIN_EPOCHS:-3}"
MAX_STEPS="${MAX_STEPS:--1}"
LOGGING_STEPS="${LOGGING_STEPS:-1}"
SAVE_STEPS="${SAVE_STEPS:-50}"
EVAL_STEPS="${EVAL_STEPS:-50}"
SAVE_TOTAL_LIMIT="${SAVE_TOTAL_LIMIT:-3}"
OPTIM="${OPTIM:-adamw_torch}"
ATTN_IMPLEMENTATION="${ATTN_IMPLEMENTATION:-eager}"
DTYPE="${DTYPE:-bf16}"
TF32="${TF32:-true}"
GRADIENT_CHECKPOINTING="${GRADIENT_CHECKPOINTING:-true}"
GRADIENT_CHECKPOINTING_USE_REENTRANT="${GRADIENT_CHECKPOINTING_USE_REENTRANT:-false}"
DDP_FIND_UNUSED_PARAMETERS="${DDP_FIND_UNUSED_PARAMETERS:-false}"
DDP_INIT_SYNC="${DDP_INIT_SYNC:-false}"
DDP_BROADCAST_BUFFERS="${DDP_BROADCAST_BUFFERS:-false}"
DISABLE_TRAIN_METRICS_GATHER="${DISABLE_TRAIN_METRICS_GATHER:-true}"
DISABLE_FLASH_SDP="${DISABLE_FLASH_SDP:-true}"
DISABLE_MEM_EFFICIENT_SDP="${DISABLE_MEM_EFFICIENT_SDP:-true}"
ENABLE_MATH_SDP="${ENABLE_MATH_SDP:-true}"
REPORT_TO="${REPORT_TO:-wandb}"
RUN_NAME="${RUN_NAME:-qwen3vl8b_hydrant_auto_visible_reasoning_v3_sft_lora_20260627}"
WANDB_PROJECT="${WANDB_PROJECT:-qwen3vl_hydrant_sft}"
WANDB_ENTITY="${WANDB_ENTITY:-}"
WANDB_TAGS="${WANDB_TAGS:-qwen3vl8b,hydrant,auto_scope,internal_components,appearance,sft,lora,prompt_v3,visible_reasoning,dedup,20260627}"
WANDB_MODE="${WANDB_MODE:-online}"
USE_QLORA="${USE_QLORA:-0}"
DRY_RUN="${DRY_RUN:-0}"
DEBUG_STAGE_DIR="${DEBUG_STAGE_DIR:-/tmp/qwen3vl_stage}"
DEBUG_STOP_AFTER="${DEBUG_STOP_AFTER:-}"

if [[ ! -f "$TRAIN_JSONL" ]]; then
  echo "TRAIN_JSONL does not exist: $TRAIN_JSONL" >&2
  exit 2
fi
if [[ "$DO_EVAL" == "1" && ! -f "$EVAL_JSONL" ]]; then
  echo "EVAL_JSONL does not exist: $EVAL_JSONL" >&2
  exit 2
fi

EXTRA_ARGS=()
if [[ "$USE_QLORA" == "1" ]]; then
  EXTRA_ARGS+=(--qlora)
fi

export CUDA_VISIBLE_DEVICES
export HF_HOME
export HF_DATASETS_CACHE
export PYTHONNOUSERSITE="${PYTHONNOUSERSITE:-1}"
export PYTHONFAULTHANDLER="${PYTHONFAULTHANDLER:-1}"
export TOKENIZERS_PARALLELISM="${TOKENIZERS_PARALLELISM:-false}"
export NCCL_DEBUG="${NCCL_DEBUG:-WARN}"
export TORCH_NCCL_ASYNC_ERROR_HANDLING="${TORCH_NCCL_ASYNC_ERROR_HANDLING:-1}"
export TORCH_DISTRIBUTED_DEBUG="${TORCH_DISTRIBUTED_DEBUG:-OFF}"

echo "CUDA_VISIBLE_DEVICES=$CUDA_VISIBLE_DEVICES"
echo "NPROC_PER_NODE=$NPROC_PER_NODE"
echo "MODEL=$MODEL"
echo "DATA_DIR=$DATA_DIR"
echo "TRAIN_JSONL=$TRAIN_JSONL"
echo "EVAL_JSONL=$EVAL_JSONL"
echo "OUTPUT_DIR=$OUTPUT_DIR"
echo "DO_EVAL=$DO_EVAL"
echo "REPORT_TO=$REPORT_TO"
echo "TRL_SFT_SCRIPT=$TRL_SFT_SCRIPT"
echo "DATALOADER_NUM_WORKERS=$DATALOADER_NUM_WORKERS"
echo "ATTN_IMPLEMENTATION=$ATTN_IMPLEMENTATION"
echo "OPTIM=$OPTIM"
echo "DTYPE=$DTYPE"
echo "DDP_INIT_SYNC=$DDP_INIT_SYNC"
echo "DDP_BROADCAST_BUFFERS=$DDP_BROADCAST_BUFFERS"
echo "DISABLE_TRAIN_METRICS_GATHER=$DISABLE_TRAIN_METRICS_GATHER"
echo "DEBUG_STAGE_DIR=$DEBUG_STAGE_DIR"
if [[ -n "$DEBUG_STOP_AFTER" ]]; then
  echo "DEBUG_STOP_AFTER=$DEBUG_STOP_AFTER"
fi
if [[ "$REPORT_TO" == "wandb" ]]; then
  echo "WANDB_PROJECT=$WANDB_PROJECT"
  echo "WANDB_MODE=$WANDB_MODE"
  echo "RUN_NAME=$RUN_NAME"
fi

WANDB_ARGS=()
if [[ "$REPORT_TO" == "wandb" ]]; then
  WANDB_ARGS+=(--run-name "$RUN_NAME")
  WANDB_ARGS+=(--wandb-project "$WANDB_PROJECT")
  WANDB_ARGS+=(--wandb-tags "$WANDB_TAGS")
  WANDB_ARGS+=(--wandb-mode "$WANDB_MODE")
  if [[ -n "$WANDB_ENTITY" ]]; then
    WANDB_ARGS+=(--wandb-entity "$WANDB_ENTITY")
  fi
fi

EVAL_ARGS=()
if [[ "$DO_EVAL" == "1" ]]; then
  EVAL_ARGS+=(--eval-jsonl "$EVAL_JSONL")
  EVAL_ARGS+=(--do-eval)
fi

DEBUG_ARGS=()
if [[ -n "$DEBUG_STAGE_DIR" ]]; then
  DEBUG_ARGS+=(--debug-stage-dir "$DEBUG_STAGE_DIR")
fi
if [[ -n "$DEBUG_STOP_AFTER" ]]; then
  DEBUG_ARGS+=(--debug-stop-after "$DEBUG_STOP_AFTER")
fi

CMD=(
  conda run -n "$CONDA_ENV" python -m torch.distributed.run --standalone --nproc_per_node "$NPROC_PER_NODE" "$TRL_SFT_SCRIPT"
  --model "$MODEL"
  --train-jsonl "$TRAIN_JSONL"
  "${EVAL_ARGS[@]}"
  --output-dir "$OUTPUT_DIR"
  --max-seq-len "$MAX_SEQ_LEN"
  --min-image-pixels "$MIN_IMAGE_PIXELS"
  --max-image-pixels "$MAX_IMAGE_PIXELS"
  --per-device-train-batch-size "$PER_DEVICE_TRAIN_BATCH_SIZE"
  --per-device-eval-batch-size "$PER_DEVICE_EVAL_BATCH_SIZE"
  --gradient-accumulation-steps "$GRADIENT_ACCUMULATION_STEPS"
  --dataloader-num-workers "$DATALOADER_NUM_WORKERS"
  --learning-rate "$LEARNING_RATE"
  --optim "$OPTIM"
  --num-train-epochs "$NUM_TRAIN_EPOCHS"
  --max-steps "$MAX_STEPS"
  --logging-steps "$LOGGING_STEPS"
  --save-steps "$SAVE_STEPS"
  --eval-steps "$EVAL_STEPS"
  --save-total-limit "$SAVE_TOTAL_LIMIT"
  --attn-implementation "$ATTN_IMPLEMENTATION"
  --dtype "$DTYPE"
  --tf32 "$TF32"
  --gradient-checkpointing "$GRADIENT_CHECKPOINTING"
  --gradient-checkpointing-use-reentrant "$GRADIENT_CHECKPOINTING_USE_REENTRANT"
  --ddp-find-unused-parameters "$DDP_FIND_UNUSED_PARAMETERS"
  --ddp-init-sync "$DDP_INIT_SYNC"
  --ddp-broadcast-buffers "$DDP_BROADCAST_BUFFERS"
  --disable-train-metrics-gather "$DISABLE_TRAIN_METRICS_GATHER"
  --disable-flash-sdp "$DISABLE_FLASH_SDP"
  --disable-mem-efficient-sdp "$DISABLE_MEM_EFFICIENT_SDP"
  --enable-math-sdp "$ENABLE_MATH_SDP"
  --report-to "$REPORT_TO"
  "${WANDB_ARGS[@]}"
  "${EXTRA_ARGS[@]}"
  "${DEBUG_ARGS[@]}"
  "$@"
)

if [[ "$DRY_RUN" == "1" ]]; then
  printf 'DRY_RUN command:'
  printf ' %q' "${CMD[@]}"
  printf '\n'
  exit 0
fi

mkdir -p "$HF_DATASETS_CACHE" "$OUTPUT_DIR"
if [[ -n "$DEBUG_STAGE_DIR" ]]; then
  rm -f "$DEBUG_STAGE_DIR"/rank*_local*.json 2>/dev/null || true
  mkdir -p "$DEBUG_STAGE_DIR"
fi

"${CMD[@]}"
