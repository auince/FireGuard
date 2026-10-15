import base64
import io
import json
from types import SimpleNamespace

import numpy as np
import pytest
from PIL import Image

from xfagent import cases
from xfagent.evidence_vision import VisionEvidence


def photo(color='red'):
    output = io.BytesIO()
    Image.new('RGB', (12, 12), color).save(output, 'PNG')
    return 'data:image/png;base64,' + base64.b64encode(output.getvalue()).decode()


def index(monkeypatch):
    records = [
        {'id': 'private', 'project_id': 'other', 'review_status': 'approved', 'description': 'private'},
        {'id': 'pending', 'visibility': 'shared', 'review_status': 'pending', 'description': 'pending'},
        {'id': 'test', 'visibility': 'shared', 'review_status': 'approved', 'split': 'test', 'description': 'held out'},
        {'id': 'good', 'visibility': 'shared', 'review_status': 'approved', 'description': 'visible condition',
         'facility': 'indoor_hydrant', 'synthetic': True, 'linked_evidence_ids': ['clause-id']},
        {'id': 'other', 'project_id': 'p', 'review_status': 'approved', 'description': 'another case', 'facility': 'fire_extinguisher'},
    ]
    vectors = np.array([[1., 0.], [1., 0.], [1., 0.], [.8, .6], [0., 1.]])
    monkeypatch.setattr(cases, 'load_index', lambda: (records, vectors, vectors, list(range(5))))
    monkeypatch.setattr(cases, 'encode_cases', lambda items, kind, **kw: np.array([[1., 0.] for _ in items]))
    return records


def test_four_cross_modal_routes_scope_and_review_filter_before_topk(monkeypatch):
    index(monkeypatch)
    result = cases.retrieve_cases('消火栓', photo(), project_id='p', facility='indoor_hydrant', k=1)
    assert result['routes'] == ['text_to_image', 'text_to_text', 'image_to_image', 'image_to_text']
    assert [c['id'] for c in result['cases']] == ['good']
    assert result['cases'][0]['usable_as_legal_evidence'] is False
    assert result['cases'][0]['linked_evidence_ids'] == ['clause-id']
    assert 'image' not in result['cases'][0]


def test_image_query_does_not_require_text(monkeypatch):
    index(monkeypatch)
    result = cases.retrieve_cases(image=photo(), project_id='p')
    assert result['cases'][0]['id'] == 'good'
    assert set(result['routes']) == {'image_to_image', 'image_to_text'}


def test_text_route_survives_image_encoder_outage(monkeypatch):
    index(monkeypatch)
    def encode(items, kind, **kw):
        if kind == 'image_data': raise TimeoutError('offline')
        return np.array([[1., 0.] for _ in items])
    monkeypatch.setattr(cases, 'encode_cases', encode)
    result = cases.retrieve_cases('question', photo(), project_id='p')
    assert result['cases'] and result['warnings'] == ['case_image_unavailable:TimeoutError']


def test_group_exclusion_and_duplicates_do_not_fill_results(monkeypatch):
    records = index(monkeypatch)
    records[3]['group_id'] = records[4]['group_id'] = 'same-source'
    assert len(cases.retrieve_cases('q', project_id='p')['cases']) == 1
    assert not cases.retrieve_cases('q', project_id='p', exclude_group_ids=['same-source'])['cases']
    assert not cases.permitted({'project_id': 'other', 'visibility': 'shared'}, 'p')


def test_exact_query_image_is_excluded(monkeypatch):
    import hashlib
    records = index(monkeypatch)
    records[3]['image_sha256'] = hashlib.sha256(cases.image_bytes(photo())).hexdigest()
    result = cases.retrieve_cases(image=photo(), project_id='p', facility='indoor_hydrant')
    assert result['cases'] == []


def test_region_views_are_bounded_and_invalid_boxes_are_not_cropped():
    assert len(cases.crop_views(photo(), [[0, 0, .5, .5], [.5, .5, 1, 1], [0, 0, 1, 1]])) <= 3
    assert len(cases.crop_views(photo(), [[.9, 0, .1, 1], [0, 0, float('nan'), 1]])) == 1
    with pytest.raises(ValueError): cases.crop_views('/private/photo.jpg', [])


def test_atomic_build_encoder_identity_and_integrity(tmp_path, monkeypatch):
    monkeypatch.setattr(cases, 'ROOT', tmp_path)
    monkeypatch.setattr(cases, 'encode_cases', lambda items, kind, **kw: np.array([[1., 0.] for _ in items]))
    path = tmp_path / 'photo.png'
    path.write_bytes(cases.image_bytes(photo()))
    source = tmp_path / 'source.jsonl'
    source.write_text(json.dumps({'id': 'a', 'image': str(path), 'description': 'observed facts',
        'visibility': 'shared', 'human_reviewed': True, 'regions': [[0, 0, .5, .5]]}))
    result = cases.build_cases(source)
    records, images, texts, owners = cases.load_index()
    assert result['indexed'] == 1 and len(images) == 2 and owners == [0, 0]
    assert records[0]['review_status'] == 'approved'
    assert cases.case_image('a', 'p').read_bytes() == path.read_bytes()
    assert cases.case_image('a', 'p').is_relative_to(tmp_path / 'data/cases')
    pointer = (tmp_path / 'data/cases/current.json').read_bytes()
    monkeypatch.setattr(cases, 'encode_cases', lambda *a, **kw: (_ for _ in ()).throw(TimeoutError()))
    with pytest.raises(TimeoutError): cases.build_cases(source)
    assert (tmp_path / 'data/cases/current.json').read_bytes() == pointer
    folder = tmp_path / 'data/cases' / result['generation']
    (folder / 'records.json').write_text('[]')
    with pytest.raises(ValueError, match='integrity'): cases.load_index()


def test_unknown_review_and_encoder_mismatch_are_not_silently_accepted(tmp_path, monkeypatch):
    assert not cases.reviewed({'human_reviewed': False})
    assert not cases.reviewed({'human_reviewed': True, 'review_status': 'rejected'})
    monkeypatch.setattr(cases.requests, 'post', lambda *a, **kw: SimpleNamespace(
        raise_for_status=lambda: None, json=lambda: {'vectors': [[1., 0.]], 'encoder_id': 'different'}))
    with pytest.raises(ValueError, match='encoder'): cases.encode_cases(['q'], 'text')


def test_adapter_sends_image_regions_and_retains_only_reviewed_scoped_references():
    payloads = []
    def post(url, json, **kw):
        payloads.append(json)
        return SimpleNamespace(raise_for_status=lambda: None, json=lambda: {'cases': [
            {'id': 'approved', 'description': 'reference', 'project_id': 'p', 'review_status': 'approved',
             'score': .5, 'linked_evidence_ids': ['e'], 'synthetic': True},
            {'id': 'rejected', 'description': 'no', 'project_id': 'p', 'review_status': 'rejected'}],
            'routes': ['image_to_text'], 'warnings': []})
    result = VisionEvidence(post=post).references({'query': 'q', 'image': photo(), 'project_id': 'p'},
        'indoor_hydrant', detections=[{'bboxNorm': [0, 0, .5, .5]}])
    assert payloads[0]['image'] == photo() and payloads[0]['regions'] == [[0, 0, .5, .5]]
    assert len(result['similar_cases']) == 1
    assert result['similar_cases'][0]['linked_evidence_ids'] == ['e']
    assert result['case_telemetry']['routes'] == ['image_to_text']
