#!/usr/bin/env bash
set -euo pipefail

STEPS=${STEPS:-1}
TRAIN_BATCH_SIZE=${TRAIN_BATCH_SIZE:-4}
PPO_MINI_BATCH_SIZE=${PPO_MINI_BATCH_SIZE:-${TRAIN_BATCH_SIZE}}
PPO_EPOCHS=${PPO_EPOCHS:-1}
ENV=/opt/venvs/verl_qwen3vl_20260722
VERL=/opt/verl
MODEL=/opt/xfagent/artifacts/post_training_benchmark/qwen3vl_hydrant_20260722/sft400_merged_hf
DATA=/opt/datasets/fire-inspection/training_data/20260722_hydrant_verl_rl_v2_verbose
REWARD=/opt/datasets/fire-inspection/scripts/post_training_benchmark_20260722/reward/hydrant_reward_verl_v41.py
ROOT=/opt/xfagent/artifacts/post_training_benchmark/qwen3vl_hydrant_20260722
RUN=ppo_gae_verbose_4b_4gpu_${STEPS}step_b${TRAIN_BATCH_SIZE}_mb${PPO_MINI_BATCH_SIZE}_ep${PPO_EPOCHS}_seed20260722
OUT=${ROOT}/${RUN}

if [ "${STEPS}" -le 1 ]; then
  SAVE_FREQ=-1
  TEST_FREQ=-1
else
  SAVE_FREQ=100
  TEST_FREQ=100
fi

test -f "${MODEL}/merge_manifest.json"
test -f "${DATA}/train.parquet"
test -f "${REWARD}"
mkdir -p "${OUT}" "${ROOT}/logs" /tmp/xfagent-ray

export CUDA_VISIBLE_DEVICES=0,1,2,3
export VERL_VALUEHEAD_ATTN_IMPLEMENTATION=sdpa
# NCCL 2.24+ auto-enables cuMem host allocations on recent CUDA stacks.
# This L40 host crashes in ncclCuMemHostEnable/cuMemCreate while FSDP2
# broadcasts the full value-head state, so use NCCL's documented SHM fallback.
export NCCL_CUMEM_HOST_ENABLE=0
# Final guard at prepare_micro_batches: this pinned Torch NestedTensor build
# cannot dynamically reorder Qwen3-VL ragged image tokens safely.
export VERL_FORCE_STATIC_BSZ=1
export VERL_STATIC_MICRO_BATCH_SIZE_PER_GPU=1
export VERL_NESTED_IDENTITY_FASTPATH=1
export VERL_KEEP_SERIALIZED_POSITION_IDS_RAGGED_IDX=1
export RAY_TMPDIR=/tmp/xfagent-ray
export WANDB_PROJECT=qwen3vl_hydrant_post_training_benchmark
export TOKENIZERS_PARALLELISM=false

