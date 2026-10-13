#!/usr/bin/env python3
"""Build auditable hard-negative preference pairs for hydrant VLM training.

The frozen evaluation set must never be passed to this script.  Pairs are split
by image SHA1 so an image cannot occur in both preference train and validation.
"""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
import random
from pathlib import Path
from typing import Any


INTERNAL_LABELS = [
    "室内消火栓手轮缺失",
    "室内消火栓栓口方向错误",
    "室内消火栓无消防水带",
    "室内消火栓无消防水枪",
    "室内消火栓消防接口缺失",
    "消防软管卷盘供水管道折弯严重",
    "室内消火栓无箱体",
    "室内消火栓箱锈蚀",
    "室内消火栓箱门缺失",
]
APPEARANCE_LABELS = [
    "室内消火栓箱明显部位未采用耐久性文字或图形标注操作说明",
    "室内消火栓箱门上未标注“消火栓”和英文“FIRE HYDRANT”字样",
    "室内消火栓箱体无铭牌",
    "室内消火栓箱门标识模糊",
    "室内消火栓箱体铭牌模糊",
    "室内消火栓箱门为玻璃门",
    "室内消火栓箱体或箱门被物品遮挡",
]
LABELS_BY_SCOPE = {
    "internal_components": INTERNAL_LABELS,
    "appearance": APPEARANCE_LABELS,
}
SCOPE_ZH = {"internal_components": "内部组件", "appearance": "箱体外观"}

COMPACT_PROMPT = """你是消防设施巡检助手。只根据图片中清晰可见的内容检查室内消火栓，不得把遮挡、反光、模糊或画面外的项目推测为异常。

检查范围只能选：内部组件、箱体外观、无法确定。
内部组件标签只能选：""" + "；".join(INTERNAL_LABELS) + """。
箱体外观标签只能选：""" + "；".join(APPEARANCE_LABELS) + """。

有隐患标签则结论为“不合规”，无隐患标签则为“合规”；证据不足时写“无法判断”。不要输出思维链。请严格按以下顺序输出：
检查范围：...
结论：...
隐患标签：多个用“；”分隔，无则写“无”
可见证据：用 1 至 3 句说明可见依据和看不清的项目。"""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--val-size", type=int, default=193)
    parser.add_argument("--seed", type=int, default=20260722)
    parser.add_argument("--compact-prompt", action=argparse.BooleanOptionalAction, default=True)
    return parser.parse_args()


def message_text(row: dict[str, Any], role: str) -> str:
    for message in row.get("messages", []):
        if message.get("role") != role:
            continue
        content = message.get("content", "")
        if isinstance(content, str):
            return content
        return "\n".join(
            str(item.get("text", ""))
            for item in content
            if isinstance(item, dict) and item.get("type") == "text"
        )
    return ""


def normalize_scope(value: str) -> str:
    if value in {"appearance", "箱体外观"}:
        return "appearance"
    if value in {"internal", "internal_components", "内部组件"}:
        return "internal_components"
    raise ValueError(f"unsupported scope: {value!r}")


def canonical_compact_answer(scope: str, labels: list[str]) -> str:
    label_text = "；".join(labels) if labels else "无"
    verdict = "不合规" if labels else "合规"
    evidence = (
        "图中可见证据与上述隐患标签一致；未清晰显示的项目不作异常推测。"
        if labels
        else "图中未见当前检查范围内的明确隐患；未清晰显示的项目不作异常推测。"
    )
    return (
        f"检查范围：{SCOPE_ZH[scope]}\n"
        f"结论：{verdict}\n"
        f"隐患标签：{label_text}\n"
        f"可见证据：{evidence}"
    )


