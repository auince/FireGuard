import base64
import io
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from xfagent.practice.app import create_app
from xfagent.practice.contracts import Inspection
from xfagent.practice.harness import Harness
from xfagent.practice.vector import BasicVectorRAG, chunk


class RAG:
    def search(self, request, queries):
        return {'evidence': [{'evidence_id': 'e', 'text': '消防设施不得遮挡', 'document_title': '仿真工程夹具'}],
                'warnings': [], 'snapshot_id': 'fixture'}


class Model:
    name = 'injected-fixture-not-9b-inference'
    def complete(self, role, payload, image=None):
        if role == 'intent': return {'facility': 'indoor_hydrant'}
        if role == 'rewrite': return {'queries': ['室内消火栓遮挡']}
        if role == 'verify': return {'supported': True, 'issues': []}
        return {'hazards': [{'description': '可能被遮挡，需现场核查', 'suggestion': '移开障碍物并核查取用空间',
                             'evidence_ids': ['e']}], 'missing_information': []}


def test_question_photo_pipeline():
    im = Image.new('RGB', (8, 8)); output = io.BytesIO(); im.save(output, 'PNG')
    photo = 'data:image/png;base64,' + base64.b64encode(output.getvalue()).decode()
    response = TestClient(create_app(Harness(RAG(), Model()))).post('/api/inspect', json={'query': '检查消火栓', 'image': photo})
    assert response.status_code == 200
    report = response.json()
    assert report['evidence'][0]['evidence_id'] == 'e'
    assert report['answer']['hazards'][0]['suggestion']
    assert report['verification']['passed']


def test_forged_reference_fails():
    model = Model()
    original = model.complete
    def forged(role, payload, image=None):
        result = original(role, payload, image)
        if role == 'answer': result['hazards'][0]['evidence_ids'] = ['invented']
        return result
    model.complete = forged
    result = Harness(RAG(), model).execute(Inspection(query='检查消火栓').model_dump(mode='json'))
    assert not result['verification']['passed']


def test_chunk_overlap_and_vector_storage():
    client = SimpleNamespace(has_collection=lambda name: False, create_collection=lambda *a, **k: None,
                             upsert=lambda name, records: saved.extend(records), flush=lambda name: None)
    saved = []
    rag = BasicVectorRAG(client=client, embedding=lambda parts: [[1., 0.] for _ in parts])
    assert rag.ingest('设施应便于取用。' * 100, '仿真') > 1
    assert all(r['text'] and r['vector'] for r in saved)
    assert chunk('abcdefghij', size=6, overlap=2)[:2] == ['abcdef', 'efghij']


@pytest.mark.parametrize('query,image', [(' ', None), ('检查', 'data:image/png;base64,invalid')])
def test_invalid_input(query, image):
    with pytest.raises(ValueError): Inspection(query=query, image=image)
