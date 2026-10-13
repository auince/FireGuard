import pytest
from fastapi.testclient import TestClient

from xfagent.practice.app import create_app
from xfagent.practice.harness import Harness
from xfagent.practice.storage import Storage
from test_prototype import Model, RAG


@pytest.fixture
def setup(tmp_path):
    storage = Storage(tmp_path / 'state.sqlite')
    for name, role in [('i', 'inspector'), ('other', 'inspector'), ('r', 'reviewer')]:
        storage.add_user(name, 'test-password', role)
    engine = Harness(RAG(), Model())
    client = TestClient(create_app(engine, storage))
    headers = {}
    for name in ['i', 'other', 'r']:
        token = client.post('/api/login', json={'username': name, 'password': 'test-password'}).json()['token']
        headers[name] = {'Authorization': 'Bearer ' + token}
    return client, headers, storage, engine


def submit(client, headers):
    response = client.post('/api/inspect', json={'query': '检查室内消火栓'}, headers=headers)
    assert response.status_code == 202
    return response.json()['id']


def test_review_roles_cas_and_final_recheck(setup):
    client, headers, store, engine = setup
    identifier = submit(client, headers['i'])
    assert client.get('/api/reports/' + identifier, headers=headers['other']).status_code == 404
    body = {'expected_revision': 1, 'action': 'approve'}
    assert client.post(f'/api/reports/{identifier}/review', json=body, headers=headers['i']).status_code == 403
    response = client.post(f'/api/reports/{identifier}/review', json=body, headers=headers['r'])
    assert response.status_code == 200 and response.json()['status'] == 'approved'
    assert client.post(f'/api/reports/{identifier}/review', json=body, headers=headers['r']).status_code == 409


def test_return_resubmit_and_evidence_revocation(setup):
    client, headers, store, engine = setup
    identifier = submit(client, headers['i'])
    path = f'/api/reports/{identifier}'
    assert client.post(path + '/review', json={'expected_revision': 1, 'action': 'return', 'comment': '补充照片'}, headers=headers['r']).json()['status'] == 'returned'
    response = client.post(path + '/revise', json={'expected_revision': 2, 'input': {'query': '补充室内消火栓检查'}}, headers=headers['i'])
    assert response.status_code == 202
    report = client.get(path, headers=headers['i']).json()
    assert report['revision'] == 3 and report['status'] == 'pending' and len(report['reviews']) == 1
    engine.rag.validate = lambda *args: ['source_mismatch:revoked']
    response = client.post(path + '/review', json={'expected_revision': 3, 'action': 'approve'}, headers=headers['r'])
    assert response.status_code == 422
    assert store.get(identifier)['status'] == 'pending'


def test_login_logout_and_failed_worker_visible(setup):
    client, headers, store, engine = setup
    assert client.post('/api/inspect', json={'query': '检查'}).status_code == 401
    assert client.post('/api/login', json={'username': 'i', 'password': 'wrong'}).status_code == 401
    assert client.post('/api/logout', headers=headers['i']).status_code == 200
    assert client.get('/api/reports', headers=headers['i']).status_code == 401
    engine.model.complete = lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError('fixture outage'))
    identifier = submit(client, headers['other'])
    assert store.get(identifier)['status'] == 'failed'


def test_knowledge_requires_login_and_missing_documents_are_explicit(setup):
    client, headers, store, engine = setup
    assert client.get('/api/knowledge/documents').status_code == 401
    engine.rag.documents = lambda day, region: {'snapshot_id': 'fixture', 'documents': []}
    engine.rag.document = lambda *args: None
    assert client.get('/api/knowledge/documents', headers=headers['i']).json()['snapshot_id'] == 'fixture'
    assert client.get('/api/knowledge/documents/missing', headers=headers['i']).status_code == 404
    assert client.get('/api/knowledge/search?q=消火栓', headers=headers['i']).status_code == 200
    assert client.get('/api/not-a-route', headers=headers['i']).status_code == 404
