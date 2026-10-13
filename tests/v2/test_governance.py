import os,uuid,copy
from datetime import timedelta
import pytest
from langgraph.types import Command
from xfagent.v2.store import Store,digest
from xfagent.v2.schema import Actor,Strategy
from xfagent.v2.config import now
from xfagent.v2.facts import eligible,fetch_evidence,publish_snapshot
from xfagent.v2.verify import verify
from xfagent.v2.policy import Policies
from xfagent.v2.graphs import inspection_graph
from xfagent.v2.auth import access
from xfagent.v2.memory import MemoryContextBuilder
from fastapi import HTTPException

@pytest.fixture
def db():
    name='xfagent_test_'+uuid.uuid4().hex
    s=Store(name=name);s.setup();Policies(s).seed()
    yield s
    s.client.drop_database(name)

@pytest.fixture
def state(db):
    text='任何单位和个人不得埋压、圈占、遮挡消火栓。'
    db.db.documents.insert_one({'_id':'d','doc_id':'d','snapshot_id':'kb','ready':True,'status':'source_verified',
        'kind':'law','jurisdiction':'全国','effective_from':'2021-04-29','sha256':'source','url':'https://example.gov.cn/law','conditions':{}})
    db.db.evidence.insert_one({'_id':'e','evidence_id':'e','legacy_id':'old','doc_id':'d','snapshot_id':'kb','text':text,
        'quote_hash':digest(text.encode()),'source_hash':'source'})
    return {'run_id':'run','owner':'a','snapshot_id':'kb','request':{'mode':'inspection','query':'检查消火栓','scene':{},'as_of':'2026-10-03',
        'jurisdiction':'四川','facility':'outdoor_hydrant','project_id':'default','session_id':'s','use_model':False},
        'observations':[{'observation_id':'o1','status':'visible_anomaly','description':'被杂物遮挡','facility':'outdoor_hydrant'}],
        'evidence':[fetch_evidence(db,'kb','e','2026-10-03','四川')], 'conclusions':[{'claim_id':'c1','text':'消火栓被遮挡，应核查清理。','kind':'legal_assessment',
        'observation_ids':['o1'],'evidence_ids':['e'],'applicability':'supported','sufficiency':'sufficient','missing_fields':[]}]}

def test_temporal_and_jurisdiction_filters():
    d={'ready':True,'status':'source_verified','kind':'local_regulation','jurisdiction':'四川','effective_from':'2024-11-01','effective_until':'2027-01-01'}
    assert eligible(d,'2026-10-03','四川')
    assert not eligible(d,'2024-10-31','四川')
    assert not eligible(d,'2027-01-01','四川')
    assert not eligible(d,'2026-10-03','全国')
    assert not eligible({**d,'kind':'announcement'},'2026-10-03','四川')

def test_forged_and_modified_citations(db,state):
    assert verify(db,state)['passed']
    bad=copy.deepcopy(state);bad['conclusions'][0]['evidence_ids']=['invented']
    assert 'forged_citation' in {e['code'] for e in verify(db,bad)['errors']}
    db.db.evidence.update_one({'_id':'e'},{'$set':{'text':'被篡改'}})
    assert 'source_mismatch' in {e['code'] for e in verify(db,state)['errors']}

def test_stale_metadata_refill(db,state):
    db.db.documents.update_one({'_id':'d'},{'$set':{'effective_until':'2026-01-01'}})
    assert fetch_evidence(db,'kb','e','2026-10-03','四川') is None
    assert fetch_evidence(db,'kb','e','2025-01-01','四川') is not None

def test_missing_applicability_and_unobservable_fact(db,state):
    db.db.documents.update_one({'_id':'d'},{'$set':{'conditions':{'highrise':True}}})
    assert 'unknown_applicability' in {e['code'] for e in verify(db,state)['errors']}
    state['request']['scene']['highrise']=True;state['observations'][0]['status']='uncertain'
    assert 'uncertain_observation' in {e['code'] for e in verify(db,state)['errors']}

def test_unmeasured_numeric_claim(db,state):
    state['conclusions'][0]['text']='通道宽度为0.8米，不符合要求'
    assert 'unmeasured_fact' in {e['code'] for e in verify(db,state)['errors']}

def test_project_and_ownership():
    a=Actor(user_id='a',role='inspector',projects=['default'])
    access(a,{'owner':'a','project_id':'default'})
    for r in [{'owner':'b','project_id':'default'},{'owner':'a','project_id':'other'}]:
        with pytest.raises(HTTPException):access(a,r)
    with pytest.raises(HTTPException):access(a,{'owner':'a','project_id':'default'},write=True)

