"""Regression cases for the real governance paths; all inference is injected."""
import copy
import json
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from pathlib import Path
import pytest
import requests
from test_contract_cases import fixture_store, initial
from xfagent.v2.config import now
from xfagent.v2.model import complete
from xfagent.v2.graphs import safe_node, inspection_graph, LeaseLost
from xfagent.v2.verify import verify
from xfagent.v2.facts import fetch_evidence, eligible
from xfagent.v2.memory import MemoryContextBuilder
from xfagent.v2.retrieval import Retrieval
from xfagent.v2.model_routes import resolve, manifest
from xfagent.v2.intent_adapter import parse_response
from xfagent.v2.store import digest

ALL_CASES = [json.loads(line) for line in Path('benchmarks/coverage_v2/gap_cases.jsonl').read_text().splitlines()]

CASES=[case for case in ALL_CASES if case['operation']!='version_metadata']

class Response:
    def __init__(self, value):self.value=value
    def raise_for_status(self):pass
    def json(self):return self.value

def transport(monkeypatch, completion=None):
    import xfagent.v2.model as model
    sent=[]
    def post(url, **kwargs):
        if url.endswith('/tokenize'):return Response({'count':10})
        sent.append((url,kwargs['json']))
        if completion:return completion(url,kwargs)
        return Response({'choices':[{'message':{'content':'{"queries":["q"]}'}}], 'usage':{'total_tokens':7}})
    monkeypatch.setattr(model.requests,'post',post)
    return sent

