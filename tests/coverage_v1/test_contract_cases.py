"""Data-driven requirements tests against real v2 code, using disposable Mongo DBs.

All model/tool responses are injected. No GPU calls or production writes occur.
Failures are reported normally, including existing product defects.
"""
import copy
import json
import os
import uuid
from datetime import timedelta
from pathlib import Path

import numpy as np
import pytest
import requests
from fastapi import HTTPException
from langgraph.types import Command

from xfagent.v2.store import Store, digest
from xfagent.v2.schema import Actor, Strategy
from xfagent.v2.config import now
from xfagent.v2.facts import eligible, fetch_evidence, publish_snapshot
from xfagent.v2.verify import verify
from xfagent.v2.graphs import inspection_graph, verification_route, safe_node, LeaseLost
from xfagent.v2.model import complete, BudgetExhausted
from xfagent.v2.policy import Policies
from xfagent.v2.retrieval import Retrieval
from xfagent.v2.replay_protocol import evaluate_pairs
from xfagent.v2.memory import MemoryContextBuilder

SUITE = Path(os.environ.get('XF_COVERAGE_SUITE', 'benchmarks/coverage_v1'))
CASES = [json.loads(l) for l in (SUITE/'contracts.jsonl').read_text().splitlines() if l.strip()]

@pytest.fixture
def fixture_store():
 name='xfagent_coverage_test_'+uuid.uuid4().hex
 s=Store(name=name)
 try:
  s.setup();Policies(s).seed()
  text='测试夹具：不得遮挡该设施。'
  s.db.documents.insert_one({'_id':'d','doc_id':'d','snapshot_id':'kb','ready':True,'status':'source_verified',
      'kind':'law','jurisdiction':'全国','effective_from':'2021-01-01','effective_until':None,
      'sha256':'fixture-source','url':'https://fixture.invalid/law','conditions':{},'version_id':'v1'})
  s.db.evidence.insert_one({'_id':'e','evidence_id':'e','legacy_id':'e','doc_id':'d','snapshot_id':'kb',
      'text':text,'quote_hash':digest(text.encode()),'source_hash':'fixture-source','version_id':'v1',
      'article':'第一条','location':{'article':'第一条'},'document_title':'合成测试夹具'})
  s.db.snapshots.insert_one({'_id':'kb','state':'published','index_ready':True})
  s.db.settings.insert_one({'_id':'active_snapshot','value':'kb'})
  yield s
 finally:
  assert s.db.name==name and name.startswith('xfagent_coverage_test_')
  s.client.drop_database(name);s.client.close()

def initial(s):
 return {'run_id':'coverage-run','owner':'a','snapshot_id':'kb',
  'request':{'mode':'inspection','query':'核查该消火栓遮挡情况','scene':{},'as_of':'2026-10-05','jurisdiction':'四川',
      'facility':'outdoor_hydrant','project_id':'default','session_id':'coverage','use_model':False,'retrieval_mode':'rrf'},
  'observations':[{'observation_id':'o1','status':'visible_anomaly','description':'现场观察：有遮挡',
      'facility':'outdoor_hydrant','source':'human'}],
  'evidence':[fetch_evidence(s,'kb','e','2026-10-05','四川')],
  'conclusions':[{'claim_id':'c1','text':'该设施存在遮挡，应清理。','kind':'legal_assessment',
      'observation_ids':['o1'],'evidence_ids':['e'],'applicability':'supported','sufficiency':'sufficient','missing_fields':[]}],
  'calls':0,'active_seconds':0,'trace':[],'warnings':[]}

def no_network_graph(monkeypatch):
 import xfagent.v2.graphs as g
 monkeypatch.setattr(g.Retrieval,'search',lambda *a,**k:{'evidence':[],'queries':['q'],'warnings':[]})
 monkeypatch.setattr(MemoryContextBuilder,'remember',lambda *a:None)

def pair_rows():
 good={'elapsed':10,'calls':2,'hard_errors':[],'draft_present':True,'semantic':'model_supported',
       'policy':{'triggered':True}}
 return [{'source_run_id':str(i),'control':copy.deepcopy(good),'treatment':copy.deepcopy(good)} for i in range(3)]

