#!/usr/bin/env bash
set -euo pipefail

STAGE_DIR="${1:-${DEBUG_STAGE_DIR:-/tmp/qwen3vl_stage}}"

if [[ ! -d "$STAGE_DIR" ]]; then
  echo "stage dir does not exist: $STAGE_DIR" >&2
  exit 1
fi

python - "$STAGE_DIR" <<'PY'
import json
import pathlib
import sys

stage_dir = pathlib.Path(sys.argv[1])
files = sorted(stage_dir.glob("rank*_local*.json"))
if not files:
    print(f"no stage files in {stage_dir}")
    raise SystemExit(0)

for path in files:
    data = json.loads(path.read_text(encoding="utf-8"))
    cuda = data.get("cuda") or {}
    print(
        f"{path.name}: stage={data.get('stage')} "
        f"rank={data.get('rank')} local_rank={data.get('local_rank')} "
        f"pid={data.get('pid')} cuda_device={cuda.get('current_device')} "
        f"name={cuda.get('device_name')} allocated={cuda.get('memory_allocated')} "
        f"reserved={cuda.get('memory_reserved')}"
    )
PY
