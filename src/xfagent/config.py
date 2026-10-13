from pathlib import Path
import json
import os
import uuid

ROOT = Path(os.environ.get("XFAGENT_ROOT", Path(__file__).resolve().parents[2])).resolve()

def directory(name):
    p = ROOT / name
    p.mkdir(parents=True, exist_ok=True)
    return p

def read_json(path, default=None):
    p = Path(path)
    return json.loads(p.read_text()) if p.exists() else default

def write_json(path, value):
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(p.suffix + "."+uuid.uuid4().hex+".tmp")
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2))
    tmp.replace(p)

def settings():
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env", override=False)
    return {
        "base_url": os.getenv("XF_MODEL_URL", "http://127.0.0.1:8000/v1"),
        "model": os.getenv("XF_MODEL_NAME", "xf-qwen3.5-9b"),
        "api_key": os.getenv("XF_MODEL_KEY", "local"),
        "embedding_model": os.getenv("XF_EMBEDDING_MODEL", "/opt/models/bge-m3"),
        "embedding_device": os.getenv("XF_EMBEDDING_DEVICE", "cpu"),
        "clip_model": os.getenv("XF_CLIP_MODEL", "/opt/models/clip-vit-large-patch14"),
    }
