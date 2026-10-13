"""Actual model/API smoke for each facility plus human-finalization transport checks."""
import json,base64,time,uuid
from pathlib import Path
import requests
from xfagent.v2.config import ROOT

out=ROOT/'reports/v2/live';out.mkdir(parents=True,exist_ok=True)
account=next(x for x in json.loads((ROOT/'runtime/v2/credentials.json').read_text()) if x['username']=='admin')
base='http://127.0.0.1:8080';response=requests.post(base+'/api/auth/login',json=account);response.raise_for_status()
headers={'Authorization':'Bearer '+response.json()['access_token']}
cases=[json.loads(l) for l in (ROOT/'benchmarks/inspection_scenarios/v2/cases.jsonl').read_text().splitlines()]
chosen=[]
for facility in ['indoor_hydrant','outdoor_hydrant','fire_extinguisher']:
 chosen.append(next(c for c in cases if c['facility']==facility and 'image_path' in c and c['split']=='dev'))
results=[]
for c in chosen:
 req=c['input'].copy();req['image']='data:image/jpeg;base64,'+base64.b64encode(Path(c['image_path']).read_bytes()).decode()
 req['query']='请观察这张'+{'indoor_hydrant':'室内消火栓','outdoor_hydrant':'室外消火栓','fire_extinguisher':'灭火器'}[c['facility']]+'照片，列出能确认的现象及不能确认的项目，检索相关消防条款作为人工核查参考。'
 req['session_id']='acceptance-'+uuid.uuid4().hex
 t=time.monotonic();res=requests.post(base+'/api/inspect',json=req,headers=headers);res.raise_for_status();identifier=res.json()['id']
 print('submitted',c['facility'],identifier,flush=True)
 deadline=time.monotonic()+480
 while time.monotonic()<deadline:
  j=requests.get(base+'/api/jobs/'+identifier,headers=headers).json()
  if j['status'] not in ['queued','running']:break
  time.sleep(3)
 row={'case_id':c['id'],'facility':c['facility'],'job_id':identifier,'elapsed':time.monotonic()-t,'job':j,
      'professional_review':'pending','kind':'live_model_engineering_acceptance'}
 if j['status']=='awaiting_review':
  # Deliberately review transport using only observations/information requests; no invented expert legal approval.
  claims=[x for x in j['result']['report']['conclusions'] if x['kind']!='legal_assessment']
  if not claims:claims=[{'claim_id':'human-review-pending','text':'工程验收已记录本次图像观察；法规适用及业务判断等待专业复核。',
    'observation_ids':[],'evidence_ids':[],'applicability':'unknown','sufficiency':'insufficient','missing_fields':[], 'kind':'information_request'}]
  review=requests.post(base+'/api/reports/'+identifier+'/review',headers=headers,json={'expected_revision':j['revision'],
    'action':'approve','comment':'自动化工程验收：仅确认工作流与待核查事项，非消防专业验收。','conclusions':claims})
  row['review_http_status']=review.status_code
  for _ in range(20):
   final=requests.get(base+'/api/jobs/'+identifier,headers=headers).json()
   if final['status'] not in ['queued','running']:break
   time.sleep(2)
  row['final_status']=final['status'];row['final_report_status']=final.get('result',{}).get('report',{}).get('status')
 results.append(row);(out/'results.json').write_text(json.dumps(results,ensure_ascii=False,indent=2))
 print(c['facility'],j['status'],'calls',j.get('result',{}).get('calls'),'seconds',round(row['elapsed'],1),'final',row.get('final_status'),flush=True)
