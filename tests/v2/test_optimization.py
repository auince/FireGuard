import copy
import numpy as np
import pytest
from test_governance import db,state
from xfagent.v2.verify import verify
from xfagent.v2.facts import fetch_evidence
from xfagent.v2.graphs import verification_route,safe_node
from xfagent.v2.retrieval import Retrieval
from xfagent.v2.observability import TraceAggregator
from xfagent.v2.replay_protocol import evaluate_pairs,retrieval_metrics
from xfagent.v2.query_planning import multi_queries

@pytest.mark.parametrize('field,value',[('text','伪造正文'),('quote_hash','bad'),('version_id','wrong'),('source_url','https://fake.invalid'),('location',{'article':'fake'})])
def test_reported_evidence_must_equal_canonical(db,state,field,value):
    state['evidence'][0][field]=value
    result=verify(db,state)
    assert not result['passed']
    assert any(e['code']=='source_mismatch' and field in e.get('fields',[]) for e in result['errors'])

def test_version_mismatch_between_document_and_evidence_is_rejected(db,state):
    db.db.documents.update_one({'_id':'d'},{'$set':{'version_id':'v2'}})
    assert fetch_evidence(db,'kb','e','2026-10-03','四川') is None

def test_duplicate_claim_ids_rejected(db,state):
    state['conclusions']*=2
    assert any(e['code']=='duplicate_or_empty_claim_id' for e in verify(db,state)['errors'])

def test_failure_routing_bounds_and_clarification():
    base={'verification':{'passed':False,'errors':[{'code':'missing_evidence'}]},'evidence':[{'id':'e'}]}
    assert verification_route(base)=='rewrite'
    assert verification_route({**base,'retrieval_rounds':2})=='repair'
    assert verification_route({**base,'retrieval_rounds':2,'rewrites':2})=='review_ready'
    assert verification_route({**base,'verification':{'errors':[{'code':'unknown_applicability'}]}})=='review_ready'

def test_verifier_exception_cannot_preserve_old_success(db,state):
    state['verification']={'passed':True}
    result=safe_node(db,'verify',lambda s:(_ for _ in ()).throw(RuntimeError('offline')))(state)
    assert result['verification']['passed'] is False
    assert result['verification']['semantic_review']=='unavailable'

def test_trace_deltas_do_not_repeat_previous_warning_or_calls(db,state):
    state.update(calls=4,warnings=['old issue'])
    def node(s):s['calls']+=1;return {}
    result=safe_node(db,'draft',node)(state);event=result['trace'][-1]
    assert event['calls_delta']==1 and event['warnings']==[] and event['outcome']=='ok'
    stats=TraceAggregator.summarize([event,{'node':'draft','seconds':10,'calls':12,'warnings':['legacy']}])['draft']
    assert stats['count']==2 and stats['outcome_known_count']==1 and stats['model_calls']==1

def test_batch_embedding_and_cache_have_namespace_and_ttl(db,monkeypatch):
    import xfagent.v2.retrieval as m
    calls=[]
    def fake(texts,timeout):calls.append(list(texts));return np.array([[1.,0.] for _ in texts])
    monkeypatch.setattr(m,'embed',fake);r=Retrieval(db)
    _,stats=r.query_vectors(['a','b','a'],'kb',10)
    assert calls==[['a','b']] and stats['misses']==2
    _,stats=r.query_vectors(['b','a'],'kb',10);assert stats['hits']==2 and len(calls)==1
    r.query_vectors(['a'],'kb-new',10);assert len(calls)==2
    for key,(at,value) in list(r.embeddings.items()):r.embeddings[key]=(at-301,value)
    r.query_vectors(['a'],'kb',10);assert len(calls)==3

def test_batch_search_preserves_query_order_and_refreshes_eligibility(db,state,monkeypatch):
    import xfagent.v2.retrieval as m
    monkeypatch.setattr(m,'embed',lambda texts,timeout:np.array([[1.,0.] for _ in texts]))
    class Vector:
        def search(self,*a,**k):return [[{'id':'e'}] for _ in k['data']]
    r=Retrieval(db);r.vector=Vector()
    answer=r.search(['消火栓','遮挡','消火栓'],'kb','2026-10-03',mode='rrf')
    assert answer['queries']==['消火栓','遮挡'] and answer['telemetry']['embedding_cache']['http_batches']==1
    db.db.documents.update_one({'_id':'d'},{'$set':{'effective_until':'2026-10-03'}})
    assert not r.search(['消火栓'],'kb','2026-10-03',mode='rrf')['evidence']

