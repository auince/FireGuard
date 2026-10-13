#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

export CUDA_VISIBLE_DEVICES=1
export NPROC_PER_NODE=1
export REPORT_TO="${REPORT_TO:-none}"
export WANDB_MODE="${WANDB_MODE:-disabled}"
export OUTPUT_DIR="${OUTPUT_DIR:-/tmp/qwen3vl_single_gpu1}"
export DO_EVAL="${DO_EVAL:-0}"
export MAX_STEPS="${MAX_STEPS:-1}"
export DATALOADER_NUM_WORKERS="${DATALOADER_NUM_WORKERS:-0}"
export ATTN_IMPLEMENTATION="${ATTN_IMPLEMENTATION:-eager}"
export OPTIM="${OPTIM:-adamw_torch}"
export DTYPE="${DTYPE:-bf16}"
export DISABLE_FLASH_SDP="${DISABLE_FLASH_SDP:-true}"
export DISABLE_MEM_EFFICIENT_SDP="${DISABLE_MEM_EFFICIENT_SDP:-true}"
export DEBUG_STAGE_DIR="${DEBUG_STAGE_DIR:-/tmp/qwen3vl_stage_single_gpu1}"
export TORCH_DISTRIBUTED_DEBUG="${TORCH_DISTRIBUTED_DEBUG:-DETAIL}"
export NCCL_DEBUG="${NCCL_DEBUG:-INFO}"

exec "$SCRIPT_DIR/run_qwen3vl8b_internal_sft.sh" "$@"
