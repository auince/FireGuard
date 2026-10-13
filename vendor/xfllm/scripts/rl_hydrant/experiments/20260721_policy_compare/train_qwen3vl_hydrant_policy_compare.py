#!/usr/bin/env python3
from __future__ import annotations

import argparse
from collections import Counter
import importlib
import json
import math
import os
import random
import sys
import types
from pathlib import Path
from typing import Any

import torch
from datasets import Dataset, Image as DatasetImage
from peft import LoraConfig, PeftModel
from PIL import Image as PILImage
from transformers import AutoProcessor, Qwen3VLForConditionalGeneration


COMPACT_PROMPT = """你是消防设施巡检助手。只根据图片中清晰可见的内容检查室内消火栓，不得把遮挡、反光、模糊或画面外的项目推测为异常。

检查范围只能选：内部组件、箱体外观、无法确定。
内部组件标签只能选：室内消火栓手轮缺失；室内消火栓栓口方向错误；室内消火栓无消防水带；室内消火栓无消防水枪；室内消火栓消防接口缺失；消防软管卷盘供水管道折弯严重；室内消火栓无箱体；室内消火栓箱锈蚀；室内消火栓箱门缺失。
箱体外观标签只能选：室内消火栓箱明显部位未采用耐久性文字或图形标注操作说明；室内消火栓箱门上未标注“消火栓”和英文“FIRE HYDRANT”字样；室内消火栓箱体无铭牌；室内消火栓箱门标识模糊；室内消火栓箱体铭牌模糊；室内消火栓箱门为玻璃门；室内消火栓箱体或箱门被物品遮挡。

有隐患标签则结论为“不合规”，无隐患标签则为“合规”；证据不足时写“无法判断”。不要输出思维链。请在 220 个中文词以内，严格按以下顺序输出：
检查范围：...
结论：...
隐患标签：多个用“；”分隔，无则写“无”
可见证据：用 1 至 3 句说明可见依据和看不清的项目。"""


def import_trl(*, disable_broken_vllm: bool):
    """TRL 0.20 imports its vLLM client eagerly, even when use_vllm=False."""
    if disable_broken_vllm:
        import trl
        import trl.import_utils as trl_import_utils

        stub = types.ModuleType("trl.extras.vllm_client")

        class DisabledVLLMClient:
            def __init__(self, *_: Any, **__: Any) -> None:
                raise RuntimeError("vLLM was explicitly disabled because its binary is incompatible with PyTorch")

        stub.VLLMClient = DisabledVLLMClient
        sys.modules["trl.extras.vllm_client"] = stub
        trl_import_utils.is_vllm_available = lambda: False

    from trl import GRPOConfig, GRPOTrainer

    return GRPOConfig, GRPOTrainer


def assistant_text(row: dict[str, Any]) -> str:
    for message in row.get("messages", []):
        if message.get("role") != "assistant":
            continue
        content = message.get("content", "")
        if isinstance(content, str):
            return content
        return "\n".join(
            str(item.get("text", "")) for item in content if isinstance(item, dict) and item.get("type") == "text"
        )
    return ""


def user_text(row: dict[str, Any]) -> str:
    for message in row.get("messages", []):
        if message.get("role") != "user":
            continue
        content = message.get("content", "")
        if isinstance(content, str):
            return content
        return "\n".join(
            str(item.get("text", "")) for item in content if isinstance(item, dict) and item.get("type") == "text"
        )
    return ""


def normalize_scope(value: str) -> str:
    if value in {"appearance", "箱体外观"}:
        return "appearance"
    if value in {"internal", "internal_components", "内部组件"}:
        return "internal_components"
    return "unknown"


def _weighted_without_replacement(
    rows: list[dict[str, Any]], weights: list[float], count: int, rng: random.Random
) -> list[dict[str, Any]]:
    if count >= len(rows):
        return list(rows)
    ranked = sorted(
        zip(rows, weights),
        key=lambda item: rng.random() ** (1.0 / max(item[1], 1e-6)),
        reverse=True,
    )
    return [row for row, _ in ranked[:count]]