def test_job_transaction_idempotency_and_lease(db):
    a=Actor(user_id='a',role='inspector',projects=['default'])
    first=db.submit('retrieval',{'query':'q','project_id':'default'},a,'same')
    second=db.submit('retrieval',{'query':'q','project_id':'default'},a,'same')
    assert first['_id']==second['_id'];assert db.db.outbox.count_documents({})==1
    with pytest.raises(ValueError):db.submit('retrieval',{'query':'different'},a,'same')
    assert db.claim(first['_id'],'w1')
    assert db.claim(first['_id'],'w2') is None
    db.db.jobs.update_one({'_id':first['_id']},{'$set':{'lease_until':now()-timedelta(seconds=1)}})
    assert db.claim(first['_id'],'w2')
    assert not db.finish(first['_id'],'w1',{'status':'complete'})

def test_duplicate_review_does_not_enqueue_twice(db):
    a=Actor(user_id='a',role='reviewer',projects=['default'])
    j=db.submit('inspection',{'project_id':'default'},a,'x')
    db.db.jobs.update_one({'_id':j['_id']},{'$set':{'status':'awaiting_review'}})
    review={'expected_revision':1,'action':'approve'}
    assert db.enqueue_resume(j,review,a)==2
    with pytest.raises(ValueError):db.enqueue_resume(j,review,a)
    assert db.db.outbox.count_documents({})==2

def test_policy_cannot_disable_gates():
    with pytest.raises(Exception):Strategy(name='unsafe',disable_verifier=True)
    with pytest.raises(Exception):Strategy(name='unsafe',evidence_k=100)

def test_rollout_requires_real_regression(db):
    p=Policies(db);a=Actor(user_id='a',role='admin',projects=['default'])
    identifier=p.candidate({'name':'test'},'default','a')
    with pytest.raises(ValueError,match='回放'):p.publish(identifier,a,5,1)

def test_stable_assignment_and_emergency_rollback(db):
    p=Policies(db)
    db.db.policies.insert_one({'_id':'trial','state':'canary','project_id':'default','spec':Strategy(name='trial').model_dump(),
        'version':1,'percentage':100,'approved_at':now()})
    one=p.choose('a','default','session','query','outdoor_hydrant')
    assert one['policy_id']=='trial'
    db.db.policies.update_one({'_id':'trial'},{'$set':{'percentage':5}})
    assert p.choose('a','default','session','query','outdoor_hydrant')['policy_id']=='trial'
    p.rollback('trial','test')
    assert p.choose('a','default','session','query','outdoor_hydrant')['policy_id']=='baseline-v2'

def test_metric_rollback_needs_minimum_samples(db):
    p=Policies(db)
    for group,n,elapsed in [('control',100,1),('treatment',99,3)]:
        db.db.treatments.insert_many([{'experiment_id':'x','group':group,'completed':True,'elapsed':elapsed,'error':False} for _ in range(n)])
    assert not p.statistics('x')['regressed']
    db.db.treatments.insert_one({'experiment_id':'x','group':'treatment','completed':True,'elapsed':3,'error':False})
    assert p.statistics('x')['regressed']

def test_unready_snapshot_never_replaces_active(db):
    db.db.settings.insert_one({'_id':'active_snapshot','value':'old'})
    db.db.snapshots.insert_one({'_id':'new','state':'pending'})
    with pytest.raises(ValueError):publish_snapshot(db,'new')
    assert db.active_snapshot()=='old'

def test_memory_requires_consent_and_original_binding(db,state):
    builder=MemoryContextBuilder(db);a=Actor(user_id='a',role='inspector',projects=['default'])
    with pytest.raises(ValueError):builder.preference(a,'default','report_detail','short',False)
    with pytest.raises(ValueError):builder.preference(a,'default','building_pressure',5,True)
    builder.preference(a,'default','report_detail','short',True)
    db.db.memories.insert_one({'_id':'faq','kind':'organization','project_id':'default','approved':True,'content':'outdated',
        'evidence_ids':['missing'],'created_at':now(),'expires_at':now()+timedelta(days=1)})
    ctx=builder.build('a','default','session','kb','2026-10-03','四川')
    assert len(ctx['preferences'])==1;assert not ctx['organization']
    assert db.db.memories.find_one({'_id':'faq'})['needs_review']

