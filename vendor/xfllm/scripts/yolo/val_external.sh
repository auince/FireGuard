#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source /opt/conda/etc/profile.d/conda.sh
conda activate detector

exec python "$SCRIPT_DIR/train_yolo.py" \
  --mode val \
  --data /opt/datasets/fire-inspection/training_data/v5_YOLO/external/data.yaml \
  --model "${WEIGHT:-/opt/xfagent/artifacts/yolo/v5_YOLO/external/weights/best.pt}" \
  --project /opt/xfagent/artifacts/yolo/v5_YOLO/external/val \
  --name "${RUN_NAME:-external_yolo_val_best}" \
  --exist-ok \
  "$@"