def load_dataset(
    path: str,
    *,
    limit: int,
    seed: int,
    parse_answer,
    compliant_fraction: float = 0.35,
    compact_prompt: bool = False,
    class_balanced_sampling: bool = False,
) -> Dataset:
    rows: list[dict[str, Any]] = []
    with open(path, encoding="utf-8") as handle:
        for line in handle:
            source = json.loads(line)
            image_paths = source.get("images") or []
            if not image_paths or not os.path.isfile(image_paths[0]):
                continue
            answer = assistant_text(source)
            parsed = parse_answer(answer)
            meta = source.get("meta") or {}
            labels = meta.get("defect_labels")
            if labels is None:
                labels = sorted(parsed["labels"])
            scope = normalize_scope(meta.get("task", ""))
            if scope == "unknown":
                scope = parsed["scope"]
            verdict = meta.get("verdict") or parsed["verdict"]
            rows.append(
                {
                    "id": source.get("id", f"row_{len(rows)}"),
                    "prompt": [{"role": "user", "content": COMPACT_PROMPT if compact_prompt else user_text(source)}],
                    "image": image_paths[0],
                    "gold_scope": scope,
                    "gold_verdict": verdict,
                    "gold_labels": list(labels),
                }
            )

    rng = random.Random(seed)
    is_compliant = lambda row: row["gold_verdict"] == "合规" and not row["gold_labels"]
    compliant = [row for row in rows if is_compliant(row)]
    defective = [row for row in rows if not is_compliant(row)]
    if limit > 0 and 0 < compliant_fraction < 1:
        normal_count = round(limit * compliant_fraction)
        defect_count = limit - normal_count
        selected_normal = (
            rng.sample(compliant, normal_count)
            if normal_count <= len(compliant)
            else rng.choices(compliant, k=normal_count)
        )
        if class_balanced_sampling:
            support: dict[str, int] = {}
            for row in defective:
                for label in row["gold_labels"]:
                    support[label] = support.get(label, 0) + 1
            max_support = max(support.values(), default=1)
            weights = []
            for row in defective:
                label_weights = [math.sqrt(max_support / max(support.get(label, 1), 1)) for label in row["gold_labels"]]
                weights.append(min(4.0, sum(label_weights) / len(label_weights)) if label_weights else 1.0)
            selected_defect = _weighted_without_replacement(defective, weights, defect_count, rng)
            if len(selected_defect) < defect_count:
                selected_defect += rng.choices(defective, weights=weights, k=defect_count - len(selected_defect))
        else:
            selected_defect = (
                rng.sample(defective, defect_count)
                if defect_count <= len(defective)
                else rng.choices(defective, k=defect_count)
            )
        rows = [dict(row, id=f"{row['id']}__rlsample_{index:05d}") for index, row in enumerate(selected_normal + selected_defect)]
    rng.shuffle(rows)
    image_cache: dict[str, PILImage.Image] = {}
    for row in rows:
        image_path = row["image"]
        if image_path not in image_cache:
            image = PILImage.open(image_path).convert("RGB")
            max_area = 131_072
            area = image.width * image.height
            if area > max_area:
                scale = (max_area / float(area)) ** 0.5
                size = (max(1, int(image.width * scale)), max(1, int(image.height * scale)))
                image = image.resize(size, PILImage.Resampling.LANCZOS)
            image_cache[image_path] = image
        row["image"] = image_cache[image_path]
    if not rows:
        raise ValueError(f"No usable rows found in {path}")
    return Dataset.from_list(rows).cast_column("image", DatasetImage())


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", default="/opt/models/Qwen3-VL-2B-Instruct")
    parser.add_argument(
        "--train-jsonl",
        default="/opt/datasets/fire-inspection/training_data/20260630_hydrant_auto_visible_reasoning_v5_ultra_strict_cleaned/train.jsonl",
    )
    parser.add_argument("--output-dir", default="/opt/xfagent/artifacts/trl/hydrant_qwen3vl2b_grpo_smoke")
    parser.add_argument("--limit", type=int, default=16)
    parser.add_argument("--max-steps", type=int, default=1)
    parser.add_argument("--max-prompt-length", type=int, default=2048)
    parser.add_argument("--max-completion-length", type=int, default=256)
    parser.add_argument("--num-generations", type=int, default=2)
    parser.add_argument("--per-device-train-batch-size", type=int, default=1)
    parser.add_argument("--gradient-accumulation-steps", type=int, default=1)
    parser.add_argument("--learning-rate", type=float, default=1e-6)
    parser.add_argument("--warmup-ratio", type=float, default=0.0)
    parser.add_argument("--lr-scheduler-type", default="linear")
    parser.add_argument("--temperature", type=float, default=0.9)
    parser.add_argument("--top-p", type=float, default=0.95)
    parser.add_argument("--beta", type=float, default=0.02)
    parser.add_argument("--loss-type", choices=["grpo", "bnpo", "dr_grpo"], default="dr_grpo")
    parser.add_argument(
        "--scale-rewards",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Divide within-prompt advantages by reward std. Dr.GRPO recommends --no-scale-rewards.",
    )
    parser.add_argument("--num-iterations", type=int, default=1)
    parser.add_argument("--epsilon", type=float, default=0.2)
    parser.add_argument("--epsilon-high", type=float)
    parser.add_argument("--delta", type=float)
    parser.add_argument("--mask-truncated-completions", action="store_true")
    parser.add_argument("--save-steps", type=int, default=0)
    parser.add_argument("--save-total-limit", type=int, default=6)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--compliant-fraction", type=float, default=0.35)
    parser.add_argument("--class-balanced-sampling", action="store_true")
    parser.add_argument("--compact-prompt", action="store_true")
    parser.add_argument("--reward-version", choices=["v2", "v3", "v4", "v41"], default="v2")
    parser.add_argument("--init-adapter")
    parser.add_argument("--report-to", choices=["none", "wandb"], default="none")
    parser.add_argument("--wandb-project", default="qwen3vl_hydrant_grpo")
    parser.add_argument("--wandb-entity")
    parser.add_argument("--wandb-run-name")
    parser.add_argument("--log-completions", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--disable-broken-vllm", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    reward_module = importlib.import_module({"v2": "hydrant_rewards", "v3": "hydrant_rewards_v3", "v4": "hydrant_rewards_v4", "v41": "hydrant_rewards_v41"}[args.reward_version])
    parse_answer = reward_module.parse_answer
    reward_functions = reward_module.REWARD_FUNCTIONS
    reward_weights = reward_module.REWARD_WEIGHTS
    dataset = load_dataset(
        args.train_jsonl,
        limit=args.limit,
        seed=args.seed,
        parse_answer=parse_answer,
        compliant_fraction=args.compliant_fraction,
        compact_prompt=args.compact_prompt,
        class_balanced_sampling=args.class_balanced_sampling,
    )
    print(dataset)
    print(json.dumps({k: dataset[0][k] for k in ("id", "gold_scope", "gold_verdict", "gold_labels")}, ensure_ascii=False))
    print(
        json.dumps(
            {
                "sampled_verdicts": dict(Counter(dataset["gold_verdict"])),
                "sampled_scopes": dict(Counter(dataset["gold_scope"])),
                "sampled_labels": dict(Counter(label for labels in dataset["gold_labels"] for label in labels)),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    if args.dry_run:
        return

    GRPOConfig, GRPOTrainer = import_trl(disable_broken_vllm=args.disable_broken_vllm)
    if args.report_to == "wandb":
        os.environ["WANDB_PROJECT"] = args.wandb_project
        if args.wandb_entity:
            os.environ["WANDB_ENTITY"] = args.wandb_entity
    processor = AutoProcessor.from_pretrained(args.model, trust_remote_code=True)
    processor.tokenizer.padding_side = "left"

    if args.init_adapter:
        base_model = Qwen3VLForConditionalGeneration.from_pretrained(
            args.model,
            trust_remote_code=True,
            torch_dtype=torch.bfloat16,
            attn_implementation="sdpa",
        )
        model_for_trainer = PeftModel.from_pretrained(base_model, args.init_adapter, is_trainable=True)
        peft_config = None
        model_init_kwargs = None
    else:
        model_for_trainer = args.model
        peft_config = LoraConfig(
            r=16,
            lora_alpha=32,
            lora_dropout=0.05,
            bias="none",
            task_type="CAUSAL_LM",
            target_modules=["q_proj", "k_proj", "v_proj", "o_proj"],
        )
        model_init_kwargs = {
            "trust_remote_code": True,
            "torch_dtype": torch.bfloat16,
            "attn_implementation": "sdpa",
        }
    config = GRPOConfig(
        output_dir=args.output_dir,
        overwrite_output_dir=True,
        max_steps=args.max_steps,
        per_device_train_batch_size=args.per_device_train_batch_size,
        gradient_accumulation_steps=args.gradient_accumulation_steps,
        learning_rate=args.learning_rate,
        warmup_ratio=args.warmup_ratio,
        lr_scheduler_type=args.lr_scheduler_type,
        bf16=True,
        tf32=True,
        # Qwen3-VL generation needs KV cache. With Transformers 4.57.1,
        # gradient checkpointing disables that cache and the second decode
        # token receives a length-1 input_ids with a full attention mask.
        gradient_checkpointing=False,
        max_prompt_length=args.max_prompt_length,
        max_completion_length=args.max_completion_length,
        num_generations=args.num_generations,
        temperature=args.temperature,
        top_p=args.top_p,
        beta=args.beta,
        loss_type=args.loss_type,
        scale_rewards=args.scale_rewards,
        num_iterations=args.num_iterations,
        epsilon=args.epsilon,
        epsilon_high=args.epsilon_high,
        delta=args.delta,
        # The required structured answer is often longer than the smoke-test
        # completion budget. Masking every truncated completion would produce
        # a valid-looking run with exactly zero gradients.
        mask_truncated_completions=args.mask_truncated_completions,
        reward_weights=reward_weights,
        use_vllm=False,
        logging_steps=1,
        logging_first_step=True,
        save_strategy="steps" if args.save_steps > 0 else "no",
        save_steps=args.save_steps if args.save_steps > 0 else 500,
        save_total_limit=args.save_total_limit,
        report_to=args.report_to,
        run_name=args.wandb_run_name,
        log_completions=args.log_completions,
        num_completions_to_print=4 if args.log_completions else None,
        wandb_log_unique_prompts=args.log_completions,
        remove_unused_columns=False,
        dataloader_num_workers=0,
        ddp_find_unused_parameters=False,
        seed=args.seed,
        model_init_kwargs=model_init_kwargs,
    )
    trainer = GRPOTrainer(
        model=model_for_trainer,
        reward_funcs=reward_functions,
        args=config,
        train_dataset=dataset,
        processing_class=processor,
        peft_config=peft_config,
    )
    result = trainer.train()
    trainer.save_model(args.output_dir)
    if trainer.accelerator.is_main_process:
        metrics_path = Path(args.output_dir) / "smoke_metrics.json"
        metrics_path.write_text(json.dumps(result.metrics, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(result.metrics, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