def test_langgraph_resume_survives_new_graph_instance(db,state,monkeypatch):
    from xfagent.v2 import graphs
    monkeypatch.setattr(graphs.Retrieval,'search',lambda *a,**k:{'evidence':[],'queries':['q'],'warnings':[]})
    g=inspection_graph(db);cfg={'configurable':{'thread_id':'restart'},'recursion_limit':70}
    state.update(calls=0,active_seconds=0,trace=[],warnings=[]);state['request']['mode']='retrieval'
    first=g.invoke(state,cfg)
    assert first['__interrupt__'];assert first['status']=='awaiting_review'
    second=inspection_graph(db).invoke(Command(resume={'action':'approve','reviewer':'human','comment':'保留信息不足结论'}),cfg)
    assert second['status']=='complete';assert second['report']['status']=='final'
    assert db.db.memories.count_documents({'kind':'episode'})==1

def test_budget_exhaustion_still_produces_reviewable_report(db,state,monkeypatch):
    from xfagent.v2.graphs import safe_node
    value=safe_node(db,'review_ready',lambda s:{'report':{'status':'draft'}})({**state,'active_seconds':301,'trace':[],'calls':16})
    assert value['report']['status']=='draft';assert value['exhausted']
    ran=[]
    value=safe_node(db,'draft',lambda s:ran.append(True))({**state,'active_seconds':301,'trace':[],'calls':16})
    assert not ran and value['exhausted']

def test_weak_feedback_never_creates_policy(db,state):
    from xfagent.v2.feedback import feedback_graph
    for signal in ['like','copy']:
        f={'_id':signal,'signal':signal,'owner':'a','text':'好','category':'retrieval'}
        db.db.feedback.insert_one(f)
        result=feedback_graph(db).invoke({'feedback':f,'source':{'_id':'run','input':state['request'],'project_id':'default','owner':'a'}})
        assert result['category']=='weak_signal';assert result.get('candidate_id') is None
    assert db.db.policies.count_documents({'owner':'a'})==0

def test_replay_requires_three_distinct_runs(db):
    from xfagent.v2.replay import run_replay
    with pytest.raises(ValueError,match='3至60'):run_replay(db,'baseline-v2',['same']*3,'default')

def test_legal_claim_cannot_hide_as_observation(db,state):
    state['conclusions'][0].update(kind='observation',text='根据消防法，该消火栓不符合要求',evidence_ids=[])
    assert not verify(db,state)['passed']

def test_retrieval_service_failures_preserve_sparse_evidence(db,state,monkeypatch):
    from xfagent.v2.retrieval import Retrieval
    import xfagent.v2.retrieval as module
    # Service failure is injected while canonical text remains in the real fact store.
    db.db.snapshots.insert_one({'_id':'kb','state':'published','collection':'does_not_exist'})
    r=Retrieval(db)
    monkeypatch.setattr(module,'embed',lambda *a,**k:(_ for _ in ()).throw(TimeoutError('embedding offline')))
    answer=r.search(['消火栓遮挡'],'kb','2026-10-03','四川',mode='rrf',k=5)
    assert answer['warnings'];assert answer['evidence'][0]['evidence_id']=='e'

def test_expired_worker_cannot_write_new_graph_state(db,state):
    from xfagent.v2.graphs import safe_node,LeaseLost
    db.db.jobs.insert_one({'_id':'run','status':'running','worker':'replacement','owner':'a','idempotency_key':'lease-test'})
    with pytest.raises(LeaseLost):safe_node(db,'observe',lambda s:{'observations':[]})({**state,'execution_worker':'expired'})

def test_snapshot_publish_compare_and_swap(db):
    from xfagent.v2.facts import publish_snapshot
    db.db.snapshots.insert_one({'_id':'new','index_ready':True,'document_count':0,'state':'pending'})
    db.db.settings.insert_one({'_id':'active_snapshot','value':'other'})
    with pytest.raises(ValueError,match='变化'):publish_snapshot(db,'new','old')
    assert db.active_snapshot()=='other'
    assert db.db.snapshots.find_one({'_id':'new'})['state']=='pending'

def test_context_budget_removes_history_before_parent(db,monkeypatch):
    from xfagent.v2.model import fit_payload
    import xfagent.v2.model as m
    class Response:
        def __init__(self,data):self.data=data
        def raise_for_status(self):pass
        def json(self):return self.data
    def tokenize(url,json,timeout):return Response({'count':len(json['prompt'])})
    monkeypatch.setattr(m.requests,'post',tokenize)
    state={};payload={'evidence':[{'evidence_id':'e','text':'完整原文','parent_text':'p'*1000}],
        'conversation_background_not_current_facts':['h'*17000]}
    result=fit_payload(state,'instruction',payload,None)
    assert result['evidence'][0]['text']=='完整原文'
    assert result['evidence'][0]['parent_text']=='p'*1000
    assert not result['conversation_background_not_current_facts']
    assert payload['conversation_background_not_current_facts']

