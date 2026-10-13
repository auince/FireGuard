import hashlib
import secrets
import uuid

import pytest
from fastapi.testclient import TestClient

from xfagent.server.app import create_app
from xfagent.v2 import graphs
from xfagent.v2.config import now
from xfagent.v2.graphs import inspection_graph
from xfagent.v2.policy import Policies
from xfagent.v2.schema import Actor, Review
from xfagent.v2.store import Store
from xfagent.v2.worker import execute


@pytest.fixture
def service(monkeypatch):
    name='xfagent_test_console_'+uuid.uuid4().hex
    store=Store(name=name)
    monkeypatch.setenv('XF_V2_JWT_SECRET', secrets.token_hex(32))
    monkeypatch.setenv('XF_COOKIE_SECURE','false')
    monkeypatch.setenv('XF_ALLOWED_HOSTS','testserver')
    store.setup();Policies(store).seed()
    store.db.settings.insert_one({'_id':'active_snapshot','value':'kb-test'})
    for role in ['inspector','reviewer']:
        salt=secrets.token_bytes(16)
        store.db.users.insert_one({'_id':role,'salt':salt.hex(),'password_hash':hashlib.scrypt(b'test-only',salt=salt,n=16384,r=8,p=1).hex(),
                                   'role':role,'projects':['default']})
    monkeypatch.setattr(graphs.Retrieval,'search',lambda *a,**k:{'evidence':[],'queries':['q'],'warnings':[]})
    with TestClient(create_app(store)) as client:
        yield store,client
    store.client.drop_database(name)


def login(client,role):
    reply=client.post('/api/login',json={'username':role,'password':'test-only'})
    assert reply.status_code==200,reply.text
    assert 'HttpOnly' in reply.headers['set-cookie']
    return client.cookies.get('xf_session')


@pytest.mark.parametrize("governed",[False,True])
def test_edit_confirm_restart_and_cas(service,governed):
    store,client=service
    login(client,'inspector')
    body={'query':'检查室内消火栓','facility':'indoor_hydrant','project_id':'default','use_model':False}
    response=client.post('/api/inspect',json=body,headers={'Idempotency-Key':'one'})
    assert response.status_code==202,response.text
    identifier=response.json()['id']
    assert client.post('/api/inspect',json=body,headers={'Idempotency-Key':'one'}).json()['id']==identifier
    job=store.claim(identifier,'worker-one')
    execute(store,inspection_graph(store,governed=governed),job,'worker-one')
    assert store.db.checkpoints.count_documents({'thread_id':identifier})>0
    report=client.get('/api/reports/'+identifier).json()
    assert report['status']=='pending'
    decision={'expected_revision':1,'action':'approve','comment':'已核实','conclusions':[
        {'claim_id':'c1','text':'已确认现场净宽为1.2米，需进一步核查适用条款。','kind':'information_request','recommendation':'补齐测量记录'}],
        'confirmed_scene':{'measured_width':{'value':1.2,'unit':'m','confirmed':True}}}
    assert client.post('/api/reports/'+identifier+'/review',json=decision).status_code==403
    old_token=login(client,'reviewer')
    assert client.post('/api/reports/'+identifier+'/review',json=decision).status_code==202
    assert client.post('/api/reports/'+identifier+'/review',json=decision).status_code in [400,409]
    # Entirely new graph object and worker claim: resume persistent Mongo checkpoint.
    resumed=store.claim(identifier,'worker-two')
    execute(store,inspection_graph(store,governed=governed),resumed,'worker-two')
    finished=client.get('/api/reports/'+identifier).json()
    assert finished['status']=='approved',finished
    assert finished['conclusions'][0]['text']==decision['conclusions'][0]['text']
    assert finished['scene']['measured_width']['confirmed'] is True
    assert len(finished['reviews'])==1
    assert store.db.outbox.count_documents({'job_id':identifier})==2
    assert client.get('/api/me').json()['actor']['role']=='reviewer'
    client.post('/api/logout')
    assert client.get('/api/me',headers={'Authorization':'Bearer '+old_token}).status_code==401


def test_permissions_origin_and_typed_review(service):
    store,client=service
    login(client,'inspector')
    assert client.post('/api/inspect',json={'query':'q','project_id':'other'}).status_code==403
    assert client.post('/api/memory/preferences',json={'answer_style':'concise','consent':True},headers={'Origin':'https://other.invalid'}).status_code==403
    store.db.users.update_one({'_id':'inspector'},{'$set':{'disabled':True}})
    assert client.get('/api/me').status_code==401
    with pytest.raises(ValueError):
        Review(expected_revision=1,action='approve',confirmed_scene={'measured_width':{'value':1,'unit':'m','confirmed':False}})
    with pytest.raises(ValueError):
        Review(expected_revision=1,action='approve',conclusions=[{'claim_id':'x','text':'x','kind':'invented'}])


def test_governed_dag_and_bounded_repair(service,monkeypatch):
    store,_=service
    monkeypatch.setattr(graphs,'verify',lambda *a,**k:{'passed':False,'errors':[{'code':'injected_generation_error'}],'missing_fields':[]})
    graph=inspection_graph(store,governed=True)
    edges={(e.source,e.target) for e in graph.get_graph().edges}
    chain=['Intent','Rewrite','Retrieval','Answer','Verify']
    assert all(pair in edges for pair in zip(chain,chain[1:]))
    initial={'run_id':'bounded','owner':'inspector','snapshot_id':'kb-test','calls':0,'trace':[],'warnings':[],
             'request':{'project_id':'default','session_id':'bounded','query':'检查消火栓','scene':{},'facility':'indoor_hydrant',
                        'as_of':'2026-10-13','jurisdiction':'四川','mode':'inspection','use_model':False}}
    result=graph.invoke(initial,{'configurable':{'thread_id':'bounded'},'recursion_limit':70})
    assert result['__interrupt__']
    assert result['rewrites']==2
    assert sum(t['node']=='repair' for t in result['trace'])==2
    assert result['report']['execution_version']=='8.0'


def test_cancel_fences_running_worker(service):
    from xfagent.v2.graphs import require_lease,LeaseLost
    store,client=service
    login(client,'inspector')
    identifier=client.post('/api/inspect',json={'query':'q','project_id':'default','use_model':False}).json()['id']
    store.claim(identifier,'worker')
    assert client.post('/api/jobs/'+identifier+'/cancel',json={'expected_revision':1}).status_code==200
    with pytest.raises(LeaseLost):require_lease(store,{'run_id':identifier,'execution_worker':'worker'})
    assert not store.finish(identifier,'worker',{'status':'complete'})
    assert client.get('/api/reports/'+identifier).json()['status']=='cancelled'
