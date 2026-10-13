"""Real development replay and approved engineering canary/rollback drill. Never expert quality scoring."""
import json,time,uuid,sys
import requests
from xfagent.v2.config import ROOT
from xfagent.v2.store import Store,digest
from xfagent.v2.policy import Policies
from xfagent.v2.graphs import inspection_graph
s=Store();base='http://127.0.0.1:8080';out=ROOT/'reports/v2/policy';out.mkdir(parents=True,exist_ok=True)
account=next(x for x in json.loads((ROOT/'runtime/v2/credentials.json').read_text()) if x['username']=='admin')
r=requests.post(base+'/api/auth/login',json=account);r.raise_for_status();h={'Authorization':'Bearer '+r.json()['access_token']}
def post(path,body):
 r=requests.post(base+path,json=body,headers=h);r.raise_for_status();return r.json()
def wait(identifier,seconds=2100):
 end=time.monotonic()+seconds
 while time.monotonic()<end:
  try:j=requests.get(base+'/api/jobs/'+identifier,headers=h,timeout=10).json()
  except requests.RequestException:
   time.sleep(3);continue
  if j['status'] not in ['queued','running']:
   if j['status']=='failed':raise RuntimeError(j.get('error'))
   return j
  time.sleep(3)
 raise TimeoutError(identifier)
source=[x['job_id'] for x in json.loads((ROOT/'reports/v2/live/results.json').read_text())]
if '--resume' in sys.argv or '--retry' in sys.argv:
 p=s.db.policies.find_one({'_id':{'$regex':'^feedback-'}},sort=[('created_at',-1)])
 candidate=p['_id'];f={'feedback_id':p['spec']['source_feedback_ids'][0]}
 job=s.db.jobs.find_one({'kind':'replay','input.policy_id':candidate},sort=[('created_at',-1)])
 source=job['input']['run_ids']
 if '--retry' in sys.argv:
  from xfagent.v2.replay import run_replay
  replayed={'result':run_replay(s,candidate,source,'default')}
 else:replayed=wait(job['_id'])
else:
 f=post('/api/feedback',{'run_id':source[0],'signal':'correction','category':'retrieval',
  'text':'开发测试反馈：对于消防设施遮挡、圈占、取用不便的查询，请保留原词，同时加入消火栓、消防设施、维护管理等规范术语，并补充父条款上下文；不能增加现场结论。'})
 j=wait(f['id']);candidate=j['result']['candidate_id'];print('candidate',candidate,flush=True)
 r=post('/api/policies/'+candidate+'/replay',{'run_ids':source});replayed=wait(r['id']);print('replay',replayed['result'],flush=True)
report={'feedback_id':f['feedback_id'],'policy_id':candidate,'source_run_ids':source,'replay':replayed['result'],'scope':'engineering_development_drill_not_quality_improvement'}
if replayed['result']['status']=='passed':
 p=s.db.policies.find_one({'_id':candidate});post('/api/policies/'+candidate+'/publish',{'percentage':5,'expected_revision':p['version']})
 # Explicit synthetic engineering identity selected for stable 5% assignment; excluded from quality statistics.
 owner=next('canary-drill-'+str(i) for i in range(10000) if int(digest(['canary-drill-'+str(i),candidate])[:8],16)%100<5)
 req=dict(s.db.jobs.find_one({'_id':source[0]})['input']);req['session_id']='canary-'+uuid.uuid4().hex
 terms=p['spec'].get('trigger_terms',[]);req['query']+=' '+(' '.join(terms))
 rid='canary-drill-'+uuid.uuid4().hex
 result=inspection_graph(s).invoke({'run_id':rid,'owner':owner,'request':req,'snapshot_id':s.active_snapshot(),
  'calls':0,'active_seconds':0,'trace':[],'warnings':[]},{'configurable':{'thread_id':rid},'recursion_limit':70})
 report['canary']={'run_id':rid,'assignment':result.get('policy'),'queries':result.get('queries'),'calls':result.get('calls'),'verification':result.get('verification')}
 post('/api/policies/'+candidate+'/rollback',{'reason':'完成开发环境5%灰度与回滚演练；无专业质量改善证据，恢复基线。'})
 restored=Policies(s).choose(owner,'default',req['session_id'],req['query'],result.get('facility'))
 report['restored_policy']=restored['policy_id'];report['final_policy_state']=s.db.policies.find_one({'_id':candidate})['state']
 print('rollback',report['restored_policy'],report['final_policy_state'],flush=True)
(out/'drill.json').write_text(json.dumps(report,ensure_ascii=False,indent=2,default=str))
