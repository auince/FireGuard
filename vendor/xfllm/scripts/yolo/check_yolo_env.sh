#!/usr/bin/env bash
set -euo pipefail
source /opt/conda/etc/profile.d/conda.sh
conda activate detector
python - <<'PY'
import torch, ultralytics
print('torch', torch.__version__)
print('cuda_available', torch.cuda.is_available())
print('gpu_count', torch.cuda.device_count())
for i in range(torch.cuda.device_count()):
    print('gpu%d' % i, torch.cuda.get_device_name(i))
print('ultralytics', ultralytics.__version__)
PY
yolo version