@pytest.mark.parametrize('case',CASES,ids=[case['id'] for case in CASES])
def test_gap(case, fixture_store, monkeypatch, tmp_path):
    s=fixture_store;state=initial(s);p=case['params'];expected=case['expected'];operation=case['operation']
    if operation=='measurement':
        state['conclusions'][0]['text']=p['text'];state['request']['scene']=p.get('scene',{})
        for field in ['kind','sufficiency']:
            if field in p:state['conclusions'][0][field]=p[field]
        result=verify(s,state)
        assert result['passed']==expected['passed'],result
        if expected.get('error_code'):assert expected['error_code'] in {x['code'] for x in result['errors']}
    elif operation=='condition':
        s.db.documents.update_one({'_id':'d'},{'$set':{'conditions':p['document']}})
        s.db.evidence.update_one({'_id':'e'},{'$set':{'conditions':p.get('clause',{})}})
        state['request']['scene']=p['scene'];state['evidence']=[fetch_evidence(s,'kb','e','2026-10-05','四川')]
        assert verify(s,state)['passed']==expected['passed']
    elif operation=='lifecycle':
        doc=s.db.documents.find_one({'_id':'d'});doc.update(p)
        assert eligible(doc,p.get('as_of','2026-10-05'),'四川')==expected['eligible']
    elif operation=='intent_collision':
        import xfagent.v2.graphs as module
        state['request'].update(query='室内消火栓和灭火器同时检查',facility='auto',use_model=True)
        called=[]
        def classify(x,*a,**k):
            called.append(k.get('role'));x['calls']=x.get('calls',0)+1
            return {'facility':'unknown'}
        monkeypatch.setattr(module,'complete',classify)
        result=inspection_graph(s,checkpointer=False).nodes['intent'].bound.invoke(state)
        assert result['facility']=='unknown' and called==['intent'] and result['calls']==1
    elif operation=='lease':
        s.db.jobs.insert_one({'_id':state['run_id'],'status':'running','worker':'same',
            'lease_until':now()-timedelta(seconds=1),'owner':'a','idempotency_key':'expired'})
        state['execution_worker']='same'
        if p.get('finish'):
            assert not s.finish(state['run_id'],'same',{'status':'complete'},report={'report':'forbidden'})
            assert not s.db.reports.find_one({'_id':state['run_id']})
        else:
            ran=[]
            with pytest.raises(LeaseLost):safe_node(s,'draft',lambda x:ran.append(True))(state)
            assert not ran
    elif operation=='cached_restart':
        sent=transport(monkeypatch);saved=copy.deepcopy(state)
        def fn(x):
            obj=complete(x,'test',{},role='rewrite')
            if p.get('crash') and len(sent)==1 and not x.get('warnings'):raise SystemExit('after durable response, before graph checkpoint')
            return {'queries':obj['queries']}
        if p.get('crash'):
            with pytest.raises(SystemExit):safe_node(s,'rewrite',fn)(copy.deepcopy(saved))
        else:safe_node(s,'rewrite',fn)(copy.deepcopy(saved))
        result=safe_node(s,'rewrite',fn)(copy.deepcopy(saved))
        assert result['queries']==['q'] and len(sent)==1 and result['calls']==1
        assert result['usage']['total_tokens']==7
    elif operation=='failed_restart':
        def failure(url,kwargs):raise requests.Timeout('delivery may have reached server')
        sent=transport(monkeypatch,failure)
        fn=lambda x:{'queries':complete(x,'test',{},role='rewrite')['queries']}
        safe_node(s,'rewrite',fn)(copy.deepcopy(state))
        result=safe_node(s,'rewrite',fn)(copy.deepcopy(state))
        assert len(sent)==1 and result['exhausted'] and result['calls']==1
    elif operation=='concurrent_quota':
        sent=transport(monkeypatch)
        def run(i):return safe_node(s,'draft'+str(i),lambda x:complete(x,'test',{},role='answer'))(copy.deepcopy(state))
        with ThreadPoolExecutor(max_workers=4) as executor:results=list(executor.map(run,range(20)))
        assert len(sent)==16 and s.db.model_budgets.find_one({'_id':state['run_id']})['calls']==16
        assert sum(x.get('exhausted',False) for x in results)==4
    elif operation=='route':
        sent=transport(monkeypatch)
        monkeypatch.setenv('XF_REWRITE_MODEL_URL','http://fixture.invalid:1/v1')
        monkeypatch.setenv('XF_REWRITE_MODEL_NAME','fixture-rewriter')
        complete(state,'test',{},role='rewrite')
        assert sent[0][0]=='http://fixture.invalid:1/v1/chat/completions' and sent[0][1]['model']=='fixture-rewriter'
        if p.get('isolation'):assert resolve('answer')['name']!='fixture-rewriter'
    elif operation=='kev_probability':
        route=resolve('intent');route.update(min_probability=.75,min_margin=.15)
        obj={'answers':{'facility':{'choice':p.get('choice','indoor_hydrant'),'probabilities':p['probabilities']}}}
        if expected.get('invalid'):
            with pytest.raises(ValueError):parse_response(obj,route)
        else:assert parse_response(obj,route)['facility']==expected['facility']
    elif operation=='kev_wire':
        monkeypatch.setenv('XF_INTENT_BACKEND','systemone');monkeypatch.setenv('XF_INTENT_MODEL_NAME','kev-latest')
        monkeypatch.setenv('XF_INTENT_MODEL_URL','http://fixture.invalid:2/v1')
        def completion(url,kwargs):return Response({'answers':{'facility':{'choice':'indoor_hydrant','probabilities':{
            'indoor_hydrant':.9,'outdoor_hydrant':.04,'fire_extinguisher':.03,'unknown':.03}}}})
        sent=transport(monkeypatch,completion)
        result=safe_node(s,'intent',lambda x:complete(x,'test',{'query':'消防箱'},role='intent'))(state)
        assert result['facility']=='indoor_hydrant' and sent[0][0].endswith('/v1/systemone')
        assert sent[0][1]['questions']['facility']['type']=='choice' and result['calls']==1
    elif operation=='finalize':
        import xfagent.v2.graphs as graphs
        state['request']['use_model']=p.get('use_model',True)
        state['report']={'status':'draft','verification':{'passed':True,'semantic_review':'model_supported'}}
        state['review']={'action':'approve','reviewer':'r','conclusions':copy.deepcopy(state['conclusions'])}
        state['review']['conclusions'][0]['text']='修改后的结论，应核查清理。'
        called=[]
        def check(x,*a,**k):
            called.append(k.get('role'))
            if p.get('outage'):raise requests.Timeout('offline')
            return {'supported':p.get('supported',True),'issues':[]}
        monkeypatch.setattr(graphs,'complete',check)
        result=inspection_graph(s,checkpointer=False).nodes['finalize'].bound.invoke(state)
        assert (result['report']['status']=='final')==expected['final']
        assert result['report']['conclusions'][0]['text']==state['review']['conclusions'][0]['text']
        assert called==(['verify'] if p.get('use_model',True) else [])
    elif operation=='memory_budget':
        memory=MemoryContextBuilder(s)
        class Redis:
            def get(self,key):return json.dumps({'last_query':'旧消息'*500})
        memory.redis=Redis()
        result=memory.build('a','default','session','kb','2026-10-05','四川',budget=100)
        assert not result['working'] and result['budget']['token_upper_bound']<=100
        assert 'working_memory_omitted_token_budget' in result['warnings']
    elif operation=='memory_warning':
        monkeypatch.setattr(MemoryContextBuilder,'build',lambda *a,**k:{'warnings':['working_memory_unavailable']})
        result=inspection_graph(s,checkpointer=False).nodes['context'].bound.invoke(state)
        assert 'working_memory_unavailable' in result['warnings']
    elif operation=='retrieval_fragments':
        first=s.db.evidence.find_one({'_id':'e'});second={**first,'_id':'e2','evidence_id':'e2','legacy_id':'e2',
            'text':'测试夹具：保持设施完整。','article':'第一条'}
        second['quote_hash']=digest(second['text'].encode());s.db.evidence.insert_one(second)
        result=Retrieval(s).search(['设施'],'kb','2026-10-05',mode='bm25')
        assert {e['evidence_id'] for e in result['evidence']}=={'e','e2'}
    elif operation=='rerank_queries':
        import xfagent.v2.retrieval as module
        seen=[]
        monkeypatch.setattr(module,'embed',lambda *a,**k:(_ for _ in ()).throw(requests.Timeout('embedding offline')))
        def post(url,**kwargs):seen.append(kwargs['json']['query']);return Response({'scores':[1.]})
        monkeypatch.setattr(module.requests,'post',post)
        result=Retrieval(s).search(['遮挡','完整'],'kb','2026-10-05',mode='rerank')
        assert seen==['遮挡\n完整'] and result['evidence']
    elif operation=='feedback_restart':
        from xfagent.v2.feedback import feedback_graph
        f={'_id':'f','owner':'a','signal':'dislike','category':'retrieval','text':'遗漏条款'}
        s.db.feedback.insert_one(f)
        source={'_id':'source','input':state['request'],'project_id':'default','owner':'a'}
        def completion(url,kwargs):return Response({'choices':[{'message':{'content':'{"trigger_terms":["设施"],"expand_terms":["遮挡"],"parent_expand":true}'}}]})
        sent=transport(monkeypatch,completion)
        saved={'feedback':f,'source':source,'calls':0,'active_seconds':0}
        a=feedback_graph(s).invoke(copy.deepcopy(saved));b=feedback_graph(s).invoke(copy.deepcopy(saved))
        assert a['candidate_id']==b['candidate_id'] and len(sent)==1
        assert s.db.policies.count_documents({'_id':a['candidate_id']})==1
    elif operation=='snapshot_metadata':
        import xfagent.v2.facts as facts
        raw=tmp_path/'raw.txt';raw.write_text('合成夹具：不得遮挡设施。')
        (tmp_path/'data/legal').mkdir(parents=True)
        doc={'id':'fixture','status':'source_verified','kind':'law','raw_path':'raw.txt','markdown_path':'raw.txt',
             'sha256':digest(raw.read_bytes()),'title':'合成夹具','url':'https://fixture.invalid','conditions':{}}
        path=tmp_path/'data/legal/manifest.json';path.write_text(json.dumps([doc]));monkeypatch.setattr(facts,'ROOT',tmp_path)
        first=facts.prepare_snapshot(s)
        doc['clause_conditions']={'第一条':{'building_height':{'gte':24}}};path.write_text(json.dumps([doc]))
        second=facts.prepare_snapshot(s)
        assert first!=second and s.active_snapshot()=='kb'
    elif operation=='canonical_integrity':
        body='测试夹具：不得遮挡该设施。'
        s.db.documents.update_one({'_id':'d'},{'$set':{'full_text':body,'body_hash':digest(body.encode())}})
        assert fetch_evidence(s,'kb','e','2026-10-05','四川')
        if p['mutation']=='quote':
            text='篡改夹具：允许遮挡该设施。'
            s.db.evidence.update_one({'_id':'e'},{'$set':{'text':text,'quote_hash':digest(text.encode())}})
        elif p['mutation']=='body':s.db.documents.update_one({'_id':'d'},{'$set':{'full_text':'篡改正文'}})
        else:s.db.evidence.update_one({'_id':'e'},{'$set':{'parent_text':'伪造父条款'}})
        assert fetch_evidence(s,'kb','e','2026-10-05','四川') is None
    elif operation=='manifest_gate':
        from xfagent.v2.policy import Policies
        from xfagent.v2.replay_protocol import execution_hash, PROTOCOL
        from xfagent.v2.schema import Strategy, Actor
        spec=Strategy(name='fixture').model_dump()
        s.db.policies.insert_one({'_id':'trial','project_id':'default','spec':spec,'version':1,'state':'draft'})
        s.db.settings.insert_one({'_id':'generator_fingerprint','value':'weights'})
        s.db.evaluations.insert_one({'_id':'eval','policy_id':'trial','policy_hash':digest(spec),'status':'passed',
            'protocol':PROTOCOL,'execution_hash':execution_hash(),'model_fingerprint':'weights','model_routes_hash':digest(manifest())})
        if p.get('change'):monkeypatch.setenv('XF_VERIFY_MODEL_REVISION','new-weights')
        if expected['allowed']:Policies(s).publish('trial',__import__('xfagent.v2.schema',fromlist=['Actor']).Actor(user_id='a',role='admin',projects=['default']),5,1)
        else:
            with pytest.raises(ValueError):Policies(s).publish('trial',Actor(user_id='a',role='admin',projects=['default']),5,1)
    else:raise AssertionError('unhandled operation '+operation)
