#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source /opt/conda/etc/profile.d/conda.sh
conda activate detector

exec python "$SCRIPT_DIR/train_yolo.py" \
  --data /opt/datasets/fire-inspection/training_data/v5_YOLO/internal/data.yaml \
  --project /opt/xfagent/artifacts/yolo/v5_YOLO/internal/train \
  --weights-dir /opt/xfagent/artifacts/yolo/v5_YOLO/internal/weights \
  --name "${RUN_NAME:-internal_yolo}" \
  "$@"
