#!/usr/bin/env python3
from __future__ import annotations

import argparse
import collections
import copy
import json
import math
import random
import re
from pathlib import Path
from typing import Any


SECTION_RE = r"\n\s*(?:检查范围|结论|检查过程|判定依据|隐患标签)\s*[:：]"


def message_text(row: dict[str, Any], role: str) -> str:
    chunks: list[str] = []
    for message in row.get("messages", []):
        if message.get("role") != role:
            continue
        content = message.get("content", "")
        if isinstance(content, str):
            chunks.append(content)
        elif isinstance(content, list):
            for item in content:
                if isinstance(item, dict) and item.get("type") == "text":
                    chunks.append(str(item.get("text", "")))
    return "\n".join(chunks)


def field(text: str, name: str) -> str | None:
    match = re.search(rf"{re.escape(name)}\s*[:：]\s*(.*?)(?={SECTION_RE}|\Z)", text, re.S)
    return match.group(1).strip() if match else None


def labels_from_answer(text: str) -> list[str]:
    raw = field(text, "隐患标签")
    if raw is None:
        return []
    raw = raw.strip().strip("。.;；,，")
    if raw in {"", "无", "合规", "正常", "无隐患"}:
        return []
    labels = []
    for part in re.split(r"[；;、,，\n]+", raw):
        label = part.strip().strip("。.;；,，")
        if label and label not in {"无", "合规", "正常", "无隐患"}:
            labels.append(label)
    return labels


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as handle:
        for idx, line in enumerate(handle, 1):
            if not line.strip():
                continue
            row = json.loads(line)
            row["_source_line"] = idx
            answer = message_text(row, "assistant")
            labels = labels_from_answer(answer)
            row["_parsed_labels"] = labels
            row["_parsed_verdict"] = field(answer, "结论")
            rows.append(row)
    return rows


def weighted_without_replacement(
    rows: list[dict[str, Any]], weights: list[float], n: int, rng: random.Random
) -> list[dict[str, Any]]:
    if n >= len(rows):
        return list(rows)
    ranked = sorted(
        zip(rows, weights),
        key=lambda item: rng.random() ** (1.0 / max(item[1], 1e-8)),
        reverse=True,
    )
    return [row for row, _ in ranked[:n]]


def defect_weights(rows: list[dict[str, Any]]) -> list[float]:
    support: collections.Counter[str] = collections.Counter()
    for row in rows:
        support.update(row["_parsed_labels"])
    max_support = max(support.values(), default=1)
    weights: list[float] = []
    for row in rows:
        labels = row["_parsed_labels"]
        if not labels:
            weights.append(1.0)
            continue
        label_weights = [math.sqrt(max_support / max(support[label], 1)) for label in labels]
        weights.append(min(5.0, sum(label_weights) / len(label_weights)))
    return weights


def clean_for_write(row: dict[str, Any], *, split: str, sampled_from: int, oversampled: bool) -> dict[str, Any]:
    out = copy.deepcopy(row)
    source_line = out.pop("_source_line")
    labels = out.pop("_parsed_labels")
    verdict = out.pop("_parsed_verdict")
    meta = out.setdefault("meta", {})
    meta["sft_split_version"] = "20260714_hydrant_sft_balanced_v1"
    meta["sft_split"] = split
    meta["sft_sampled_from_source_line"] = sampled_from
    meta["sft_oversampled"] = oversampled
    meta["sft_parsed_labels"] = labels
    meta["sft_parsed_verdict"] = verdict
    out["id"] = f"{out.get('id', 'row')}__{split}_{source_line:05d}_{sampled_from:05d}"
    return out


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--train-size", type=int, default=1400)
    parser.add_argument("--val-size", type=int, default=200)
    parser.add_argument("--train-compliant-fraction", type=float, default=0.35)
    parser.add_argument("--val-compliant-fraction", type=float, default=0.20)
    parser.add_argument("--seed", type=int, default=20260714)
    args = parser.parse_args()

    rng = random.Random(args.seed)
    rows = read_jsonl(args.input)
    compliant = [row for row in rows if not row["_parsed_labels"]]
    defects = [row for row in rows if row["_parsed_labels"]]
    rng.shuffle(compliant)
    rng.shuffle(defects)

    val_compliant_n = min(len(compliant), round(args.val_size * args.val_compliant_fraction))
    val_defect_n = min(len(defects), args.val_size - val_compliant_n)
    val_compliant = compliant[:val_compliant_n]
    remain_compliant = compliant[val_compliant_n:]

    defect_w = defect_weights(defects)
    val_defect = weighted_without_replacement(defects, defect_w, val_defect_n, rng)
    val_ids = {id(row) for row in val_compliant + val_defect}
    remain_defects = [row for row in defects if id(row) not in val_ids]

    train_compliant_n = round(args.train_size * args.train_compliant_fraction)
    train_defect_n = args.train_size - train_compliant_n
    if train_compliant_n <= len(remain_compliant):
        train_compliant = rng.sample(remain_compliant, train_compliant_n)
    else:
        train_compliant = list(remain_compliant)
        train_compliant += rng.choices(remain_compliant, k=train_compliant_n - len(remain_compliant))

    remain_defect_w = defect_weights(remain_defects)
    train_defects = weighted_without_replacement(remain_defects, remain_defect_w, min(train_defect_n, len(remain_defects)), rng)
    if len(train_defects) < train_defect_n:
        train_defects += rng.choices(remain_defects, weights=remain_defect_w, k=train_defect_n - len(train_defects))

    train_rows_raw = train_compliant + train_defects
    val_rows_raw = val_compliant + val_defect
    rng.shuffle(train_rows_raw)
    rng.shuffle(val_rows_raw)

    seen_train: collections.Counter[int] = collections.Counter(id(row) for row in train_rows_raw)
    train_rows = [
        clean_for_write(
            row,
            split="train",
            sampled_from=row["_source_line"],
            oversampled=seen_train[id(row)] > 1,
        )
        for row in train_rows_raw
    ]
    val_rows = [
        clean_for_write(row, split="val", sampled_from=row["_source_line"], oversampled=False)
        for row in val_rows_raw
    ]

    write_jsonl(args.output_dir / "train.jsonl", train_rows)
    write_jsonl(args.output_dir / "val.jsonl", val_rows)

    def summarize(name: str, split_rows: list[dict[str, Any]]) -> dict[str, Any]:
        labels = [label for row in split_rows for label in row["meta"]["sft_parsed_labels"]]
        card = collections.Counter(len(row["meta"]["sft_parsed_labels"]) for row in split_rows)
        return {
            "name": name,
            "rows": len(split_rows),
            "compliant": card.get(0, 0),
            "defect": len(split_rows) - card.get(0, 0),
            "label_cardinality": dict(sorted(card.items())),
            "labels": dict(collections.Counter(labels).most_common()),
            "oversampled_rows": sum(1 for row in split_rows if row["meta"]["sft_oversampled"]),
        }

    summary = {
        "source": str(args.input),
        "output_dir": str(args.output_dir),
        "seed": args.seed,
        "source_rows": len(rows),
        "source_compliant": len(compliant),
        "source_defect": len(defects),
        "train": summarize("train", train_rows),
        "val": summarize("val", val_rows),
    }
    (args.output_dir / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
