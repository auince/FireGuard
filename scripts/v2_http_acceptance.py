"""Live authenticated API constraints, durable checkpoint resume, and idempotency."""
import json,time,uuid,subprocess
from pathlib import Path
import requests
from xfagent.v2.config import ROOT
accounts={x['username']:x for x in json.loads((ROOT/'runtime/v2/credentials.json').read_text())};base='http://127.0.0.1:8080';headers={};results={}
for name in ['admin','reviewer','inspector']:
 r=requests.post(base+'/api/auth/login',json=accounts[name]);r.raise_for_status();headers[name]={'Authorization':'Bearer '+r.json()['access_token']}
results['unauthenticated_denied']=requests.get(base+'/api/jobs').status_code==401
fixture=requests.post(base+'/api/retrieve',headers=headers['admin'],json={'query':'工程验收专用：持久检查点恢复；不构成消防专业结论。',
 'facility':'indoor_hydrant','use_model':False,'retrieval_mode':'bm25','session_id':'http-fixture-'+uuid.uuid4().hex});fixture.raise_for_status()
fixture_id=fixture.json()['id']
for _ in range(45):
 old=requests.get(base+'/api/jobs/'+fixture_id,headers=headers['admin']).json()
 if old['status'] not in ['running','queued']:break
 time.sleep(1)
assert old['status']=='awaiting_review'
results['cross_owner_denied']=requests.get(base+'/api/jobs/'+old['id'],headers=headers['inspector']).status_code==403
results['inspector_publish_denied']=requests.post(base+'/api/policies/seed-1/publish',headers=headers['inspector'],json={'percentage':5,'expected_revision':1}).status_code==403
results['reviewer_publish_denied']=requests.post(base+'/api/policies/seed-1/publish',headers=headers['reviewer'],json={'percentage':5,'expected_revision':1}).status_code==403
key='http-acceptance-'+uuid.uuid4().hex;h={**headers['inspector'],'Idempotency-Key':key}
body={'query':'工程验证：消火栓核查的信息不完整，请列出待补充项。','facility':'indoor_hydrant','use_model':False,'retrieval_mode':'bm25'}
a=requests.post(base+'/api/inspect',headers=h,json=body);a.raise_for_status();first=a.json()
b=requests.post(base+'/api/inspect',headers=h,json=body);b.raise_for_status();results['duplicate_creation_same_task']=first['id']==b.json()['id']
results['idempotency_conflict_rejected']=requests.post(base+'/api/inspect',headers=h,json={**body,'query':'另一个内容'}).status_code in [400,409]
results['inspector_cannot_finalize']=requests.post(base+'/api/reports/'+first['id']+'/review',headers=headers['inspector'],json={'expected_revision':1,'action':'approve'}).status_code==403
# Restart our own workers after both dedicated fixtures have checkpointed.
for _ in range(45):
 own=requests.get(base+'/api/jobs/'+first['id'],headers=headers['inspector']).json()
 if own['status'] not in ['running','queued']:break
 time.sleep(1)
assert own['status']=='awaiting_review'
subprocess.run(['docker','compose','-f',str(ROOT/'deploy/v2/compose.yaml'),'restart','worker'],check=True)
claims=[{'claim_id':'restart-engineering-check','text':'跨进程恢复工程验证，专业结论等待人工核查。','kind':'information_request',
 'observation_ids':[],'evidence_ids':[],'applicability':'unknown','sufficiency':'insufficient','missing_fields':[]}]
review={'expected_revision':old['revision'],'action':'approve','comment':'工程检查点恢复验收；非消防专业审批。','conclusions':claims}
r=requests.post(base+'/api/reports/'+old['id']+'/review',headers=headers['reviewer'],json=review);r.raise_for_status()
for _ in range(45):
 j=requests.get(base+'/api/jobs/'+old['id'],headers=headers['reviewer']).json()
 if j['status'] not in ['running','queued']:break
 time.sleep(1)
results['resumed_after_worker_restart']=j['status']=='complete' and j['result']['report']['status']=='final'
results['duplicate_finalization_rejected']=requests.post(base+'/api/reports/'+old['id']+'/review',headers=headers['reviewer'],json=review).status_code in [400,409]
report={'checks':results,'passed':all(results.values()),'restored_run_id':old['id'],'idempotent_run_id':first['id'],
 'worker_restart_performed':True,'dedicated_engineering_fixtures':True,'professional_review':'not_performed'}
(ROOT/'reports/v2/http_acceptance.json').write_text(json.dumps(report,ensure_ascii=False,indent=2));print(json.dumps(report,ensure_ascii=False));assert report['passed']