def test_hyde_is_embedding_hint_not_evidence(db,state,monkeypatch):
    import xfagent.v2.retrieval as m
    seen=[]
    def emb(texts,timeout):seen.extend(texts);return np.array([[1.,0.] for _ in texts])
    monkeypatch.setattr(m,'embed',emb)
    class Vector:
        def search(self,*a,**k):return [[{'id':'e'}] for _ in k['data']]
    r=Retrieval(db);r.vector=Vector()
    answer=r.search(['用户原话'],'kb','2026-10-03',mode='hyde',dense_hint='假设内容')
    assert seen==['假设内容'];assert answer['queries']==['用户原话']
    assert answer['evidence'][0]['text']==state['evidence'][0]['text']
    assert '假设内容' not in str(answer['evidence'])

def test_multi_query_planner_does_not_reuse_other_facility_or_invent_pressure():
    queries=multi_queries('这个消防箱怎么改？','indoor_hydrant',{}, {'facility':'fire_extinguisher','last_query':'压力0.25MPa'},['q1','q2','q3'])
    assert len(queries)==3 and '消火栓箱' in queries[0]
    assert '0.25' not in str(queries)
    assert '额定压力' not in str(multi_queries('压力问题','indoor_hydrant',{}, {},[]))

def pairs():
    good={'elapsed':10,'calls':2,'hard_errors':[],'draft_present':True,'semantic':'model_supported','policy':{'triggered':True}}
    return [{'source_run_id':str(i),'control':copy.deepcopy(good),'treatment':copy.deepcopy(good)} for i in range(3)]

def test_paired_regression_not_hidden_by_equal_aggregate_defects():
    rows=pairs();rows[0]['control']['hard_errors']=[{'code':'missing_evidence'}]
    rows[1]['treatment']['hard_errors']=[{'code':'missing_evidence'}]
    result=evaluate_pairs(rows)
    assert result['gates']['defect_count_not_increased'] and not result['passed']
    assert result['regressions'][0]['source_run_id']=='1'

def test_replay_missing_gold_is_unknown_and_latency_is_gated():
    rows=pairs();result=evaluate_pairs(rows)
    assert result['passed'] and result['metrics']['treatment']['retrieval'] is None
    assert retrieval_metrics([],None) is None
    assert retrieval_metrics(['x','b'],['a','b'])['recall@5']==.5
    rows[0]['treatment']['elapsed']=30
    assert not evaluate_pairs(rows)['gates']['latency_within_20_percent']

def test_replay_requires_actual_trigger_and_successful_drafts():
    rows=pairs()
    for row in rows:row['treatment']['policy']['triggered']=False
    assert not evaluate_pairs(rows)['passed']
    rows=pairs();rows[0]['treatment']['execution_error']='timeout'
    assert not evaluate_pairs(rows)['passed']

def test_observability_requires_admin_and_project_access(db,monkeypatch):
    from fastapi import HTTPException
    from xfagent.v2.schema import Actor
    import xfagent.v2.api as api
    monkeypatch.setattr(api,'store',db)
    with pytest.raises(HTTPException):api.observability('default',Actor(user_id='a',role='inspector',projects=['default']))
    with pytest.raises(HTTPException):api.observability('other',Actor(user_id='a',role='admin',projects=['default']))
    assert api.observability('default',Actor(user_id='a',role='admin',projects=['default']))['event_count']==0

def test_pre_upgrade_idempotency_accepts_only_equivalent_new_defaults(db,state):
    from xfagent.v2.schema import Actor
    actor=Actor(user_id='a',role='inspector',projects=['default'])
    old=db.submit('inspection',state['request'],actor,'old-key')
    retry=db.submit('inspection',{**state['request'],'query_strategy':'standard'},actor,'old-key')
    assert retry['_id']==old['_id']
    with pytest.raises(ValueError):db.submit('inspection',{**state['request'],'query_strategy':'multi'},actor,'old-key')
