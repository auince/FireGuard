#!/usr/bin/env python3
from __future__ import annotations

import argparse
from datetime import datetime
import json
import os
from pathlib import Path
import shutil
from typing import Any


DEFAULT_MODEL = "/opt/datasets/fire-inspection/models/yolo/yolo11n.pt"


def env_int(name: str, default: int) -> int:
    return int(os.environ.get(name, default))


def env_value(name: str, default: str) -> str:
    return os.environ.get(name, default)


def env_bool(name: str, default: bool = False) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def parse_batch(value: str) -> int | float | str:
    try:
        return int(value)
    except ValueError:
        try:
            return float(value)
        except ValueError:
            return value


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Train or validate an Ultralytics YOLO detector through the Python API."
    )
    parser.add_argument("--mode", choices=("train", "val"), default="train")
    parser.add_argument("--data", type=Path, required=True)
    parser.add_argument("--model", type=Path, default=Path(env_value("MODEL", DEFAULT_MODEL)))
    parser.add_argument("--project", type=Path, required=True)
    parser.add_argument("--name", default=env_value("RUN_NAME", "train_yolo"))
    parser.add_argument("--weights-dir", type=Path)
    parser.add_argument("--epochs", type=int, default=env_int("EPOCHS", 100))
    parser.add_argument("--imgsz", type=int, default=env_int("IMGSZ", 640))
    parser.add_argument("--batch", default=env_value("BATCH", "16"))
    parser.add_argument("--device", default=env_value("DEVICE", "0"))
    parser.add_argument("--workers", type=int, default=env_int("WORKERS", 8))
    parser.add_argument("--patience", type=int, default=env_int("PATIENCE", 30))
    parser.add_argument("--seed", type=int, default=env_int("SEED", 20260723))
    parser.add_argument("--cache", action="store_true", default=env_bool("CACHE"))
    parser.add_argument("--resume", action="store_true", default=env_bool("RESUME"))
    parser.add_argument("--exist-ok", action="store_true", default=env_bool("EXIST_OK"))
    parser.add_argument("--dry-run", action="store_true", default=env_bool("DRY_RUN"))
    return parser.parse_args()


def validate_dataset(data_path: Path) -> None:
    import yaml

    if not data_path.is_file():
        raise FileNotFoundError(f"Dataset YAML not found: {data_path}")
    data = yaml.safe_load(data_path.read_text(encoding="utf-8"))
    root = Path(data.get("path", data_path.parent))
    if not root.is_absolute():
        root = (data_path.parent / root).resolve()
    required_splits = ("train", "val")
    for split in required_splits:
        relative = data.get(split)
        if not relative:
            raise ValueError(f"Missing '{split}' in {data_path}")
        split_path = Path(relative)
        if not split_path.is_absolute():
            split_path = root / split_path
        if not split_path.exists():
            raise FileNotFoundError(f"Dataset split not found: {split_path}")
    names = data.get("names")
    if not names:
        raise ValueError(f"Missing class names in {data_path}")


def serializable_config(args: argparse.Namespace) -> dict[str, Any]:
    return {
        key: str(value) if isinstance(value, Path) else value
        for key, value in vars(args).items()
    }


def main() -> None:
    args = parse_args()
    args.data = args.data.resolve()
    args.model = args.model.resolve()
    args.project = args.project.resolve()
    if args.weights_dir:
        args.weights_dir = args.weights_dir.resolve()

    validate_dataset(args.data)
    if not args.model.is_file():
        raise FileNotFoundError(f"Model weights not found: {args.model}")
    args.project.mkdir(parents=True, exist_ok=True)
    config = serializable_config(args)
    print(json.dumps(config, ensure_ascii=False, indent=2))
    if args.dry_run:
        print("Dry run complete; training was not started.")
        return

    from ultralytics import YOLO

    model = YOLO(str(args.model))
    common = {
        "data": str(args.data),
        "imgsz": args.imgsz,
        "batch": parse_batch(args.batch),
        "device": args.device,
        "workers": args.workers,
        "project": str(args.project),
        "name": args.name,
        "exist_ok": args.exist_ok,
    }
    if args.mode == "train":
        model.train(
            **common,
            epochs=args.epochs,
            patience=args.patience,
            cache=args.cache,
            seed=args.seed,
            deterministic=True,
            resume=args.resume,
        )
        save_dir = Path(model.trainer.save_dir)
        archive_weights(save_dir, args.weights_dir, config)
    else:
        model.val(**common, plots=True)


def archive_weights(
    save_dir: Path, weights_dir: Path | None, config: dict[str, Any]
) -> None:
    if weights_dir is None:
        return
    weights_dir.mkdir(parents=True, exist_ok=True)
    source_dir = save_dir / "weights"
    copied = []
    for name in ("best.pt", "last.pt"):
        source = source_dir / name
        if source.is_file():
            target = weights_dir / name
            shutil.copy2(source, target)
            copied.append(str(target))
    record = {
        "completed_at": datetime.now().astimezone().isoformat(),
        "run_dir": str(save_dir),
        "copied_weights": copied,
        "config": config,
    }
    (weights_dir / "latest_run.json").write_text(
        json.dumps(record, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
