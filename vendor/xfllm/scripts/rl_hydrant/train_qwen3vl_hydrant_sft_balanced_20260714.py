#!/usr/bin/env python3
from __future__ import annotations

import argparse
import faulthandler
import json
import os
from pathlib import Path
import sys
import time
from typing import Any

import torch
from datasets import load_dataset
from PIL import Image
from peft import LoraConfig, prepare_model_for_kbit_training
from transformers import (
    AutoProcessor,
    BitsAndBytesConfig,
    Qwen3VLForConditionalGeneration,
    Trainer,
    TrainingArguments,
)
from trl import SFTTrainer


def _rank() -> int:
    return int(os.environ.get("RANK", "0"))


def _local_rank() -> int:
    return int(os.environ.get("LOCAL_RANK", "0"))


def _log(message: str) -> None:
    print(f"[rank={_rank()} local_rank={_local_rank()} pid={os.getpid()}] {message}", flush=True)


def _mark_stage(args: argparse.Namespace, stage: str) -> None:
    _log(stage)
    if not args.debug_stage_dir:
        return

    stage_dir = Path(args.debug_stage_dir)
    stage_dir.mkdir(parents=True, exist_ok=True)
    cuda_info: dict[str, Any] = {
        "available": torch.cuda.is_available(),
        "current_device": None,
        "device_count": None,
        "device_name": None,
        "memory_allocated": None,
        "memory_reserved": None,
    }
    if torch.cuda.is_available():
        current_device = torch.cuda.current_device()
        cuda_info.update(
            {
                "current_device": current_device,
                "device_count": torch.cuda.device_count(),
                "device_name": torch.cuda.get_device_name(current_device),
                "memory_allocated": torch.cuda.memory_allocated(current_device),
                "memory_reserved": torch.cuda.memory_reserved(current_device),
            }
        )

    payload = {
        "time": time.strftime("%Y-%m-%d %H:%M:%S"),
        "stage": stage,
        "pid": os.getpid(),
        "rank": _rank(),
        "local_rank": _local_rank(),
        "world_size": int(os.environ.get("WORLD_SIZE", "1")),
        "torch": torch.__version__,
        "cuda_runtime": torch.version.cuda,
        "cuda": cuda_info,
    }
    marker = stage_dir / f"rank{_rank()}_local{_local_rank()}.json"
    marker.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _stop_after(args: argparse.Namespace, stage: str) -> bool:
    if args.debug_stop_after != stage:
        return False
    _mark_stage(args, f"debug_stop_after_{stage}")
    return True


def _str_to_bool(value: str) -> bool:
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "y", "on"}:
        return True
    if normalized in {"0", "false", "no", "n", "off"}:
        return False
    raise argparse.ArgumentTypeError(f"expected a boolean value, got {value!r}")


def _configure_torch_runtime(args: argparse.Namespace) -> None:
    if torch.cuda.is_available():
        local_rank = _local_rank()
        if local_rank < torch.cuda.device_count():
            torch.cuda.set_device(local_rank)

    if torch.cuda.is_available():
        torch.backends.cuda.matmul.allow_tf32 = args.tf32
        torch.backends.cudnn.allow_tf32 = args.tf32
    if hasattr(torch, "set_float32_matmul_precision"):
        torch.set_float32_matmul_precision("high" if args.tf32 else "highest")

    if args.disable_flash_sdp and hasattr(torch.backends.cuda, "enable_flash_sdp"):
        torch.backends.cuda.enable_flash_sdp(False)
    if args.disable_mem_efficient_sdp and hasattr(torch.backends.cuda, "enable_mem_efficient_sdp"):
        torch.backends.cuda.enable_mem_efficient_sdp(False)
    if args.enable_math_sdp and hasattr(torch.backends.cuda, "enable_math_sdp"):
        torch.backends.cuda.enable_math_sdp(True)


