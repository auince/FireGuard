"""Exercise simulated-human feedback through actual v2 code in an isolated DB.

offline: injected model responses, actual Mongo/graphs/BM25/review/release code.
live9b: actual 9B for feedback attribution/adaptation; other fixtures remain injected.
No fake events, reference labels or canary samples enter the application database.
"""
import argparse, copy, json, time, uuid
from collections import Counter
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch

def rows(path):return [json.loads(x) for x in path.read_text().splitlines()]
def write(path,value):path.parent.mkdir(parents=True,exist_ok=True);path.write_text(json.dumps(value,ensure_ascii=False,indent=2,default=str))

def seed(store):
 from xfagent.v2.store import digest
 from xfagent.v2.policy import Policies
 from xfagent.v2.model_routes import manifest
 store.setup();Policies(store).seed()
 text='仿真工程夹具：室内消火栓、室外消火栓和灭火器应保持便于取用，不得遮挡。'
 store.db.documents.insert_one({'_id':'d','doc_id':'d','snapshot_id':'sim-kb','ready':True,
   'status':'source_verified','kind':'law','lifecycle':'active','jurisdiction':'全国',
   'sha256':digest(text.encode()),'body_hash':digest(text.encode()),'full_text':text,'version_id':'sim-v1',
   'url':'https://fixture.invalid/not-a-law','conditions':{},'simulation_only':True})
 store.db.evidence.insert_one({'_id':'e','evidence_id':'e','legacy_id':'e','doc_id':'d','snapshot_id':'sim-kb',
   'text':text,'quote_hash':digest(text.encode()),'source_hash':digest(text.encode()),'version_id':'sim-v1',
   'article':'模拟条款','document_title':'仿真工程夹具（不是法律依据）','location':{'article':'模拟条款'},'simulation_only':True})
 store.db.snapshots.insert_one({'_id':'sim-kb','state':'published','index_ready':True})
 store.db.settings.insert_one({'_id':'active_snapshot','value':'sim-kb'})
 store.db.settings.insert_one({'_id':'generator_fingerprint','value':'injected-simulation-not-real-9b'})
 return digest(manifest())

def source_row(case):
 req=copy.deepcopy(case['source']['input']);req.update(project_id='default',use_model=True,retrieval_mode='bm25')
 return {'_id':case['feedback_payload']['run_id'],'owner':case['persona']['user_id'],'project_id':'default',
   'kind':'inspection','idempotency_key':case['feedback_payload']['run_id'],'input':req,'snapshot_id':'sim-kb','benchmark_split':'dev','simulation_only':True,
   'result':{'report':{'status':'draft','simulation_only':True,
      'conclusions':[{'text':case['source']['simulated_agent_output'],'provenance':'authored_simulated_output'}],
      'verification':{'passed':False,'missing_fields':case['source']['missing_fields']}}}}

