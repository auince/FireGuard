import time
from types import SimpleNamespace

from xfagent.practice.memory import Memory, resolve_followup
from test_review import setup, submit


def test_sessions_are_owner_scoped_and_followups_link_reports(setup):
    client, headers, store, engine = setup
    identifier = submit(client, headers['i'])
    first = store.get(identifier)
    sid = first['session_id']
    assert client.get('/api/sessions/'+sid, headers=headers['other']).status_code == 404
    assert client.get('/api/sessions/'+sid, headers=headers['r']).status_code == 404
    assert client.post('/api/inspect', json={'query': '如何整改', 'session_id': sid}, headers=headers['other']).status_code == 404
    response = client.post('/api/inspect', json={'query': '这个怎么整改？', 'session_id': sid}, headers=headers['i'])
    assert response.status_code == 202
    second = store.get(response.json()['id'])
    assert second['session_id'] == sid and second['facility'] == 'indoor_hydrant'
    assert second['memory_context']['working']['report_id'] == identifier
    assert len(client.get('/api/sessions/'+sid, headers=headers['i']).json()['turns']) == 2
    assert len(second['trace']) == 5


def test_memory_ttl_budget_new_photo_and_fact_boundaries(setup):
    client, headers, store, engine = setup
    identifier = submit(client, headers['i'])
    sid = store.get(identifier)['session_id']
    actor = {'username': 'i', 'project_id': 'practice'}
    memory = Memory(store)
    request = {'query': '这个如何整改', 'session_id': sid, 'facility': 'auto', 'image': None}
    context = memory.context(request, actor)
    assert resolve_followup(request, context) == 'indoor_hydrant'
    assert set(context['working']) == {'previous_query','facility','report_id','authority'}
    assert len(__import__('json').dumps(context,ensure_ascii=False).encode()) <= memory.BUDGET
    assert memory.context(dict(request,image='new-photo'),actor)['working'] == {}
    assert resolve_followup(dict(request,query='检查灭火器'),context) is None
    assert resolve_followup(dict(request,query='今天天气'),context) is None
    store.cas(identifier,1,{'pending'},lambda r:dict(r,created_at=time.time()-memory.TTL-1),increment=False)
    assert memory.context(request,actor)['working'] == {}


def test_preferences_require_consent_and_cache_outage_degrades(setup):
    client, headers, store, engine = setup
    assert client.post('/api/memory/preferences',json={'answer_style':'concise','consent':False},headers=headers['i']).status_code == 422
    assert client.post('/api/memory/preferences',json={'answer_style':'detailed','consent':True},headers=headers['i']).json()['answer_style']=='detailed'
    assert client.get('/api/memory',headers=headers['other']).json()['preferences']=={}
    identifier=submit(client,headers['i'])
    actor={'username':'i','project_id':'practice'}
    cache=SimpleNamespace(get=lambda *args: None, setex=lambda *args:(_ for _ in ()).throw(ConnectionError()))
    context=Memory(store,cache).context({'session_id':store.get(identifier)['session_id']},actor)
    assert context['cache']=='redis_unavailable_sqlite_fallback'
    assert context['preferences']=={'answer_style':'detailed'}
    assert client.delete('/api/memory/preferences',headers=headers['i']).status_code == 200
    assert client.get('/api/memory',headers=headers['i']).json()['preferences']=={}


def test_previous_measurements_and_answers_never_enter_current_answer_prompt(setup):
    client, headers, store, engine = setup
    identifier=submit(client,headers['i']);sid=store.get(identifier)['session_id']
    store.cas(identifier,1,{'pending'},lambda r:dict(r,scene={'pressure_measurement':9.99}),increment=False)
    captured=[];original=engine.model.complete
    def capture(role,payload,*args,**kwargs):
        captured.append((role,payload));return original(role,payload,*args,**kwargs)
    engine.model.complete=capture
    response=client.post('/api/inspect',json={'query':'这个如何整改','session_id':sid},headers=headers['i'])
    assert response.status_code==202
    answer=[payload for role,payload in captured if role=='answer'][0]
    assert answer['scene']=={} and 'working' not in answer and 'memory_context' not in answer
    assert '9.99' not in str(answer)


def test_stale_cache_cannot_restore_rejected_report(setup):
    client, headers, store, engine = setup
    identifier=submit(client,headers['i']);sid=store.get(identifier)['session_id']
    actor={'username':'i','project_id':'practice'};items={}
    cache=SimpleNamespace(get=lambda k:items.get(k),setex=lambda k,ttl,value:items.update({k:value}))
    memory=Memory(store,cache)
    request={'session_id':sid,'query':'这个怎么整改','facility':'auto'}
    assert memory.context(request,actor)['cache']=='redis_refreshed'
    assert memory.context(request,actor)['cache']=='redis_hit'
    store.cas(identifier,1,{'pending'},lambda r:dict(r,status='rejected'))
    assert memory.context(request,actor)['working']=={}
    assert memory.key(sid,actor)!=memory.key(sid,dict(actor,project_id='other-project'))
