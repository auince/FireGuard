"""Document's per-component comparison, only against explicitly annotated attributes.
Input JSONL: images, attributes mapping; unknown is NOT equivalent to normal.
"""
import argparse,json,base64,sys,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'src'))
from xfagent.data import rows
from xfagent.models import complete,json_response,health
ATTRIBUTES=['Class','door_status','bolt_body','Handwheel','Joint','bolt_dir','belt_body','water_gun','Result']
p=argparse.ArgumentParser();p.add_argument('data');p.add_argument('--output',required=True);a=p.parse_args();records=[];scores={k:[0,0] for k in ATTRIBUTES}
for row in rows(a.data):
 gold=row.get('attributes')
 if not gold:raise ValueError('Missing expert component annotations; do not infer normal from absence of a hazard label')
 image='data:image/jpeg;base64,'+base64.b64encode(Path(row['images'][0]).read_bytes()).decode()
 prediction=json_response(complete('检查图片中的消防设施属性，以JSON返回以下字段（看不清写unknown）：'+','.join(ATTRIBUTES)+'. Class用internal_components或appearance；Result用合规、不合规或无法判断；其他字段用normal、abnormal、unknown。',image=image))
 for key,value in gold.items():
  if key in scores:scores[key][1]+=1;scores[key][0]+=prediction.get(key)==value
 records.append({'id':row.get('id'),'gold':gold,'prediction':prediction})
Path(a.output).write_text(json.dumps({'model':health(),'data':a.data,'results':records,'attributes':{k:{'n':v[1],'accuracy':v[0]/v[1] if v[1] else None} for k,v in scores.items()}},ensure_ascii=False,indent=2))
