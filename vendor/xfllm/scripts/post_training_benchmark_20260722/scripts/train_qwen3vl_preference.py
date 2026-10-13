#!/usr/bin/env python3
"""Train Qwen3-VL with DPO/IPO/SimPO from the same merged SFT start.

For DPO/IPO the SFT LoRA is merged first, then a fresh preference LoRA is
attached.  With ref_model=None, disabling the fresh adapter recovers the merged
SFT policy, which is the intended reference rather than the original base model.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import types
from typing import Any

import torch
import torch.nn.functional as F
from datasets import Image as DatasetImage
from datasets import Sequence, load_dataset
from peft import LoraConfig, PeftModel
from PIL import Image as PILImage
from transformers import AutoProcessor, Qwen3VLForConditionalGeneration
from trl import DPOConfig, DPOTrainer
from trl.trainer.dpo_trainer import DataCollatorForPreference


class Qwen3VLPreferenceCollator(DataCollatorForPreference):
    """Flatten variable-length Qwen3-VL patches instead of image-padding them."""

    def torch_call(self, examples):
        output = super().torch_call(examples)
        # Qwen3-VL pixel_values is [num_patches, patch_features].  The generic
        # TRL collator pads it to [batch, max_patches, patch_features], while
        # Qwen3-VL expects all patches flattened and delimited by grid rows.
        output["pixel_values"] = torch.cat(
            [torch.as_tensor(example["pixel_values"]) for example in examples], dim=0
        )
        return output


class Qwen3VLDPOTrainer(DPOTrainer):
    """TRL 0.20 DPO VLM adapter for Qwen3-VL's image_grid_thw field.

    TRL 0.20 preserves the older generic name ``image_sizes`` end-to-end but
    drops Qwen3-VL's ``image_grid_thw``.  We carry the grid through that slot;
    ``enable_qwen3vl_grid_alias`` maps it back at model.forward.  This leaves the
    installed TRL package untouched and keeps the compatibility change local.
    """

    @staticmethod
    def process_row(
        features: dict[str, Any],
        processing_class: Any,
        max_prompt_length: int | None = None,
        max_completion_length: int | None = None,
        add_special_tokens: bool = True,
    ) -> dict[str, Any]:
        processor, tokenizer = processing_class, processing_class.tokenizer
        max_pixels = int(getattr(processor, "_hydrant_max_image_pixels", 131072))
        resized_images = []
        for image in features["images"]:
            image = image.convert("RGB")
            area = image.width * image.height
            if area > max_pixels:
                scale = (max_pixels / float(area)) ** 0.5
                size = (max(1, int(image.width * scale)), max(1, int(image.height * scale)))
                image = image.resize(size, PILImage.Resampling.LANCZOS)
            resized_images.append(image)
        processed = processor(images=resized_images, text=features["prompt"], add_special_tokens=False)
        prompt_ids = processed["input_ids"][0]
        chosen_ids = tokenizer(features["chosen"], add_special_tokens=False)["input_ids"]
        rejected_ids = tokenizer(features["rejected"], add_special_tokens=False)["input_ids"]
        if add_special_tokens:
            if tokenizer.bos_token_id is not None:
                prompt_ids = [tokenizer.bos_token_id] + prompt_ids
            if tokenizer.eos_token_id is not None:
                prompt_ids = prompt_ids + [tokenizer.eos_token_id]
        chosen_ids = chosen_ids + [tokenizer.eos_token_id]
        rejected_ids = rejected_ids + [tokenizer.eos_token_id]
        if max_prompt_length is not None and len(prompt_ids) > max_prompt_length:
            raise ValueError(
                f"Qwen3-VL prompt has {len(prompt_ids)} tokens > max_prompt_length={max_prompt_length}; "
                "do not truncate image placeholders. Shorten the prompt or reduce --max-image-pixels."
            )
        if max_completion_length is not None:
            chosen_ids = chosen_ids[:max_completion_length]
            rejected_ids = rejected_ids[:max_completion_length]
        output = {
            "prompt_input_ids": prompt_ids,
            # Unlike Llava-style processors, Qwen3-VL returns a flattened
            # variable-length patch matrix with no leading batch dimension.
            "pixel_values": processed["pixel_values"],
            "chosen_input_ids": chosen_ids,
            "rejected_input_ids": rejected_ids,
            # Compatibility carrier; restored to image_grid_thw before forward.
            "image_sizes": processed["image_grid_thw"][0],
        }
        if "pixel_attention_mask" in processed:
            output["pixel_attention_mask"] = processed["pixel_attention_mask"][0]
        return output


class Qwen3VLSimPOTrainer(Qwen3VLDPOTrainer):
    """Exact reference-free, length-normalized SimPO pairwise objective.

    DPOConfig uses ``loss_type=ipo`` only to request mean (rather than summed)
    completion log-probabilities from TRL's forward pass.  The loss below is the
    SimPO objective; no IPO loss and no reference forward are used.
    """

    def __init__(self, *trainer_args, simpo_gamma: float = 0.5, **trainer_kwargs):
        self.simpo_gamma = float(simpo_gamma)
        super().__init__(*trainer_args, **trainer_kwargs)

    def compute_ref_log_probs(self, batch):
        batch_size = batch["prompt_input_ids"].shape[0]
        zeros = torch.zeros(batch_size, device=self.accelerator.device)
        return zeros, zeros

    def dpo_loss(
        self,
        chosen_logps,
        rejected_logps,
        ref_chosen_logps,
        ref_rejected_logps,
        loss_type="ipo",
        model_output=None,
    ):
        device = self.accelerator.device
        chosen_logps = chosen_logps.to(device)
        rejected_logps = rejected_logps.to(device)
        logits = chosen_logps - rejected_logps - self.simpo_gamma / self.beta
        losses = -F.logsigmoid(self.beta * logits)
        chosen_rewards = (self.beta * chosen_logps).detach()
        rejected_rewards = (self.beta * rejected_logps).detach()
        return losses, chosen_rewards, rejected_rewards


def enable_qwen3vl_grid_alias(model: torch.nn.Module) -> None:
    original_forward = model.forward

    def forward_with_grid_alias(self, *model_args, image_sizes=None, image_grid_thw=None, **model_kwargs):
        if image_grid_thw is None:
            image_grid_thw = image_sizes
        return original_forward(*model_args, image_grid_thw=image_grid_thw, **model_kwargs)

    model.forward = types.MethodType(forward_with_grid_alias, model)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--method", choices=["dpo", "ipo", "simpo"], required=True)
    parser.add_argument("--model", default="/opt/models/qwen3-vl-4b")
    parser.add_argument(
        "--sft-adapter",
        default="/opt/xfagent/artifacts/trl/qwen3vl4b_hydrant_sft_grpo_v41_full_20260717/sft_model/checkpoint-400",
    )
    parser.add_argument(
        "--train-jsonl",
        default="/opt/datasets/fire-inspection/training_data/20260722_hydrant_preference_v1/train.jsonl",
    )
    parser.add_argument(
        "--validation-jsonl",
        default="/opt/datasets/fire-inspection/training_data/20260722_hydrant_preference_v1/validation.jsonl",
    )
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--max-steps", type=int, default=100)
    parser.add_argument("--per-device-train-batch-size", type=int, default=1)
    parser.add_argument("--per-device-eval-batch-size", type=int, default=1)
    parser.add_argument("--gradient-accumulation-steps", type=int, default=4)
    parser.add_argument("--learning-rate", type=float, default=5e-7)
    parser.add_argument("--warmup-ratio", type=float, default=0.05)
    parser.add_argument("--beta", type=float)
    parser.add_argument("--simpo-gamma", type=float, default=0.5)
    parser.add_argument("--max-prompt-length", type=int, default=2048)
    parser.add_argument("--max-completion-length", type=int, default=256)
    parser.add_argument("--max-image-pixels", type=int, default=131072)
    parser.add_argument("--eval-steps", type=int, default=20)
    parser.add_argument("--save-steps", type=int, default=20)
    parser.add_argument("--save-total-limit", type=int, default=6)
    parser.add_argument("--logging-steps", type=int, default=1)
    parser.add_argument("--seed", type=int, default=20260722)
    parser.add_argument("--report-to", choices=["none", "wandb"], default="wandb")
    parser.add_argument("--wandb-project", default="qwen3vl_hydrant_post_training_benchmark")
    parser.add_argument("--wandb-entity")
    parser.add_argument("--run-name")
    parser.add_argument("--train-limit", type=int, default=0)
    parser.add_argument("--validation-limit", type=int, default=0)
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def load_preference_dataset(train_path: str, validation_path: str, train_limit: int, val_limit: int):
    datasets = load_dataset("json", data_files={"train": train_path, "validation": validation_path})
    for split, limit in (("train", train_limit), ("validation", val_limit)):
        if limit > 0:
            datasets[split] = datasets[split].select(range(min(limit, len(datasets[split]))))
        datasets[split] = datasets[split].cast_column("images", Sequence(DatasetImage()))
    return datasets


def dataset_audit(datasets) -> dict[str, Any]:
    train_sha1 = set(datasets["train"]["meta"][i]["image_sha1"] for i in range(len(datasets["train"])))
    val_sha1 = set(datasets["validation"]["meta"][i]["image_sha1"] for i in range(len(datasets["validation"])))
    return {
        "train_rows": len(datasets["train"]),
        "validation_rows": len(datasets["validation"]),
        "train_unique_images": len(train_sha1),
        "validation_unique_images": len(val_sha1),
        "image_overlap": len(train_sha1 & val_sha1),
    }


def merged_sft_model(model_path: str, adapter_path: str):
    base = Qwen3VLForConditionalGeneration.from_pretrained(
        model_path,
        trust_remote_code=True,
        torch_dtype=torch.bfloat16,
        attn_implementation="sdpa",
    )
    merged = PeftModel.from_pretrained(base, adapter_path, is_trainable=False).merge_and_unload()
    # PEFT leaves metadata on some versions after merge; a fresh preference
    # adapter must be the only active adapter.
    if hasattr(merged, "peft_config"):
        delattr(merged, "peft_config")
    enable_qwen3vl_grid_alias(merged)
    return merged


def common_training_kwargs(args: argparse.Namespace) -> dict[str, Any]:
    return {
        "output_dir": args.output_dir,
        "overwrite_output_dir": True,
        "max_steps": args.max_steps,
        "per_device_train_batch_size": args.per_device_train_batch_size,
        "per_device_eval_batch_size": args.per_device_eval_batch_size,
        "gradient_accumulation_steps": args.gradient_accumulation_steps,
        "learning_rate": args.learning_rate,
        "warmup_ratio": args.warmup_ratio,
        "lr_scheduler_type": "cosine",
        "bf16": True,
        "tf32": True,
        "gradient_checkpointing": True,
        "gradient_checkpointing_kwargs": {"use_reentrant": False},
        "max_prompt_length": args.max_prompt_length,
        "max_completion_length": args.max_completion_length,
        # DPOTrainer applies a second, total-sequence truncation immediately
        # before forward.  Its default max_length can remove Qwen3-VL image
        # placeholder tokens while leaving pixel_values/image_grid_thw intact,
        # producing "image features and image tokens do not match".  Keep the
        # full audited prompt plus the configured completion budget.
        "max_length": args.max_prompt_length + args.max_completion_length,
        "eval_strategy": "steps",
        "eval_steps": args.eval_steps,
        "save_strategy": "steps",
        "save_steps": args.save_steps,
        "save_total_limit": args.save_total_limit,
        "logging_steps": args.logging_steps,
        "logging_first_step": True,
        "report_to": args.report_to,
        "run_name": args.run_name,
        "remove_unused_columns": False,
        "dataloader_num_workers": 0,
        "ddp_find_unused_parameters": False,
        "seed": args.seed,
    }


def main() -> None:
    args = parse_args()
    if args.report_to == "wandb":
        os.environ["WANDB_PROJECT"] = args.wandb_project
        if args.wandb_entity:
            os.environ["WANDB_ENTITY"] = args.wandb_entity

    datasets = load_preference_dataset(
        args.train_jsonl, args.validation_jsonl, args.train_limit, args.validation_limit
    )
    audit = dataset_audit(datasets)
    print(json.dumps(audit, ensure_ascii=False, indent=2), flush=True)
    if audit["image_overlap"]:
        raise ValueError("preference train/validation image leakage detected")
    if args.dry_run:
        return

    processor = AutoProcessor.from_pretrained(args.model, trust_remote_code=True)
    processor.tokenizer.padding_side = "left"
    processor._hydrant_max_image_pixels = args.max_image_pixels
    if hasattr(processor, "image_processor"):
        processor.image_processor.max_pixels = args.max_image_pixels
    model = merged_sft_model(args.model, args.sft_adapter)
    model.config.use_cache = False
    peft_config = LoraConfig(
        r=16,
        lora_alpha=32,
        lora_dropout=0.05,
        bias="none",
        task_type="CAUSAL_LM",
        target_modules=["q_proj", "k_proj", "v_proj", "o_proj"],
    )

    kwargs = common_training_kwargs(args)
    if args.method in {"dpo", "ipo"}:
        beta = args.beta if args.beta is not None else 0.1
        config = DPOConfig(loss_type="sigmoid" if args.method == "dpo" else "ipo", beta=beta, **kwargs)
        trainer = Qwen3VLDPOTrainer(
            model=model,
            ref_model=None,
            args=config,
            train_dataset=datasets["train"],
            eval_dataset=datasets["validation"],
            processing_class=processor,
            peft_config=peft_config,
            data_collator=Qwen3VLPreferenceCollator(
                pad_token_id=processor.tokenizer.pad_token_id,
                return_tensors="pt",
            ),
        )
    else:
        beta = args.beta if args.beta is not None else 2.0
        config = DPOConfig(
            # TRL averages completion log-probs when "ipo" is present; the
            # trainer override above supplies the actual SimPO loss.
            loss_type="ipo",
            beta=beta,
            reference_free=True,
            **kwargs,
        )
        trainer = Qwen3VLSimPOTrainer(
            model=model,
            ref_model=None,
            args=config,
            train_dataset=datasets["train"],
            eval_dataset=datasets["validation"],
            processing_class=processor,
            peft_config=peft_config,
            simpo_gamma=args.simpo_gamma,
            data_collator=Qwen3VLPreferenceCollator(
                pad_token_id=processor.tokenizer.pad_token_id,
                return_tensors="pt",
            ),
        )

    result = trainer.train()
    trainer.save_model(args.output_dir)
    if trainer.accelerator.is_main_process:
        output = Path(args.output_dir)
        (output / "train_metrics.json").write_text(
            json.dumps(result.metrics, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        (output / "dataset_audit.json").write_text(
            json.dumps(audit, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        (output / "experiment_config.json").write_text(
            json.dumps(vars(args), ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        print(json.dumps(result.metrics, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
