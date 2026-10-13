import json,subprocess,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
rows=[json.loads(x) for x in (ROOT/'data/training/validation.jsonl').read_text().splitlines()]
row=next(r for r in rows if '检查范围：内部组件' in json.dumps(r,ensure_ascii=False));source=row['images'][0]
command=[str(ROOT/'.venv-model/bin/python'),str(ROOT/'scripts/edge.py'),'infer','--weights','/opt/xfagent/artifacts/yolo/fire_hydrant_v3_20260707/fire_hydrant_20260715.pt','--source',source,'--output',str(ROOT/'runtime/edge-smoke'),'--device','cpu']
subprocess.run(command,check=True)
print('edge inference and crops saved')