def _patch_ddp_init_sync(args: argparse.Namespace) -> None:
    if not args.ddp_init_sync:
        import torch.nn.parallel as parallel

        original_ddp = parallel.DistributedDataParallel

        class PatchedDistributedDataParallel(original_ddp):
            def __init__(self, module, *ddp_args, **ddp_kwargs):
                ddp_kwargs.setdefault("init_sync", False)
                super().__init__(module, *ddp_args, **ddp_kwargs)

        parallel.DistributedDataParallel = PatchedDistributedDataParallel
        torch.nn.parallel.DistributedDataParallel = PatchedDistributedDataParallel
        _log("patched DistributedDataParallel init_sync=False")


def _find_sublist(haystack: list[int], needle: list[int]) -> int | None:
    if not needle:
        return None
    max_i = len(haystack) - len(needle)
    for i in range(max_i + 1):
        if haystack[i : i + len(needle)] == needle:
            return i
    return None


class Qwen3VLChatDataCollator:
    """
    Collator that:
    1) builds a full chat transcript with the model's chat_template (includes image tokens),
    2) loads the referenced image from example["images"][0],
    3) uses the Qwen3-VL processor to produce tensors,
    4) masks labels so loss only applies to assistant tokens.
    """

    def __init__(
        self,
        *,
        processor: Any,
        max_seq_len: int,
        min_image_pixels: int | None = None,
        max_image_pixels: int | None = None,
    ) -> None:
        self.processor = processor
        self.max_seq_len = int(max_seq_len)
        self.min_image_pixels = None if min_image_pixels is None else int(min_image_pixels)
        self.max_image_pixels = None if max_image_pixels is None else int(max_image_pixels)
        # Train only on assistant content, not on user/system.
        self.assistant_header_ids = processor.tokenizer.encode(
            "<|im_start|>assistant\n", add_special_tokens=False
        )

    def _load_image(self, image_path: str) -> Image.Image:
        image = Image.open(image_path).convert("RGB")
        if self.max_image_pixels is None:
            return image
        area = image.width * image.height
        if area <= self.max_image_pixels:
            return image
        scale = (self.max_image_pixels / float(area)) ** 0.5
        size = (max(1, int(image.width * scale)), max(1, int(image.height * scale)))
        return image.resize(size, Image.Resampling.LANCZOS)

    def __call__(self, examples: list[dict[str, Any]]) -> dict[str, torch.Tensor]:
        texts: list[str] = []
        images: list[Image.Image] = []
        for ex in examples:
            msgs = ex["messages"]
            # Datasets may add None-valued union fields (e.g. image=None on text blocks).
            # Some Qwen3-VL processor builds treat the mere presence of "image" as an image block.
            clean_msgs = []
            for msg in msgs:
                content = msg.get("content", [])
                clean_content = []
                for item in content:
                    if isinstance(item, dict):
                        clean_content.append({k: v for k, v in item.items() if v is not None})
                    else:
                        clean_content.append(item)
                clean_msgs.append({**msg, "content": clean_content})
            image_path = ex["images"][0]
            text = self.processor.apply_chat_template(clean_msgs, tokenize=False, add_generation_prompt=False)

            # Important: do NOT use processor/tokenizer truncation for Qwen3-VL multi-modal inputs.
            # Truncation may drop special vision placeholders and triggers a mismatch between text/image tokens.
            # Instead, we hard-fail early so the user can increase --max-seq-len or shorten prompts.
            token_len = len(self.processor.tokenizer.encode(text, add_special_tokens=False))
            if token_len > self.max_seq_len:
                raise ValueError(
                    f"Sequence too long after chat template: {token_len} tokens > max_seq_len={self.max_seq_len}. "
                    "Increase --max-seq-len or shorten the prompt/instruction."
                )

            img = self._load_image(image_path)
            texts.append(text)
            images.append(img)

        batch = self.processor(
            text=texts,
            images=images,
            min_pixels=self.min_image_pixels,
            max_pixels=self.max_image_pixels,
            return_tensors="pt",
            padding=True,
            # no truncation (see comment above)
        )
        input_ids: torch.Tensor = batch["input_ids"]
        attention_mask: torch.Tensor = batch["attention_mask"]

        # Note: Qwen3-VL expands a single "<image>" placeholder into many image tokens based on image size.
        # This means the *true* sequence length can exceed the text-only token_len check above.
        seq_len = int(input_ids.shape[1])
        if seq_len > self.max_seq_len:
            per_sample_lens = attention_mask.sum(dim=1).tolist()
            raise ValueError(
                f"Batch sequence too long after multimodal expansion/padding: seq_len={seq_len} > max_seq_len={self.max_seq_len}. "
                f"Per-sample lengths (attention_mask sums): {per_sample_lens}. "
                "Fix by reducing image resolution (or setting --max-image-pixels), shortening prompts, or increasing --max-seq-len."
            )
        labels = input_ids.clone()

        # Mask: everything before "<|im_start|>assistant\n" (inclusive).
        # Also mask padding.
        for i in range(labels.shape[0]):
            ids = input_ids[i].tolist()
            start = _find_sublist(ids, self.assistant_header_ids)
            if start is None:
                # Fallback: train on the entire sequence if template search fails.
                cut = 0
            else:
                cut = start + len(self.assistant_header_ids)
            labels[i, :cut] = -100

        labels = labels.masked_fill(attention_mask == 0, -100)
        batch["labels"] = labels
        return batch