def run(suite,out,mode,limit,keep_db):
 from xfagent.v2.store import Store,digest
 from xfagent.v2.schema import Feedback,Review,Actor
 from xfagent.v2.feedback import feedback_graph,cluster_gaps
 from xfagent.v2.graphs import inspection_graph
 from xfagent.v2.policy import Policies
 from xfagent.v2.facts import fetch_evidence
 from xfagent.v2.retrieval import Retrieval
 from xfagent.v2.replay import run_replay
 from xfagent.v2.model_routes import manifest
 import xfagent.v2.api as api
 if any(role['name']!='xf-qwen3.5-9b' or role['backend']!='chat' for role in manifest().values()):
  raise ValueError('This practice profile requires all roles to use the configured 9B chat model')
 if mode=='live9b':
  import requests
  from xfagent.v2.config import MODEL_URL
  models=requests.get(MODEL_URL+'/models',timeout=(3,5));models.raise_for_status()
  if 'xf-qwen3.5-9b' not in {r['id'] for r in models.json()['data']}:raise ValueError('9B endpoint is not ready')
 cases=rows(suite/'human_feedback.jsonl');review_cases=rows(suite/'human_reviews.jsonl')
 if limit:cases=cases[:limit]
 index={case['id']:case for case in cases};database='xfagent_feedback_sim_'+uuid.uuid4().hex
 store=Store(name=database);seed(store);policies=Policies(store)
 report={'scope':'resume_practice_simulation','database':database,'mode':mode,
   'configured_model':'xf-qwen3.5-9b','feedback_inference':'real_9b' if mode=='live9b' else 'injected_fixture',
   'inspection_replay_inference':'injected_fixture','real_human_events':0,'real_expert_accuracy':None,
   'feedback':[],'human_reviews':[],'policy_loops':[],'errors':[],
   'fixture_rules':'synthetic_not_legal_truth','canary_metrics':'constructed_not_online_metrics'}
 classification_calls=[];started=time.monotonic()
 def model_fixture(state,instruction,payload,image=None,role='answer'):
  state['calls']=state.get('calls',0)+1
  state.setdefault('warnings',[]).append('simulation_injected_model_response:'+role)
  if role=='reflect':
   case=index[payload['feedback']['_id']];classification_calls.append(case['id'])
   return {'category':case['expected']['initial_category'],'reason':'仿真反馈对应的注入归因'}
  if role=='adapt':return {'trigger_terms':['消防箱'],'expand_terms':['便于取用','消火栓'],'parent_expand':False}
  if role=='rewrite':return {'queries':[]}
  if role=='intent':return {'facility':state['request'].get('facility','unknown')}
  if role=='answer':
   scene=payload.get('scene',{});fault=scene.get('simulation_fault_kind');template=payload.get('template')
   if template=='measurement_required':
    return {'conclusions':[{'claim_id':'c1','kind':'information_request','text':'请补充现场实测条件，现有信息不足以判断。',
      'observation_ids':[],'evidence_ids':[],'applicability':'unknown','sufficiency':'insufficient','missing_fields':['pressure_measurement']}]}
   text='设施应保持便于取用，不得遮挡。'
   if fault=='generation' and template!='risk_action_evidence':text='允许遮挡该设施。'
   if fault=='applicability':text='现场水压0.25MPa，判断为达标。'
   return {'conclusions':[{'claim_id':'c1','kind':'legal_assessment','text':text,'observation_ids':[],
     'evidence_ids':['e1'],'applicability':'supported','sufficiency':'sufficient','missing_fields':[]}]}
  if role=='verify':
   supported=not any('允许遮挡' in row.get('text','') for row in payload.get('conclusions',[]))
   return {'supported':supported,'issues':[] if supported else [{'claim_id':'c1','reason':'与合成规则相反'}]}
  raise ValueError('unhandled simulation model role: '+role)
 original_search=Retrieval.search
 def retrieval_fixture(self,queries,*args,**kwargs):
  # A controlled miss demonstrates a Skill fixing recall, rather than pretending
  # an observed 9B/RAG failure. The treatment still runs actual BM25 and refill.
  if getattr(self,'simulation_profile',None)=='retrieval' and not any('便于取用' in q for q in queries):
   time.sleep(.15)
   return {'queries':queries,'evidence':[],'warnings':['simulation_injected_retrieval_miss']}
  time.sleep(.15)
  return original_search(self,queries,*args,**kwargs)
 try:
  with ExitStack() as stack:
   stack.enter_context(patch.object(api,'store',store))
   if mode=='offline':stack.enter_context(patch('xfagent.v2.feedback.complete',model_fixture))
   for number,case in enumerate(cases):
    f={**Feedback.model_validate(case['feedback_payload']).model_dump(),'_id':case['id'],
       'owner':case['persona']['user_id'],'project_id':'default','state':'queued','simulation_only':True}
    source=source_row(case);store.db.jobs.insert_one(source);store.db.feedback.insert_one(f)
    try:
     result=feedback_graph(store).invoke({'feedback':f,'source':source,'calls':0,'active_seconds':0})
     initial_kind=(store.db.policies.find_one({'_id':result.get('candidate_id')}) or {}).get('spec',{}).get('kind')
     if case['profile']=='attribution_correction':
      old=result.get('candidate_id');who=Actor(user_id='sim-reviewer',role='reviewer',projects=['default'])
      correction=case['followup_events'][0]['payload'];api.correct_attribution(f['_id'],correction,who)
      new_feedback=store.db.feedback.find_one({'_id':f['_id']})
      result=feedback_graph(store).invoke({'feedback':new_feedback,'source':source,'calls':0,'active_seconds':0})
      assert store.db.policies.find_one({'_id':old})['state']=='deprecated'
     candidate=store.db.policies.find_one({'_id':result.get('candidate_id')})
     actual_kind=candidate['spec']['kind'] if candidate else None
     passed=result['category']==case['expected']['final_category'] and actual_kind==case['expected']['candidate_kind']
     if any(e['type']=='repeat_submit_same_idempotency_key' for e in case['followup_events']):
      stored=store.db.feedback.find_one({'_id':f['_id']})
      again=feedback_graph(store).invoke({'feedback':stored,'source':source,'calls':0,'active_seconds':0})
      passed=passed and again.get('candidate_id')==result.get('candidate_id')
     if candidate:passed=passed and candidate['state']=='draft'
     report['feedback'].append({'id':case['id'],'expected_category':case['expected']['final_category'],
       'category':result['category'],'initial_kind':initial_kind,'candidate_kind':actual_kind,
       'candidate_id':result.get('candidate_id'),'passed':passed,'simulation_only':True})
    except Exception as exc:
     report['feedback'].append({'id':case['id'],'passed':False,'error':type(exc).__name__+':'+str(exc)[:300]})
    if (number+1)%40==0:print('feedback',number+1,'/',len(cases),flush=True)
   # Run the real knowledge-gap clustering with deliberately injected vectors.
   import numpy as np
   with patch('xfagent.v2.feedback.embed',lambda texts,**kw:np.array([[1.,0.] for _ in texts])):
    tickets=cluster_gaps(store,'default')
   report['backlogs']={'vision':store.db.annotation_backlog.count_documents({}),
       'knowledge_gaps':store.db.knowledge_gaps.count_documents({}),'knowledge_tickets':len(tickets),
       'clustering_embedding':'injected_identical_vectors_for_control_flow'}
   # Reviewer actions exercise the real API, revision CAS, and finalize gate.
   stack.enter_context(patch('xfagent.v2.graphs.complete',model_fixture))
   reviewer=Actor(user_id='sim-reviewer',role='reviewer',projects=['default'])
   for case in review_cases:
    identifier=case['id'];req=copy.deepcopy(case['source']['input']);req.update(mode='retrieval',scene={},use_model=True)
    claim={'claim_id':'c1','text':'设施应保持便于取用，不得遮挡。','kind':'legal_assessment',
       'evidence_ids':['e'],'observation_ids':[],'applicability':'supported','sufficiency':'sufficient','missing_fields':[]}
    kind=case['review_type']
    if kind=='opposite_meaning':claim['text']='允许遮挡该设施。'
    if kind=='forged_citation':claim['evidence_ids']=['fake-evidence']
    if kind=='invented_measurement':claim['text']='现场水压0.25MPa，已达标。'
    state={'run_id':identifier,'owner':'sim-inspector','snapshot_id':'sim-kb','request':req,
      'conclusions':[claim],'evidence':[fetch_evidence(store,'sim-kb','e','2026-10-05','四川')],
      'observations':[],'calls':0,'active_seconds':0,'warnings':[],'trace':[],
      'report':{'status':'draft','conclusions':[claim],'verification':{'passed':False}}}
    store.db.jobs.insert_one({'_id':identifier,'owner':'sim-inspector','project_id':'default','kind':'inspection',
      'input':req,'result':state,'revision':1,'status':'awaiting_review','idempotency_key':identifier,'simulation_only':True})
    body=Review.model_validate(case['review_payload']);status=None;detail=None
    try:
     api.review(identifier,body,reviewer)
     if kind=='duplicate_submit':
      try:api.review(identifier,body,reviewer);raise AssertionError('duplicate accepted')
      except (ValueError,__import__('fastapi').HTTPException):pass
      assert store.db.outbox.count_documents({'job_id':identifier})==1
      status='queued_once'
     else:
      state['review']={**body.model_dump(),'reviewer':reviewer.user_id}
      result=inspection_graph(store,checkpointer=False).nodes['finalize'].bound.invoke(state)
      status='redrafting' if result['status']=='redrafting' else result['report']['status']
    except (ValueError,__import__('fastapi').HTTPException) as exc:status='blocked';detail=str(exc)[:300]
    except Exception as exc:status='execution_error';detail=type(exc).__name__+':'+str(exc)[:300]
    report['human_reviews'].append({'id':identifier,'status':status,'expected':case['expected']['status'],
      'passed':status==case['expected']['status'],'detail':detail,'simulation_only':True})
   # Full Execute -> Observe -> Reflect -> Adapt -> Deploy for all three kinds.
   stack.enter_context(patch.object(Retrieval,'search',retrieval_fixture))
   for profile,policy_kind in [('retrieval','skill'),('generation','hook'),('applicability','rule')]:
    candidate=next((r for r in report['feedback'] if r.get('candidate_kind')==policy_kind and r.get('passed')),None)
    if not candidate:report['errors'].append('missing_candidate:'+policy_kind);continue
    pid=candidate['candidate_id'];sources=[]
    # Per-graph retrieval objects carry this local fault-injection profile.
    original_init=Retrieval.__init__
    def init(self,s,profile=profile):original_init(self,s);self.simulation_profile=profile
    with patch.object(Retrieval,'__init__',init):
     for j in range(3):
      identifier='paired-'+profile+'-'+str(j)
      req={'query':['消防箱怎么维护？','请核查消防箱取用条件。','消防箱被遮挡该怎么处理？'][j],
        'mode':'retrieval','facility':'indoor_hydrant','project_id':'default','session_id':identifier,
        'as_of':'2026-10-05','jurisdiction':'四川','scene':{'simulation_fault_kind':profile},
        'use_model':True,'retrieval_mode':'bm25'}
      source=inspection_graph(store).invoke({'run_id':identifier,'owner':'sim-inspector','request':req,
        'snapshot_id':'sim-kb','frozen_memory':{},'forced_policy':'baseline-v2','calls':0,
        'active_seconds':0,'trace':[],'warnings':[]}, {'configurable':{'thread_id':identifier},'recursion_limit':70})
      source.pop('__interrupt__',None)
      store.db.jobs.insert_one({'_id':identifier,'owner':'sim-inspector','project_id':'default',
        'kind':'retrieval','idempotency_key':identifier,'input':req,'snapshot_id':'sim-kb','result':source,'benchmark_split':'dev','simulation_only':True})
      sources.append(identifier)
     replay=run_replay(store,pid,sources,'default')
    evaluation=store.db.evaluations.find_one({'_id':replay['evaluation_id']})
    before=[r['control'] for r in evaluation['results']];after=[r['treatment'] for r in evaluation['results']]
    loop={'kind':policy_kind,'policy_id':pid,'simulation_only':True,'replay':replay,
      'control_with_evidence':sum(bool(r.get('evidence_ids')) for r in before),
      'treatment_with_evidence':sum(bool(r.get('evidence_ids')) for r in after),
      'control_hard_errors':sum(len(r.get('hard_errors',[])) for r in before),
      'treatment_hard_errors':sum(len(r.get('hard_errors',[])) for r in after),
      'inference':'injected_not_real_9b','release_steps':[]}
    if replay['status']!='passed':report['policy_loops'].append(loop);continue
    admin=Actor(user_id='sim-admin',role='admin',projects=['default'])
    if policy_kind=='rule':
     try:policies.publish(pid,admin,5,1);raise AssertionError('Rule review gate bypassed')
     except ValueError:loop['rule_review_required']=True
     api.rule_review(pid,admin)
    policies.publish(pid,admin,5,1);loop['release_steps'].append(5)
    assigned=[policies.choose('sim-user-'+str(j),'default','sim-'+profile+'-'+str(j),'消防箱','indoor_hydrant') for j in range(40)]
    assert assigned==[policies.choose('sim-user-'+str(j),'default','sim-'+profile+'-'+str(j),'消防箱','indoor_hydrant') for j in range(40)]
    loop['stable_assignment']=True
    try:policies.publish(pid,admin,20,2);raise AssertionError('minimum sample gate bypassed')
    except ValueError:loop['minimum_sample_gate']=True
    store.db.treatments.insert_many([{'experiment_id':pid,'group':group,'completed':True,
       'elapsed':1. if group=='control' else 1.05,'error':False,'simulation_only':True,
       'metrics_source':'constructed_for_monitor_logic'} for group in ['control','treatment'] for j in range(100)])
    for percentage in [20,50,100]:
     policy=store.db.policies.find_one({'_id':pid});policies.publish(pid,admin,percentage,policy['version']);loop['release_steps'].append(percentage)
    # Construct regressions only in this simulation DB and exercise real monitor.
    store.db.treatments.insert_many([{'experiment_id':pid,'group':'treatment','completed':True,
       'elapsed':2.,'error':False,'simulation_only':True,'metrics_source':'constructed_injected_regression'} for j in range(100)])
    policies.monitor(pid)
    loop['rollback_state']=store.db.policies.find_one({'_id':pid})['state']
    loop['after_rollback']=policies.choose('sim-user-0','default','sim-'+profile+'-0','消防箱','indoor_hydrant')['policy_id']
    assert loop['rollback_state']=='rolled_back' and loop['after_rollback']=='baseline-v2'
    report['policy_loops'].append(loop)
  report['summary']={'feedback_cases':len(report['feedback']),'feedback_passed':sum(r['passed'] for r in report['feedback']),
    'review_cases':len(report['human_reviews']),'review_passed':sum(r['passed'] for r in report['human_reviews']),
    'paired_replay_kinds':len(report['policy_loops']),
    'release_rollback_kinds':sum(r.get('rollback_state')=='rolled_back' for r in report['policy_loops']),
    'generated_candidate_kinds':dict(Counter(r.get('candidate_kind') for r in report['feedback'] if r.get('candidate_kind')))}
  report['passed']=all(r['passed'] for r in report['feedback']+report['human_reviews']) and len(report['policy_loops'])==3 and all(r.get('rollback_state')=='rolled_back' for r in report['policy_loops']) and not report['errors']
 finally:
  report['seconds']=round(time.monotonic()-started,3)
  if not keep_db:
   assert database.startswith('xfagent_feedback_sim_');store.client.drop_database(database)
   report['cleanup_verified']=database not in store.client.list_database_names()
  else:report['retained_simulation_database']=database
  store.client.close();write(out,report)
 print(json.dumps({k:v for k,v in report.items() if k not in ['feedback','human_reviews','policy_loops']},ensure_ascii=False,default=str),flush=True)
 return report

if __name__=='__main__':
 parser=argparse.ArgumentParser();parser.add_argument('--suite',type=Path,default=Path('benchmarks/feedback_sim_v1'))
 parser.add_argument('--report',type=Path,default=Path('reports/feedback_sim_v1/run.json'))
 parser.add_argument('--mode',choices=['offline','live9b'],default='offline');parser.add_argument('--limit',type=int,default=0)
 parser.add_argument('--keep-db',action='store_true');args=parser.parse_args()
 result=run(args.suite,args.report,args.mode,args.limit,args.keep_db)
 raise SystemExit(0 if result['passed'] else 1)
