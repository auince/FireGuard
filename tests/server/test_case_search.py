from test_durable_console import service, login
from xfagent import cases


def test_case_search_requires_project_access_and_returns_scoped_image_url(service, monkeypatch):
    _, client = service
    assert client.post('/api/cases/search', json={'query': 'q', 'project_id': 'default'}).status_code == 401
    login(client, 'inspector')
    assert client.post('/api/cases/search', json={'query': 'q', 'project_id': 'other'}).status_code == 403
    seen = {}
    def search(query, image, **kw):
        seen.update(query=query, image=image, **kw)
        return {'cases': [{'id': 'case1', 'description': 'reference'}], 'warnings': [], 'routes': ['text_to_image']}
    monkeypatch.setattr(cases, 'retrieve_cases', search)
    response = client.post('/api/cases/search', json={'query': '消火栓', 'project_id': 'default'})
    assert response.status_code == 200 and seen['project_id'] == 'default'
    assert response.json()['cases'][0]['image_url'] == '/api/cases/case1/image?project_id=default'
    assert client.get('/api/cases/case1/image?project_id=other').status_code == 403
    assert client.post('/api/cases/search', json={'query': 'q', 'project_id': 'default', 'facility': []}).status_code == 400


def test_case_image_not_found_or_revoked_is_not_served(service, monkeypatch):
    _, client = service
    login(client, 'inspector')
    monkeypatch.setattr(cases, 'case_image', lambda identifier, project: None)
    assert client.get('/api/cases/missing/image?project_id=default').status_code == 404