def test_context_budget_never_silently_truncates_original_evidence(db,monkeypatch):
    from xfagent.v2.model import fit_payload,BudgetExhausted
    import xfagent.v2.model as m
    class Response:
        def raise_for_status(self):pass
        def json(self):return {'count':20000}
    monkeypatch.setattr(m.requests,'post',lambda *a,**k:Response())
    payload={'evidence':[{'evidence_id':'e','text':'完整原文','parent_text':'parent'}]};state={}
    with pytest.raises(BudgetExhausted):fit_payload(state,'instruction',payload,None)
    assert payload['evidence'][0]['text']=='完整原文'
    assert 'e' in state['context_gaps']

def test_hook_and_rule_only_allow_stage_appropriate_parameters():
    with pytest.raises(ValueError):Strategy(name='bad hook',kind='hook')
    with pytest.raises(ValueError):Strategy(name='late search change',kind='hook',hook='before_draft',expand_terms=['x'])
    assert Strategy(name='request facts',kind='hook',hook='before_draft',require_fields=['building_use'])
    with pytest.raises(ValueError):Strategy(name='bad rule',kind='rule',expand_terms=['x'])
    assert Strategy(name='facts rule',kind='rule',require_fields=['building_use'])

def test_whitespace_provenance_maps_legacy_fragment(db):
    from xfagent.v2.structure import materialize_structure
    text='第一条  禁止遮挡\n  消火栓。\n\n第二条  应保持完整。'
    db.db.documents.insert_one({'_id':'doc','doc_id':'d','snapshot_id':'kb','full_text':text,'version_id':'d:v1','body_hash':digest(text.encode())})
    db.db.evidence.insert_one({'_id':'e','snapshot_id':'kb','doc_id':'d','evidence_id':'e','legacy_id':'e','article':'第一条','text':'第一条 禁止遮挡\n消火栓。'})
    result=materialize_structure(db,'kb');assert result['mapped_fragments']==1
    pos=db.db.evidence_locations.find_one({'_id':'kb:e'})['location']
    assert ''.join(text[pos['char_start']:pos['char_end']].split())=='第一条禁止遮挡消火栓。'
    assert pos['source_unit_ids']

def test_corrected_feedback_and_outbox_are_idempotent(db,monkeypatch):
    import xfagent.v2.api as api
    monkeypatch.setattr(api,'store',db)
    db.db.feedback.insert_one({'_id':'f','owner':'a','project_id':'default','text':'原反馈','category':'vision','candidate_id':None})
    actor=Actor(user_id='reviewer',role='reviewer',projects=['default'])
    request={'category':'retrieval','reason':'确认是检索遗漏','expected_version':1}
    first=api.correct_attribution('f',request,actor);second=api.correct_attribution('f',request,actor)
    assert first==second;assert db.db.outbox.count_documents({})==1
    assert db.db.feedback.find_one({'_id':'f'})['attribution_version']==2
    with pytest.raises(HTTPException):api.correct_attribution('f',{**request,'category':'generation'},actor)

def test_legal_claim_cannot_hide_as_information_request(db,state):
    state['conclusions'][0].update(kind='information_request',text='根据消防法，该设施不符合要求',evidence_ids=[])
    assert not verify(db,state)['passed']

def test_worker_handoff_resumes_human_checkpoint(db,state,monkeypatch):
    from xfagent.v2.worker import execute
    monkeypatch.setattr('xfagent.v2.graphs.Retrieval.search',lambda *a,**k:{'evidence':[],'warnings':[]})
    db.db.settings.insert_one({'_id':'active_snapshot','value':'kb'})
    actor=Actor(user_id='a',role='reviewer',projects=['default'])
    j=db.submit('inspection',state['request'],actor,'worker-handoff')
    execute(db,inspection_graph(db),db.claim(j['_id'],'first-worker'),'first-worker')
    j=db.db.jobs.find_one({'_id':j['_id']});assert j['status']=='awaiting_review'
    db.enqueue_resume(j,{'expected_revision':j['revision'],'action':'approve','comment':'transport test','conclusions':j['result']['report']['conclusions']},actor)
    execute(db,inspection_graph(db),db.claim(j['_id'],'second-worker'),'second-worker')
    j=db.db.jobs.find_one({'_id':j['_id']});assert j['status']=='complete';assert j['result']['report']['status']=='final'