class StableSFTTrainer(SFTTrainer):
    def __init__(self, *args, disable_train_metrics_gather: bool = False, **kwargs):
        super().__init__(*args, **kwargs)
        self.disable_train_metrics_gather = disable_train_metrics_gather

    def compute_loss(self, model, inputs, return_outputs=False, num_items_in_batch=None):
        if self.disable_train_metrics_gather:
            inputs["use_cache"] = False
            return Trainer.compute_loss(
                self,
                model,
                inputs,
                return_outputs=return_outputs,
                num_items_in_batch=num_items_in_batch,
            )
        return super().compute_loss(
            model,
            inputs,
            return_outputs=return_outputs,
            num_items_in_batch=num_items_in_batch,
        )


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="TRL SFT (LoRA/QLoRA) for Qwen3-VL on chat+image JSONL.")
    p.add_argument("--model", type=Path, required=True, help="Local model path, e.g. /opt/models/qwen3-vl-4b")
    p.add_argument("--train-jsonl", type=Path, required=True)
    p.add_argument("--eval-jsonl", type=Path, default=None)
    p.add_argument("--do-eval", action="store_true", help="Enable periodic evaluation (can increase VRAM use).")
    p.add_argument("--output-dir", type=Path, required=True)

    p.add_argument("--max-seq-len", type=int, default=4096)
    p.add_argument(
        "--min-image-pixels",
        type=int,
        default=None,
        help="Optional clamp for Qwen3-VL image tokenization. If set, images smaller than this will be upscaled before patching.",
    )
    p.add_argument(
        "--max-image-pixels",
        type=int,
        default=None,
        help="Optional clamp for Qwen3-VL image tokenization. Strongly recommended to bound vision token count and VRAM.",
    )
    p.add_argument("--num-train-epochs", type=float, default=1.0)
    p.add_argument("--max-steps", type=int, default=-1, help="If >0, override epochs and run for max_steps.")
    p.add_argument("--per-device-train-batch-size", type=int, default=1)
    p.add_argument("--per-device-eval-batch-size", type=int, default=1)
    p.add_argument("--gradient-accumulation-steps", type=int, default=8)
    p.add_argument("--dataloader-num-workers", type=int, default=0)
    p.add_argument("--learning-rate", type=float, default=2e-4)
    p.add_argument("--warmup-ratio", type=float, default=0.03)
    p.add_argument("--weight-decay", type=float, default=0.0)
    p.add_argument(
        "--optim",
        type=str,
        default="adamw_torch",
        help="Optimizer passed to TrainingArguments. Use adamw_torch_fused only after the stable path works.",
    )

    p.add_argument("--logging-steps", type=int, default=1)
    p.add_argument("--save-steps", type=int, default=50)
    p.add_argument("--eval-steps", type=int, default=50)
    p.add_argument("--save-total-limit", type=int, default=2)

    p.add_argument("--qlora", action="store_true", help="Load model in 4-bit NF4 (bitsandbytes) + LoRA.")
    p.add_argument("--lora-r", type=int, default=16)
    p.add_argument("--lora-alpha", type=int, default=32)
    p.add_argument("--lora-dropout", type=float, default=0.05)
    p.add_argument(
        "--attn-implementation",
        type=str,
        default="eager",
        choices=["eager", "sdpa", "flash_attention_2"],
        help="Attention implementation for from_pretrained. eager is slower but avoids fused SDP kernels while debugging segfaults.",
    )
    p.add_argument(
        "--dtype",
        type=str,
        default="bf16",
        choices=["bf16", "fp16", "fp32"],
        help="Model/training dtype. bf16 is preferred on Ampere+; fp32 is useful for CPU or kernel debugging.",
    )
    p.add_argument(
        "--tf32",
        type=_str_to_bool,
        default=True,
        help="Enable TF32 matmul/cudnn paths on supported NVIDIA GPUs.",
    )
    p.add_argument(
        "--gradient-checkpointing",
        type=_str_to_bool,
        default=True,
        help="Enable model gradient checkpointing.",
    )
    p.add_argument(
        "--gradient-checkpointing-use-reentrant",
        type=_str_to_bool,
        default=False,
        help="Use PyTorch's reentrant checkpointing implementation.",
    )
    p.add_argument(
        "--ddp-find-unused-parameters",
        type=_str_to_bool,
        default=False,
        help="Passed to TrainingArguments. False avoids extra graph traversal for LoRA/DDP.",
    )
    p.add_argument(
        "--ddp-init-sync",
        type=_str_to_bool,
        default=False,
        help=(
            "Whether DDP should verify parameter shapes and broadcast initial parameters during __init__. "
            "False works around a PyTorch/NCCL segfault in _verify_param_shape_across_processes on this stack."
        ),
    )
    p.add_argument(
        "--ddp-broadcast-buffers",
        type=_str_to_bool,
        default=False,
        help="Passed to TrainingArguments. False avoids DDP buffer broadcasts before every forward.",
    )
    p.add_argument(
        "--disable-train-metrics-gather",
        type=_str_to_bool,
        default=True,
        help="Disable TRL SFTTrainer's per-step distributed metric gathers during training.",
    )
    p.add_argument(
        "--disable-flash-sdp",
        type=_str_to_bool,
        default=True,
        help="Disable PyTorch flash SDP kernels before loading the model.",
    )
    p.add_argument(
        "--disable-mem-efficient-sdp",
        type=_str_to_bool,
        default=True,
        help="Disable PyTorch memory-efficient SDP kernels before loading the model.",
    )
    p.add_argument(
        "--enable-math-sdp",
        type=_str_to_bool,
        default=True,
        help="Keep PyTorch math SDP kernels enabled.",
    )
    p.add_argument(
        "--debug-stage-dir",
        type=Path,
        default=None,
        help="If set, write each rank's latest execution stage to this directory.",
    )
    p.add_argument(
        "--debug-stop-after",
        type=str,
        default=None,
        choices=[
            "runtime_configured",
            "processor_loaded",
            "datasets_loaded",
            "model_loaded",
            "gradient_checkpointing_enabled",
            "trainer_built",
        ],
        help="Exit cleanly after the named stage. Useful for isolating native crashes.",
    )

    # Experiment tracking
    p.add_argument(
        "--report-to",
        type=str,
        default="none",
        choices=["none", "wandb"],
        help="Enable experiment reporting. Use 'wandb' if you want Weights & Biases logging.",
    )
    p.add_argument("--run-name", type=str, default=None, help="Optional run name (TrainingArguments.run_name).")
    p.add_argument("--wandb-project", type=str, default=None, help="If set, overrides env WANDB_PROJECT.")
    p.add_argument("--wandb-entity", type=str, default=None, help="If set, overrides env WANDB_ENTITY.")
    p.add_argument(
        "--wandb-tags",
        type=str,
        default=None,
        help="Comma-separated tags. If set, overrides env WANDB_TAGS.",
    )
    p.add_argument(
        "--wandb-mode",
        type=str,
        default=None,
        choices=["online", "offline", "disabled"],
        help="If set, overrides env WANDB_MODE.",
    )

    return p.parse_args()


