import os
from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo

ROOT = Path(os.getenv('XFAGENT_ROOT', str(Path(__file__).resolve().parents[3])))
MONGO = os.getenv('XF_V2_MONGO', 'mongodb://127.0.0.1:27017/?replicaSet=xfv2&directConnection=true')
DB = os.getenv('XF_V2_DB', 'xfagent_v2')
REDIS = os.getenv('XF_V2_REDIS', 'redis://127.0.0.1:6379/0')
MILVUS = os.getenv('XF_V2_MILVUS', 'http://127.0.0.1:19530')
MODEL_URL = os.getenv('XF_MODEL_URL', 'http://127.0.0.1:8000/v1')
MODEL = os.getenv('XF_MODEL_NAME', 'xf-qwen3.5-9b')
EMBED_URL = os.getenv('XF_EMBEDDING_URL', 'http://127.0.0.1:8001/embed')
RERANK_URL = os.getenv('XF_RERANK_URL', 'http://127.0.0.1:8005/rerank')
FACILITIES = {'indoor_hydrant':'室内消火栓', 'outdoor_hydrant':'室外消火栓', 'fire_extinguisher':'灭火器'}

def today():
    return datetime.now(ZoneInfo('Asia/Shanghai')).date().isoformat()

def now():
    return datetime.now(ZoneInfo('UTC'))