def canonical_verbose_answer(scope: str, labels: list[str]) -> str:
    """Match the verbose schema used by the high-performing SFT policy.

    Chosen and rejected answers deliberately share the same structure and
    comparable length so DPO cannot solve the pair from formatting alone.
    """
    label_text = "；".join(labels) if labels else "无"
    verdict = "不合规" if labels else "合规"
    scope_reason = (
        "图片主要呈现箱内器材，检查证据集中在内部组件，因此按内部组件检查。"
        if scope == "internal_components"
        else "图片主要呈现箱体和箱门外观，检查证据集中在箱体外观，因此按箱体外观检查。"
    )
    abnormal = f"可见异常与标签“{label_text}”一致。" if labels else "未见明确异常项。"
    basis = (
        f"当前图片按{SCOPE_ZH[scope]}进行检查，可见异常与隐患标签“{label_text}”一致，因此判定为不合规。"
        if labels
        else f"当前图片按{SCOPE_ZH[scope]}进行检查，未见清晰可确认的隐患，因此判定为合规。"
    )
    return (
        f"检查范围：{SCOPE_ZH[scope]}\n\n"
        f"结论：{verdict}\n\n"
        "检查过程：\n"
        f"1. 画面判断：{scope_reason}\n"
        "2. 可见正常项：仅记录图中能清晰确认的内容。\n"
        f"3. 可见异常项：{abnormal}\n"
        "4. 无法判断项：遮挡、反光、模糊或画面外的项目不作异常推测。\n\n"
        f"判定依据：{basis}\n\n"
        f"隐患标签：{label_text}"
    )


def choose_other_label(scope: str, excluded: set[str], rng: random.Random) -> str:
    choices = [label for label in LABELS_BY_SCOPE[scope] if label not in excluded]
    if not choices:
        raise ValueError(f"no alternative label for {scope}")
    return rng.choice(choices)


def mutate_labels(scope: str, labels: list[str], rng: random.Random) -> tuple[list[str], str]:
    labels = list(dict.fromkeys(labels))
    if not labels:
        return [choose_other_label(scope, set(), rng)], "clean_false_positive"

    draw = rng.random()
    # Keep false-negative and clean false-positive pairs roughly balanced.
    # Otherwise the model can exploit answer length / label count instead of vision.
    if draw < 0.12:
        return [], "defect_false_negative"
    if len(labels) > 1 and draw < 0.40:
        rejected = labels.copy()
        rejected.pop(rng.randrange(len(rejected)))
        return rejected, "label_drop"
    if draw < 0.85:
        rejected = labels.copy()
        index = rng.randrange(len(rejected))
        rejected[index] = choose_other_label(scope, set(labels), rng)
        return list(dict.fromkeys(rejected)), "same_scope_label_swap"
    return labels + [choose_other_label(scope, set(labels), rng)], "label_add"


def make_pair(source: dict[str, Any], rng: random.Random, compact_prompt: bool) -> dict[str, Any]:
    meta = source.get("meta") or {}
    scope = normalize_scope(str(meta.get("task") or ""))
    labels = list(dict.fromkeys(meta.get("defect_labels") or []))
    invalid = [label for label in labels if label not in LABELS_BY_SCOPE[scope]]
    if invalid:
        raise ValueError(f"labels outside {scope} whitelist: {invalid}")
    rejected_labels, negative_type = mutate_labels(scope, labels, rng)
    images = source.get("images") or []
    if len(images) != 1:
        raise ValueError(f"expected exactly one image, got {len(images)}")
    prompt_text = COMPACT_PROMPT if compact_prompt else message_text(source, "user")
    answer_builder = canonical_compact_answer if compact_prompt else canonical_verbose_answer
    image_path = images[0]
    image_sha1 = str(meta.get("image_sha1") or hashlib.sha1(image_path.encode()).hexdigest())
    return {
        "id": source.get("id"),
        "images": [image_path],
        "prompt": [
            {
                "role": "user",
                "content": [
                    {"type": "image"},
                    {"type": "text", "text": prompt_text},
                ],
            }
        ],
        "chosen": [{"role": "assistant", "content": [{"type": "text", "text": answer_builder(scope, labels)}]}],
        "rejected": [
            {"role": "assistant", "content": [{"type": "text", "text": answer_builder(scope, rejected_labels)}]}
        ],
        "meta": {
            "source_id": source.get("id"),
            "image_sha1": image_sha1,
            "scope": scope,
            "chosen_labels": labels,
            "rejected_labels": rejected_labels,
            "negative_type": negative_type,
            "frozen_eval_excluded_by_sha1": bool(meta.get("frozen_eval_excluded_by_sha1")),
            "preference_version": (
                "20260722_hydrant_preference_v1_compact"
                if compact_prompt
                else "20260722_hydrant_preference_v2_verbose"
            ),
        },
    }


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def split_key(row: dict[str, Any], seed: int) -> str:
    sha1 = row["meta"]["image_sha1"]
    return hashlib.sha256(f"{seed}:{sha1}".encode()).hexdigest()


