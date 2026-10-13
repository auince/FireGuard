#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run YOLO detection and emit JSON for XFDemo backend.")
    parser.add_argument("--weights", required=True)
    parser.add_argument("--image", required=True)
    parser.add_argument("--conf", type=float, default=0.25)
    parser.add_argument("--imgsz", type=int, default=640)
    parser.add_argument("--device", default="0")
    parser.add_argument("--max-det", type=int, default=50)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    weights = Path(args.weights)
    image = Path(args.image)
    if not weights.exists():
        raise FileNotFoundError(f"weights not found: {weights}")
    if not image.exists():
        raise FileNotFoundError(f"image not found: {image}")

    from ultralytics import YOLO

    model = YOLO(str(weights))
    results = model.predict(
        source=str(image),
        conf=args.conf,
        imgsz=args.imgsz,
        device=args.device,
        max_det=args.max_det,
        verbose=False,
    )
    result = results[0]
    names = result.names or getattr(model, "names", {}) or {}
    height, width = result.orig_shape[:2]
    detections = []
    boxes = result.boxes
    if boxes is not None:
        xyxy = boxes.xyxy.cpu().tolist()
        confs = boxes.conf.cpu().tolist()
        classes = boxes.cls.cpu().tolist()
        for coords, conf, cls_id in zip(xyxy, confs, classes):
            class_id = int(cls_id)
            x1, y1, x2, y2 = [float(v) for v in coords]
            detections.append({
                "classId": class_id,
                "className": str(names.get(class_id, class_id)),
                "confidence": float(conf),
                "bbox": [x1, y1, x2, y2],
                "bboxNorm": [x1 / width, y1 / height, x2 / width, y2 / height] if width and height else [],
            })
    payload = {
        "image": str(image),
        "weights": str(weights),
        "imgsz": args.imgsz,
        "confThreshold": args.conf,
        "device": str(args.device),
        "imageWidth": int(width),
        "imageHeight": int(height),
        "detections": detections,
    }
    print("YOLO_JSON_RESULT=" + json.dumps(payload, ensure_ascii=False, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
