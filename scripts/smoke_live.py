"""Real HTTP integration checks; no mocked model answers or replacement metrics."""
import json,base64,time,requests,argparse
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];base='http://127.0.0.1:8082'
p=argparse.ArgumentParser();p.add_argument('kind',choices=['inspection','retrieval','annotation']);a=p.parse_args()
source=ROOT/'data/training/validation.jsonl';row=json.loads(source.read_text().splitlines()[0]);image='data:image/jpeg;base64,'+base64.b64encode(Path(row['images'][0]).read_bytes()).decode()
route={'inspection':'inspect','retrieval':'retrieve','annotation':'annotations'}[a.kind]
payload={'image':image,'query':'消火栓被遮挡，单位应当履行哪些消防管理责任？','use_model':True,'mode':'hybrid'} if a.kind!='annotation' else {'image':image,'mode':'model_first'}
r=requests.post(base+'/api/'+route,json=payload,timeout=15);r.raise_for_status();job=r.json()['id'];print('job',job,flush=True)
for _ in range(240):
 time.sleep(3);r=requests.get(base+'/api/jobs/'+job,timeout=15);r.raise_for_status();value=r.json()
 if value['payload']['status'] in ['complete','failed','awaiting_review']:
  out=ROOT/'runtime/validation';out.mkdir(exist_ok=True);(out/(a.kind+'.json')).write_text(json.dumps(value,ensure_ascii=False,indent=2));print(value['payload']['status'],value['payload'].get('error',''),flush=True)
  if value['payload']['status']=='failed':raise SystemExit(1)
  break
else:raise TimeoutError('integration test did not complete within 12 minutes')