def main() -> None:
    faulthandler.enable(file=sys.stderr, all_threads=True)
    args = parse_args()
    if args.do_eval and args.eval_jsonl is None:
        raise ValueError("--do-eval requires --eval-jsonl")
    args.output_dir.mkdir(parents=True, exist_ok=True)

    _configure_torch_runtime(args)
    _patch_ddp_init_sync(args)
    _mark_stage(args, "runtime_configured")
    if _stop_after(args, "runtime_configured"):
        return

    dtype_by_name = {
        "bf16": torch.bfloat16,
        "fp16": torch.float16,
        "fp32": torch.float32,
    }
    model_dtype = dtype_by_name[args.dtype]
    training_tf32 = args.tf32 if torch.cuda.is_available() else None
    gradient_checkpointing_kwargs = {
        "use_reentrant": args.gradient_checkpointing_use_reentrant,
    }

    _log(
        "runtime "
        f"torch={torch.__version__} cuda_runtime={torch.version.cuda} cuda_available={torch.cuda.is_available()} "
        f"world_size={os.environ.get('WORLD_SIZE', '1')} "
        f"attn={args.attn_implementation} dtype={args.dtype} optim={args.optim} "
        f"max_image_pixels={args.max_image_pixels} "
        f"disable_train_metrics_gather={args.disable_train_metrics_gather} "
        f"flash_sdp_disabled={args.disable_flash_sdp} mem_efficient_sdp_disabled={args.disable_mem_efficient_sdp}"
    )
    _mark_stage(args, "loading_processor")
    processor = AutoProcessor.from_pretrained(args.model, trust_remote_code=True)
    _mark_stage(args, "processor_loaded")
    if _stop_after(args, "processor_loaded"):
        return

    _mark_stage(args, "loading_datasets")
    data_files: dict[str, str] = {"train": str(args.train_jsonl)}
    if args.do_eval and args.eval_jsonl is not None:
        data_files["validation"] = str(args.eval_jsonl)
    ds = load_dataset("json", data_files=data_files)
    train_ds = ds["train"]
    eval_ds = ds["validation"] if "validation" in ds else None
    _mark_stage(args, "datasets_loaded")
    if _stop_after(args, "datasets_loaded"):
        return

    quant_config = None
    if args.qlora:
        quant_config = BitsAndBytesConfig(
            load_in_4bit=True,
            bnb_4bit_quant_type="nf4",
            bnb_4bit_use_double_quant=True,
            bnb_4bit_compute_dtype=model_dtype,
        )

    is_distributed = int(os.environ.get("WORLD_SIZE", "1")) > 1
    device_map = None if is_distributed else "auto"
    _mark_stage(args, f"loading_model distributed={is_distributed} device_map={device_map}")
    model = Qwen3VLForConditionalGeneration.from_pretrained(
        args.model,
        trust_remote_code=True,
        torch_dtype=model_dtype,
        device_map=device_map,
        quantization_config=quant_config,
        attn_implementation=args.attn_implementation,
    )
    _mark_stage(args, "model_loaded")
    if _stop_after(args, "model_loaded"):
        return

    # Avoid KV cache allocations during training.
    model.config.use_cache = False

    if args.gradient_checkpointing:
        _mark_stage(args, f"enabling_gradient_checkpointing use_reentrant={args.gradient_checkpointing_use_reentrant}")
        if args.qlora:
            model = prepare_model_for_kbit_training(
                model,
                use_gradient_checkpointing=True,
                gradient_checkpointing_kwargs=gradient_checkpointing_kwargs,
            )
        else:
            model.gradient_checkpointing_enable(gradient_checkpointing_kwargs=gradient_checkpointing_kwargs)
    _mark_stage(args, "gradient_checkpointing_enabled")
    if _stop_after(args, "gradient_checkpointing_enabled"):
        return

    peft_config = LoraConfig(
        r=args.lora_r,
        lora_alpha=args.lora_alpha,
        lora_dropout=args.lora_dropout,
        bias="none",
        task_type="CAUSAL_LM",
        # Conservative set that matches Qwen-family transformer blocks.
        target_modules=["q_proj", "k_proj", "v_proj", "o_proj", "gate_proj", "up_proj", "down_proj"],
    )

    report_to: list[str] = []
    run_name = args.run_name
    if args.report_to == "wandb":
        # These env vars are the standard way for W&B to pick up config without requiring extra code.
        if args.wandb_project:
            os.environ["WANDB_PROJECT"] = args.wandb_project
        if args.wandb_entity:
            os.environ["WANDB_ENTITY"] = args.wandb_entity
        if args.wandb_tags:
            os.environ["WANDB_TAGS"] = args.wandb_tags
        if args.wandb_mode:
            os.environ["WANDB_MODE"] = args.wandb_mode
        report_to = ["wandb"]
        if run_name is None:
            run_name = args.output_dir.name

    training_args = TrainingArguments(
        output_dir=str(args.output_dir),
        run_name=run_name,
        num_train_epochs=args.num_train_epochs,
        max_steps=args.max_steps,
        per_device_train_batch_size=args.per_device_train_batch_size,
        per_device_eval_batch_size=args.per_device_eval_batch_size,
        gradient_accumulation_steps=args.gradient_accumulation_steps,
        learning_rate=args.learning_rate,
        warmup_ratio=args.warmup_ratio,
        weight_decay=args.weight_decay,
        optim=args.optim,
        bf16=args.dtype == "bf16",
        fp16=args.dtype == "fp16",
        tf32=training_tf32,
        gradient_checkpointing=args.gradient_checkpointing,
        gradient_checkpointing_kwargs=gradient_checkpointing_kwargs,
        logging_steps=args.logging_steps,
        save_steps=args.save_steps,
        eval_steps=args.eval_steps,
        eval_strategy="steps" if eval_ds is not None else "no",
        save_total_limit=args.save_total_limit,
        save_strategy="steps",
        report_to=report_to,
        remove_unused_columns=False,  # keep messages/images for our custom collator
        dataloader_num_workers=args.dataloader_num_workers,
        dataloader_persistent_workers=False,
        ddp_find_unused_parameters=args.ddp_find_unused_parameters,
        ddp_broadcast_buffers=args.ddp_broadcast_buffers,
    )

    # Compatibility for TRL 0.20 with newer Transformers TrainingArguments.
    _training_args_to_dict = training_args.to_dict
    def _training_args_to_dict_compat():
        _d = _training_args_to_dict()
        _d.setdefault("push_to_hub_token", None)
        _d.setdefault("dataset_kwargs", {"skip_prepare_dataset": True})
        return _d
    training_args.to_dict = _training_args_to_dict_compat

    collator = Qwen3VLChatDataCollator(
        processor=processor,
        max_seq_len=args.max_seq_len,
        min_image_pixels=args.min_image_pixels,
        max_image_pixels=args.max_image_pixels,
    )

    _mark_stage(args, "building_trainer")
    trainer = StableSFTTrainer(
        model=model,
        args=training_args,
        train_dataset=train_ds,
        eval_dataset=eval_ds,
        data_collator=collator,
        peft_config=peft_config,
        processing_class=processor,  # for saving tokenizer/processor alongside adapters
        disable_train_metrics_gather=args.disable_train_metrics_gather,
    )
    _mark_stage(args, "trainer_built")
    if _stop_after(args, "trainer_built"):
        return

    _mark_stage(args, "starting_train")
    trainer.train()
    _mark_stage(args, "saving_model")
    trainer.save_model()
    processor.save_pretrained(args.output_dir)
    _mark_stage(args, "done")


if __name__ == "__main__":
    main()