def test_explicitly_empty_review_cannot_restore_deleted_claims(db,state,monkeypatch):
    import xfagent.v2.api as api
    from xfagent.v2.schema import Review
    monkeypatch.setattr(api,'store',db)
    db.db.jobs.insert_one({'_id':'run','owner':'a','project_id':'default','status':'awaiting_review','revision':1,
        'input':state['request'],'result':state,'idempotency_key':'empty-review'})
    with pytest.raises(HTTPException) as exc:api.review('run',Review(expected_revision=1,action='approve',conclusions=[]),Actor(user_id='a',role='reviewer',projects=['default']))
    assert exc.value.status_code==409
    assert db.db.outbox.count_documents({})==0

def test_expired_worker_cannot_overwrite_replacement_report(db,state):
    actor=Actor(user_id='a',role='reviewer',projects=['default'])
    job=db.submit('inspection',state['request'],actor,'fenced-report')
    db.claim(job['_id'],'replacement')
    assert db.finish(job['_id'],'expired',{'status':'complete'},report={'report':{'status':'wrong'}})==0
    assert db.db.reports.find_one({'_id':job['_id']}) is None
    assert db.finish(job['_id'],'replacement',{'status':'awaiting_review'},report={'report':{'status':'draft'}})==1
    assert db.db.reports.find_one({'_id':job['_id']})['report']['status']=='draft'
    assert db.db.jobs.find_one({'_id':job['_id']})['status']=='awaiting_review'

def test_annotation_submission_uses_idempotency_key(db,monkeypatch):
    import xfagent.v2.api as api
    from xfagent.v2.schema import InspectionInput
    monkeypatch.setattr(api,'store',db)
    actor=Actor(user_id='a',role='inspector',projects=['default'])
    body=InspectionInput(query='观察设施',facility='outdoor_hydrant',use_model=False)
    first=api.annotate(body,actor,'annotation-one');second=api.annotate(body,actor,'annotation-one')
    assert first['id']==second['id'];assert db.db.jobs.count_documents({})==1

def test_confirmed_critical_incident_immediately_rolls_back(db,monkeypatch):
    import xfagent.v2.api as api
    monkeypatch.setattr(api,'store',db)
    db.db.policies.insert_one({'_id':'incident-policy','state':'canary','version':1,'project_id':'default'})
    db.db.jobs.insert_one({'_id':'incident-run','owner':'a','project_id':'default','idempotency_key':'incident',
        'result':{'policy':{'experiment_id':'incident-policy','group':'treatment'}}})
    body={'code':'invalid_finalization','reason':'已确认定稿含错误判断'}
    with pytest.raises(HTTPException):api.report_incident('incident-run',body,Actor(user_id='a',role='inspector',projects=['default']))
    reviewer=Actor(user_id='reviewer',role='reviewer',projects=['default'])
    first=api.report_incident('incident-run',body,reviewer);second=api.report_incident('incident-run',body,reviewer)
    assert first==second;assert db.db.incidents.count_documents({})==1
    assert db.db.policies.find_one({'_id':'incident-policy'})['state']=='rolled_back'

def test_only_completed_jobs_count_toward_rollout_sample_gate(db,state):
    policies=Policies(db);state.update(policy={'policy_id':'baseline-v2','experiment_id':'exp','group':'control',
        'triggered':False,'spec':{'template':'standard'}},active_seconds=10)
    policies.record(state);assert policies.statistics('exp')['control']['n']==0
    db.db.jobs.insert_one({'_id':state['run_id'],'owner':'a','idempotency_key':'completion','status':'running','worker':'w'})
    db.finish(state['run_id'],'w',{'status':'complete'})
    assert policies.statistics('exp')['control']['n']==1

def test_mongo_reconciles_lost_redis_dispatch_without_double_scheduling(db,state):
    actor=Actor(user_id='a',role='inspector',projects=['default'])
    job=db.submit('inspection',state['request'],actor,'redis-loss')
    db.db.outbox.update_many({}, {'$set':{'sent':True}})
    db.db.jobs.update_one({'_id':job['_id']},{'$set':{'created_at':now()-timedelta(minutes=5)}})
    assert db.recover_dispatch()==1;assert db.recover_dispatch()==0
    assert db.db.outbox.count_documents({'sent':False})==1
    db.claim(job['_id'],'recovered-worker')
    db.db.jobs.update_one({'_id':job['_id']},{'$unset':{'dispatch_recovered_at':''}})
    assert db.recover_dispatch()==0
    db.db.jobs.update_one({'_id':job['_id']},{'$set':{'lease_until':now()-timedelta(seconds=1)}})
    assert db.recover_dispatch()==1
