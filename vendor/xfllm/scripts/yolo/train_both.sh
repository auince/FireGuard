#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RUN_NAME="${RUN_NAME:-internal_yolo}" "$SCRIPT_DIR/train_internal.sh"
RUN_NAME="${RUN_NAME_EXTERNAL:-external_yolo}" "$SCRIPT_DIR/train_external.sh"