ARGS=(
  algorithm.adv_estimator=gae
  data.train_files="${DATA}/train.parquet"
  data.val_files="${DATA}/validation.parquet"
  data.image_key=images
  data.train_batch_size="${TRAIN_BATCH_SIZE}"
  data.max_prompt_length=2048
  data.max_response_length=320
  # Repeated smoke runs verified 1700/1700 train and 193/193 validation
  # samples fit 2048 tokens. Avoid re-decoding every image at each restart.
  data.filter_overlong_prompts=False
  data.truncation=error
  actor_rollout_ref.model.path="${MODEL}"
  +actor_rollout_ref.model.override_config.attn_implementation=sdpa
  actor_rollout_ref.model.use_remove_padding=False
  actor_rollout_ref.model.enable_gradient_checkpointing=True
  actor_rollout_ref.model.use_fused_kernels=False
  actor_rollout_ref.actor.strategy=fsdp2
  actor_rollout_ref.actor.optim.lr=5e-7
  actor_rollout_ref.actor.ppo_mini_batch_size="${PPO_MINI_BATCH_SIZE}"
  actor_rollout_ref.actor.ppo_epochs="${PPO_EPOCHS}"
  actor_rollout_ref.actor.ppo_micro_batch_size_per_gpu=1
  # Dynamic token rebalancing in this VERL/Torch combination unbinds the
  # Qwen3-VL ragged image tensor along its token dimension (1081) instead of
  # its sample dimension.  Static per-GPU micro-batches preserve multimodal
  # sample boundaries and are the conservative PPO path for this 4x L40 host.
  actor_rollout_ref.actor.use_dynamic_bsz=False
  actor_rollout_ref.actor.ppo_max_token_len_per_gpu=4096
  actor_rollout_ref.actor.entropy_coeff=0.001
  actor_rollout_ref.actor.fsdp_config.param_offload=True
  actor_rollout_ref.actor.fsdp_config.optimizer_offload=True
  actor_rollout_ref.rollout.name=vllm
  actor_rollout_ref.rollout.tensor_model_parallel_size=2
  actor_rollout_ref.rollout.gpu_memory_utilization=0.30
  # Qwen3-VL advertises a 262144-token context and VERL otherwise forwards
  # that value (plus max_num_seqs=1024) to vLLM.  Hydrant PPO uses at most
  # 2048 prompt + 320 response tokens, so cap rollout KV-cache planning to a
  # truthful task envelope that fits the 4x L40 colocated actor/critic setup.
  actor_rollout_ref.rollout.max_model_len=4096
  actor_rollout_ref.rollout.max_num_seqs=16
  actor_rollout_ref.rollout.max_num_batched_tokens=4096
  actor_rollout_ref.rollout.n=1
  actor_rollout_ref.rollout.enable_chunked_prefill=False
  actor_rollout_ref.rollout.enforce_eager=True
  actor_rollout_ref.rollout.free_cache_engine=True
  actor_rollout_ref.rollout.log_prob_use_dynamic_bsz=False
  actor_rollout_ref.rollout.log_prob_micro_batch_size_per_gpu=1
  actor_rollout_ref.rollout.log_prob_max_token_len_per_gpu=4096
  actor_rollout_ref.ref.log_prob_use_dynamic_bsz=False
  actor_rollout_ref.ref.log_prob_micro_batch_size_per_gpu=1
  actor_rollout_ref.ref.log_prob_max_token_len_per_gpu=4096
  actor_rollout_ref.ref.fsdp_config.param_offload=True
  critic.model.path="${MODEL}"
  +critic.model.override_config.attn_implementation=sdpa
  critic.model.use_remove_padding=False
  critic.model.enable_gradient_checkpointing=True
  critic.strategy=fsdp2
  critic.optim.lr=5e-6
  critic.ppo_mini_batch_size="${PPO_MINI_BATCH_SIZE}"
  critic.ppo_epochs="${PPO_EPOCHS}"
  critic.ppo_micro_batch_size_per_gpu=1
  critic.use_dynamic_bsz=False
  critic.ppo_max_token_len_per_gpu=4096
  critic.fsdp.param_offload=True
  critic.fsdp.optimizer_offload=True
  reward.custom_reward_function.path="${REWARD}"
  reward.custom_reward_function.name=compute_score
  reward.reward_manager.name=naive
  reward.num_workers=4
  trainer.balance_batch=True
  trainer.critic_warmup=0
  trainer.logger='["console","wandb"]'
  trainer.project_name=qwen3vl_hydrant_post_training_benchmark
  trainer.experiment_name="${RUN}"
  trainer.n_gpus_per_node=4
  trainer.nnodes=1
  trainer.total_epochs=20
  trainer.total_training_steps="${STEPS}"
  trainer.save_freq="${SAVE_FREQ}"
  trainer.test_freq="${TEST_FREQ}"
  trainer.val_before_train=False
  trainer.default_local_dir="${OUT}"
  trainer.resume_mode=disable
)

cd "${VERL}"
if [ "${DRY_CONFIG:-0}" = 1 ]; then
  exec "${ENV}/bin/python" -m verl.trainer.main_ppo "${ARGS[@]}" --cfg job
fi
exec "${ENV}/bin/python" -m verl.trainer.main_ppo "${ARGS[@]}"