@pytest.mark.parametrize('case',CASES,ids=[c['id'] for c in CASES])
def test_requirement(case, fixture_store, monkeypatch):
 s=fixture_store;p=case['params'];expected=case['expected'];op=case['operation'];state=initial(s)
 if op=='temporal':
  doc={'ready':p.get('ready',True),'status':p.get('status','source_verified'),'kind':p.get('kind','law'),
       'jurisdiction':p.get('doc_jurisdiction','四川'),'effective_from':p.get('effective_from','2024-11-01'),
       'effective_until':p.get('effective_until','2026-10-05')}
  assert eligible(doc,p.get('as_of','2026-10-03'),p.get('jurisdiction','四川')) is expected['eligible']
 elif op=='verify':
  c=state['conclusions'][0]
  if 'text' in p:c['text']=p['text']
  if 'kind' in p:c['kind']=p['kind']
  if 'citation' in p:c['evidence_ids']=[p['citation']] if p['citation'] else []
  if 'observation' in p:c['observation_ids']=[p['observation']] if p['observation'] else []
  if 'observation_status' in p:state['observations'][0]['status']=p['observation_status']
  if p.get('duplicate'):state['conclusions'].append(copy.deepcopy(c))
  if p.get('condition'):
   s.db.documents.update_one({'_id':'d'},{'$set':{'conditions':{'highrise':True}}})
   state['evidence']=[fetch_evidence(s,'kb','e','2026-10-05','四川')]
  state['request']['scene']=p.get('scene',{})
  if 'missing_fields' in p:c['missing_fields']=p['missing_fields']
  if p.get('tamper_field'):
   field=p['tamper_field'];state['evidence'][0][field]={'tampered':True} if field in ['conditions','location'] else 'tampered'
  result=verify(s,state)
  assert result['passed'] is expected['passed'], json.dumps(result,ensure_ascii=False)
  if expected.get('error_code'):assert expected['error_code'] in {e['code'] for e in result['errors']}
 elif op=='route':
  state.update(p);state['verification']={'passed':p.get('passed',False),'errors':[{'code':p.get('code','semantic_unsupported')}]}
  assert verification_route(state)==expected['route']
 elif op=='budget':
  import xfagent.v2.model as m
  called=[]
  def post(url,*a,**k):
   if url.endswith('/tokenize'):
    class Resp:
     def raise_for_status(self):pass
     def json(self):return {'count':20000 if p.get('context_over') else 10}
    return Resp()
   called.append(url);raise AssertionError('model HTTP should have been blocked')
  monkeypatch.setattr(m.requests,'post',post);state.update({k:v for k,v in p.items() if k in ['calls','active_seconds']})
  with pytest.raises(BudgetExhausted):complete(state,'测试',{'evidence':[{'evidence_id':'e','text':'完整测试原文'}]})
  assert not called
 elif op=='pair':
  rows=pair_rows();mut=p['mutation']
  if mut=='regression':rows[1]['treatment']['hard_errors']=[{'code':'missing_evidence'}]
  if mut=='aggregate_hidden':
   rows[0]['control']['hard_errors']=[{'code':'missing_evidence'}];rows[1]['treatment']['hard_errors']=[{'code':'missing_evidence'}]
  if mut=='citation':rows[0]['treatment']['hard_errors']=[{'code':'forged_citation'}]
  if mut=='latency':rows[0]['treatment']['elapsed']=50
  if mut=='no_trigger':
   for r in rows:r['treatment']['policy']['triggered']=False
  if mut=='execution':rows[0]['treatment']['execution_error']='timeout'
  if mut=='no_draft':rows[0]['treatment']['draft_present']=False
  if mut=='too_few':rows=rows[:2]
  assert evaluate_pairs(rows)['passed'] is expected['passed']
 elif op=='restart_budget':
  import xfagent.v2.model as m
  sent=[]
  class Resp:
   def __init__(self,value):self.value=value
   def raise_for_status(self):pass
   def json(self):return self.value
  def post(url,*a,**k):
   if url.endswith('/tokenize'):return Resp({'count':10})
   sent.append(url)
   if len(sent)==1:raise SystemExit('injected process loss after external request, before node checkpoint')
   return Resp({'choices':[{'message':{'content':'{"queries":["q"]}'}}]})
  monkeypatch.setattr(m.requests,'post',post);state['calls']=15
  saved=copy.deepcopy(state)
  def fn(x):return {'queries':complete(x,'测试',{})['queries']}
  with pytest.raises(SystemExit):safe_node(s,'rewrite',fn)(copy.deepcopy(saved))
  try:safe_node(s,'rewrite',fn)(copy.deepcopy(saved))
  except BudgetExhausted:pass
  assert 15+len(sent)<=expected['total_external_calls_with_prior_15_at_most'], 'Budget reset across interrupted-node replay: '+str(15+len(sent))
 elif op=='strategy':
  with pytest.raises(ValueError):Strategy.model_validate({'name':'受限策略',**p})
 elif op=='access':
  a=Actor(user_id='a',role=p['role'],projects=['default']);r={'owner':p.get('owner','a'),'project_id':p.get('project','default')}
  if expected['allowed']:access_result=__import__('xfagent.v2.auth',fromlist=['access']).access(a,r,write=p.get('write',False))
  else:
   with pytest.raises(HTTPException):__import__('xfagent.v2.auth',fromlist=['access']).access(a,r,write=p.get('write',False))
 elif op=='retrieval_outage':
  import xfagent.v2.retrieval as r
  service=p['service'];retriever=Retrieval(s)
  class Vector:
   def search(self,*a,**k):
    if service=='vector':raise TimeoutError('injected vector outage')
    return [[{'id':'e'}] for _ in k['data']]
  def embeddings(texts,**k):
   if service=='embedding':raise TimeoutError('injected embedding outage')
   return np.array([[1.,0.] for _ in texts])
  def post(*a,**k):raise requests.Timeout('injected reranker outage')
  monkeypatch.setattr(r,'embed',embeddings);monkeypatch.setattr(r.requests,'post',post);retriever.vector=Vector()
  result=retriever.search(['遮挡设施'],'kb','2026-10-05',mode='rerank' if service=='reranker' else 'rrf')
  assert result['evidence'] and result['evidence'][0]['evidence_id']=='e'
  assert any(w.startswith('reranker_unavailable' if service=='reranker' else 'dense_unavailable') for w in result['warnings'])
 elif op=='intent':
  import xfagent.v2.graphs as module
  state['request'].update(facility='auto',query=p['query'],use_model=True)
  def classify(x,*a,**k):x['calls']=x.get('calls',0)+1;return {'facility':p['model_facility']}
  monkeypatch.setattr(module,'complete',classify)
  result=inspection_graph(s,checkpointer=False).nodes['intent'].bound.invoke(state)
  assert result['facility']==expected['facility'] and result['calls']==expected['model_calls']
 elif op=='verifier_outage':
  state['verification']={'passed':True}
  def fail(x):raise RuntimeError('injected verifier outage')
  result=safe_node(s,'verify',fail)(state)
  assert not result['verification']['passed'] and result['verification']['semantic_review']=='unavailable'
 elif op=='review':
  state['report']={'status':'draft','verification':{'passed':False,'semantic_review':'model_disputed'}}
  state['review']={'action':p['action'],'reviewer':'reviewer','confirmed_scene':p.get('confirmed_scene',{})}
  if p['action']=='approve' and not p.get('contradiction'):
   # Explicit positive semantic response; bypassing verification is no longer valid.
   state['request']['use_model']=True
   import xfagent.v2.graphs as module
   monkeypatch.setattr(module,'complete',lambda *a,**k:{'supported':True,'issues':[]})
  if p.get('contradiction'):
   state['conclusions'][0]['text']='允许遮挡该设施。'
   state['review']['conclusions']=copy.deepcopy(state['conclusions'])
   state['request']['use_model']=True
   import xfagent.v2.graphs as module
   monkeypatch.setattr(module,'complete',lambda *a,**k:{'supported':False,'issues':[{'claim_id':'c1','reason':'与测试证据相反'}]})
  result=inspection_graph(s,checkpointer=False).nodes['finalize'].bound.invoke(state)
  if expected.get('must_not_final'):assert result.get('report',{}).get('status')!='final', json.dumps(result,ensure_ascii=False)
  else:assert result['status']==expected['status']
 elif op=='lease':
  s.db.jobs.insert_one({'_id':state['run_id'],'status':'running','worker':'replacement','owner':'a','idempotency_key':'lease'})
  state['execution_worker']='expired'
  with pytest.raises(LeaseLost):safe_node(s,'observe',lambda x:{})(state)
 elif op=='lease_after_node':
  s.db.jobs.insert_one({'_id':state['run_id'],'status':'running','worker':'first','owner':'a','idempotency_key':'lease'})
  state['execution_worker']='first'
  def fn(x):s.db.jobs.update_one({'_id':state['run_id']},{'$set':{'worker':'replacement'}});return {'observations':[]}
  with pytest.raises(LeaseLost):safe_node(s,'observe',fn)(state)
 elif op=='resume':
  no_network_graph(monkeypatch);state['request']['mode']='retrieval'
  cfg={'configurable':{'thread_id':'coverage-resume'},'recursion_limit':70}
  first=inspection_graph(s).invoke(state,cfg)
  assert first['__interrupt__'] and first['status']=='awaiting_review'
  second=inspection_graph(s).invoke(Command(resume={'action':'approve','reviewer':'reviewer'}),cfg)
  assert second['status']=='complete' and second['report']['status']=='final'
 elif op=='idempotency':
  actor=Actor(user_id='a',role='reviewer',projects=['default'])
  a=s.submit('inspection',state['request'],actor,'same');b=s.submit('inspection',state['request'],actor,'same')
  assert a['_id']==b['_id'] and s.db.outbox.count_documents({})==1
  s.db.jobs.update_one({'_id':a['_id']},{'$set':{'status':'awaiting_review'}})
  s.enqueue_resume(a,{'expected_revision':1,'action':'approve'},actor)
  with pytest.raises(ValueError):s.enqueue_resume(a,{'expected_revision':1,'action':'approve'},actor)
  assert s.db.outbox.count_documents({})==2
 elif op=='snapshot':
  s.db.snapshots.insert_one({'_id':'new','index_ready':False,'document_count':0})
  with pytest.raises(ValueError):publish_snapshot(s,'new')
  assert s.active_snapshot()=='kb'
  s.db.snapshots.update_one({'_id':'new'},{'$set':{'index_ready':True}})
  with pytest.raises(ValueError):publish_snapshot(s,'new','wrong')
  assert s.active_snapshot()=='kb'
 elif op=='weak_feedback':
  from xfagent.v2.feedback import feedback_graph
  source={'_id':'source','input':state['request'],'project_id':'default','owner':'a'}
  for signal in ['like','copy']:
   f={'_id':signal,'signal':signal,'owner':'a','text':'好','category':'retrieval'};s.db.feedback.insert_one(f)
   result=feedback_graph(s).invoke({'feedback':f,'source':source})
   assert result.get('candidate_id') is None and result['category']=='weak_signal'
 elif op=='memory_consent':
  actor=Actor(user_id='a',role='inspector',projects=['default']);memory=MemoryContextBuilder(s)
  with pytest.raises(ValueError):memory.preference(actor,'default','report_detail','brief',False)
  assert s.db.memories.count_documents({'kind':'user'})==0
 elif op=='incident':
  spec=Strategy(name='灰度测试').model_dump();s.db.policies.insert_one({'_id':'candidate','state':'canary','project_id':'default','spec':spec,'version':1})
  run={'_id':'run','project_id':'default','result':{'policy':{'group':'treatment','experiment_id':'candidate'}}}
  Policies(s).incident(run,'forged_citation','确认严重错误','reviewer')
  assert s.db.policies.find_one({'_id':'candidate'})['state']=='rolled_back'
 elif op=='session_rollback':
  s.db.policies.insert_one({'_id':'candidate','state':'canary','project_id':'default','spec':Strategy(name='灰度测试').model_dump(),
      'version':1,'percentage':100,'approved_at':now()})
  p=Policies(s);first=p.choose('a','default','same-session','核查','outdoor_hydrant');assert first['group']=='treatment'
  p.rollback('candidate','测试回滚');second=p.choose('a','default','same-session','核查','outdoor_hydrant')
  assert second['policy_id']=='baseline-v2'
 elif op=='queue_recovery':
  actor=Actor(user_id='a',role='inspector',projects=['default']);job=s.submit('inspection',state['request'],actor,'recover')
  s.db.jobs.update_one({'_id':job['_id']},{'$set':{'created_at':now()-timedelta(seconds=120)}})
  assert s.recover_dispatch()==1 and s.recover_dispatch()==0
  assert s.db.outbox.count_documents({'reason':'durable_job_reconciliation'})==1
 elif op=='memory_isolation':
  m=MemoryContextBuilder(s)
  class Redis:
   def get(self,key):return None
  m.redis=Redis()
  for identifier,owner,project,expires in [('own','a','default',now()+timedelta(days=1)),('other-owner','b','default',now()+timedelta(days=1)),
                                        ('other-project','a','other',now()+timedelta(days=1)),('expired','a','default',now()-timedelta(days=1))]:
   s.db.memories.insert_one({'_id':identifier,'kind':'user','owner':owner,'project_id':project,'expires_at':expires,'content':identifier,'created_at':now()})
  result=m.build('a','default','session','kb','2026-10-05','四川')
  assert [x['content'] for x in result['preferences']]==['own']
 elif op=='trace':
  state.update(calls=3,warnings=['historical-warning'])
  def fn(x):x['calls']+=1;return {}
  r=safe_node(s,'draft',fn)(state);event=r['trace'][-1]
  assert event['calls_delta']==1 and event['warnings']==[] and event['outcome']=='ok'
  assert s.db.events.count_documents({'run_id':state['run_id']})==1
 elif op=='model_failure':
  import xfagent.v2.graphs as g
  no_network_graph(monkeypatch)
  monkeypatch.setattr(g.Retrieval,'search',lambda *a,**k:{'evidence':state['evidence'],'queries':['q'],'warnings':[]})
  def fail(*a,**k):raise requests.Timeout('injected model outage')
  monkeypatch.setattr(g,'complete',fail);state['request']['use_model']=True;state['request']['mode']='retrieval'
  result=inspection_graph(s).invoke(state,{'configurable':{'thread_id':'model-failure'},'recursion_limit':70})
  assert result['__interrupt__'] and result['report']['status']=='draft' and result['warnings']
 else:raise AssertionError('Unimplemented requirement operation: '+op)
