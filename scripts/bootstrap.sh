#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
APP_PYTHON=${XF_APP_PYTHON:-/opt/conda/bin/python}
MODEL_PYTHON=${XF_TORCH_PYTHON:-/opt/conda/envs/model/bin/python}
if [ ! -x .venv/bin/python ]; then "$APP_PYTHON" -m venv .venv; fi
.venv/bin/pip install -e '.[test]'
if [ ! -x .venv-model/bin/python ]; then "$MODEL_PYTHON" -m venv --system-site-packages .venv-model; fi
.venv-model/bin/pip install 'transformers==5.3.0' 'peft==0.18.1' 'trl==1.14.1' accelerate datasets sentence-transformers diffusers ultralytics onnx onnxslim onnxruntime
.venv/bin/python scripts/inventory.py
.venv/bin/pip freeze > requirements-app.lock
.venv-model/bin/pip freeze > requirements-model.lock
