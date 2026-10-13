"""Model-authored indexing aids, separated from unmodified legal source text."""
import json,sys,argparse,base64
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'src'))
from xfagent.config import read_json,write_json
from xfagent.ingest import normalize_with_model
from xfagent.models import complete,settings
from xfagent.data import rows,text_of

def main():
 p=argparse.ArgumentParser();p.add_argument('kind',choices=['legal','cases']);p.add_argument('--limit',type=int,default=8);p.add_argument('--source',default=str(ROOT/'data/training/train.jsonl'));p.add_argument('--output');a=p.parse_args()
 if a.kind=='legal':
  target=ROOT/'data/legal/enrichment.json';result=read_json(target,{})
  docs=[d for d in read_json(ROOT/'data/legal/manifest.json',[]) if d.get('status')=='source_verified' and d.get('kind') not in ['announcement','catalog']]
  for d in docs[:a.limit]:
   if d['id'] in result:continue
   result[d['id']]={'suggested':normalize_with_model((ROOT/d['markdown_path']).read_text()),'source_sha256':d['sha256'],'model':settings()['model'],'authoritative':False};write_json(target,result)
  print({'enriched':len(result)})
 else:
  target=Path(a.output or ROOT/'data/cases/model_descriptions.jsonl');target.parent.mkdir(parents=True,exist_ok=True)
  with target.open('w') as f:
   for i,row in enumerate(rows(a.source)):
    if i>=a.limit:break
    image='data:image/jpeg;base64,'+base64.b64encode(Path(row['images'][0]).read_bytes()).decode()
    text=complete('结合图片和已有专业标注，描述设施外观、可见部件、隐患及不可判断处。避免将看不见当成缺失。\n已有标注：'+text_of(row,'assistant'),image=image)
    record={**row,'messages':[{'role':'assistant','content':text}],'description_model':settings()['model'],'human_reviewed':False,'usage':'retrieval_description_only_not_training_label'}
    f.write(json.dumps(record,ensure_ascii=False)+'\n');f.flush()
  print({'output':str(target)})
if __name__=='__main__':main()
