#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source /opt/conda/etc/profile.d/conda.sh
conda activate detector

DATASET=20260723_yolo_fire_extinguisher_v2
exec python "$SCRIPT_DIR/train_yolo.py" \
  --data "/opt/datasets/fire-inspection/training_data/$DATASET/data.yaml" \
  --project "/opt/xfagent/artifacts/yolo/$DATASET/train" \
  --weights-dir "/opt/xfagent/artifacts/yolo/$DATASET/weights" \
  --name "${RUN_NAME:-fire_extinguisher_yolo11n}" \
  "$@"