def stratified_validation_split(
    pairs: list[dict[str, Any]], val_size: int, seed: int
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Cover rare gold labels and every negative type, then fill by stable hash."""
    ordered = sorted(pairs, key=lambda row: split_key(row, seed))
    label_support = Counter(label for row in ordered for label in row["meta"]["chosen_labels"])
    required_labels = sorted(label_support, key=lambda label: (label_support[label], label))
    required_negative_types = sorted({row["meta"]["negative_type"] for row in ordered})
    selected_ids: set[str] = set()

    def select_first(predicate) -> None:
        for row in ordered:
            sha1 = row["meta"]["image_sha1"]
            if sha1 not in selected_ids and predicate(row):
                selected_ids.add(sha1)
                return

    for label in required_labels:
        select_first(lambda row, wanted=label: wanted in row["meta"]["chosen_labels"])
    for negative_type in required_negative_types:
        select_first(lambda row, wanted=negative_type: row["meta"]["negative_type"] == wanted)
    # Both scopes must be present even in unusually small audit splits.
    for scope in sorted(LABELS_BY_SCOPE):
        select_first(lambda row, wanted=scope: row["meta"]["scope"] == wanted)

    if len(selected_ids) > val_size:
        raise ValueError(f"val-size={val_size} is too small for required coverage={len(selected_ids)}")
    for row in ordered:
        if len(selected_ids) >= val_size:
            break
        selected_ids.add(row["meta"]["image_sha1"])

    validation = [row for row in ordered if row["meta"]["image_sha1"] in selected_ids]
    train = [row for row in ordered if row["meta"]["image_sha1"] not in selected_ids]
    return train, validation


def summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    length_deltas = []
    for row in rows:
        chosen = row["chosen"][0]["content"][0]["text"]
        rejected = row["rejected"][0]["content"][0]["text"]
        length_deltas.append(len(chosen) - len(rejected))
    return {
        "rows": len(rows),
        "unique_images": len({row["meta"]["image_sha1"] for row in rows}),
        "scopes": dict(Counter(row["meta"]["scope"] for row in rows)),
        "negative_types": dict(Counter(row["meta"]["negative_type"] for row in rows)),
        "chosen_labels": dict(Counter(label for row in rows for label in row["meta"]["chosen_labels"])),
        "answer_char_length_delta": {
            "mean": round(sum(length_deltas) / max(len(length_deltas), 1), 3),
            "min": min(length_deltas, default=0),
            "max": max(length_deltas, default=0),
        },
    }


if __name__ == "__main__":
    args = parse_args()
    rng = random.Random(args.seed)
    source_rows: list[dict[str, Any]] = []
    with open(args.input, encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                source_rows.append(json.loads(line))

    pairs = [make_pair(row, rng, args.compact_prompt) for row in source_rows]
    sha1s = [row["meta"]["image_sha1"] for row in pairs]
    if len(sha1s) != len(set(sha1s)):
        raise ValueError("input contains duplicate image_sha1; deduplicate before preference splitting")
    if not all(row["meta"]["frozen_eval_excluded_by_sha1"] for row in pairs):
        raise ValueError("at least one row lacks frozen_eval_excluded_by_sha1=true")
    if not 0 < args.val_size < len(pairs):
        raise ValueError("val-size must be between 1 and number of pairs - 1")

    train, validation = stratified_validation_split(pairs, args.val_size, args.seed)
    assert {r["meta"]["image_sha1"] for r in train}.isdisjoint(
        {r["meta"]["image_sha1"] for r in validation}
    )

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    write_jsonl(output_dir / "train.jsonl", train)
    write_jsonl(output_dir / "validation.jsonl", validation)
    audit = {
        "input": args.input,
        "seed": args.seed,
        "split_unit": "image_sha1",
        "split_strategy": "rare-label-and-negative-type coverage, then deterministic SHA256 fill",
        "frozen_eval_policy": "source rows must declare frozen_eval_excluded_by_sha1=true",
        "prompt": "compact" if args.compact_prompt else "source",
        "train": summarize(train),
        "validation": summarize(validation),
        "train_validation_image_overlap": 0,
    }
    (output_dir / "audit.json").write_text(
        json.dumps(audit, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(audit, ensure_ascii=False, indent=2))
