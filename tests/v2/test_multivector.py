"""Regressions for independent title/body recall and immutable index migration."""
from types import SimpleNamespace
import numpy as np
import pytest

from test_governance import db, state
from xfagent.ingest import structure
from xfagent.v2.retrieval import Retrieval, index_snapshot


def test_complete_heading_path_survives_sibling_and_document_headings():
    source = '# 规范\n## 第二章 设施\n### 第一节 消火栓\n#### 维护\n第一条 应完整。\n### 第二节 灭火器\n第二条 应完整。'
    parents, children = structure(source, '规范', 'd')
    one = next(c for c in children if c['article'] == '第一条')
    two = next(c for c in children if c['article'] == '第二条')
    assert one['heading_path'] == ['规范', '第二章 设施', '第一节 消火栓', '维护']
    assert two['heading_path'] == ['规范', '第二章 设施', '第二节 灭火器']
    assert '第一节' not in two['title']
    assert len(one['ancestor_ids']) == 4
    assert one['text'] == '第一条 应完整。'
    assert any(p['id'] == one['parent_id'] for p in parents)
    _, plain = structure('第一章 设施\n第一节 消火栓\n第一条 保持完整。', '规范', 'd')
    assert plain[-1]['heading_path'] == ['规范', '第一章 设施', '第一节 消火栓']


def dual(db, monkeypatch):
    import xfagent.v2.retrieval as module
    db.db.snapshots.insert_one({'_id': 'kb', 'index_schema': 'title-body-v1', 'collection': 'physical-dual'})
    monkeypatch.setattr(module, 'embed', lambda texts, timeout: np.array([[1., 0.] for _ in texts]))
    return Retrieval(db)


def test_title_only_hit_is_refilled_and_revocation_still_wins(db, state, monkeypatch):
    retriever = dual(db, monkeypatch)
    calls = []
    class Vector:
        def search(self, name, **options):
            calls.append((name, options['anns_field']))
            return [[{'id': 'e'}] if options['anns_field'] == 'title_vector' else [] for _ in options['data']]
    retriever.vector = Vector()
    result = retriever.search(['主题检索'], 'kb', '2026-10-03', mode='rrf')
    assert [x['evidence_id'] for x in result['evidence']] == ['e']
    assert result['evidence'][0]['text'] == state['evidence'][0]['text']
    assert calls == [('physical-dual', 'body_vector'), ('physical-dual', 'title_vector')]
    assert result['telemetry']['title_candidates'] == 1
    db.db.documents.update_one({'_id': 'd'}, {'$set': {'effective_until': '2026-01-01'}})
    assert not retriever.search(['主题检索'], 'kb', '2026-10-03', linked_evidence_ids=['e'])['evidence']


@pytest.mark.parametrize('failed', ['body_vector', 'title_vector'])
def test_one_vector_route_failure_preserves_the_other(db, state, monkeypatch, failed):
    retriever = dual(db, monkeypatch)
    class Vector:
        def search(self, name, **options):
            if options['anns_field'] == failed:
                raise TimeoutError('offline')
            return [[{'id': 'e'}] for _ in options['data']]
    retriever.vector = Vector()
    result = retriever.search(['不相关关键词'], 'kb', '2026-10-03', mode='dense')
    assert result['evidence'] and failed + '_unavailable:TimeoutError' in result['warnings']


def test_case_link_is_refilled_not_trusted(db, state):
    retriever = Retrieval(db)
    result = retriever.search(['zzz'], 'kb', '2026-10-03', mode='bm25', linked_evidence_ids=['fake', 'e'])
    assert [x['evidence_id'] for x in result['evidence']] == ['e']
    db.db.evidence.update_one({'_id': 'e'}, {'$set': {'text': 'tampered'}})
    assert not retriever.search(['zzz'], 'kb', '2026-10-03', mode='bm25', linked_evidence_ids=['e'])['evidence']


def test_reranker_receives_heading_and_body(db, state, monkeypatch):
    import xfagent.v2.retrieval as module
    retriever = dual(db, monkeypatch)
    db.db.evidence.update_one({'_id': 'e'}, {'$set': {'heading_path': ['规范', '设施维护']}})
    class Vector:
        def search(self, *a, **kw): return [[{'id': 'e'}] for _ in kw['data']]
    retriever.vector = Vector()
    payload = {}
    def post(url, json, **kw):
        payload.update(json)
        return SimpleNamespace(raise_for_status=lambda: None, json=lambda: {'scores': [.9]})
    monkeypatch.setattr(module.requests, 'post', post)
    result = retriever.search(['消火栓'], 'kb', '2026-10-03', mode='rerank')
    assert payload['texts'] == ['规范 / 设施维护\n' + state['evidence'][0]['text']]
    assert result['evidence'][0]['rerank_score'] == .9


def test_dual_build_has_no_dependency_on_legacy_files_and_preserves_published(db, state, monkeypatch):
    import xfagent.v2.retrieval as module
    calls, entities = [], []
    class Fields:
        def add_field(self, name, *a, **kw): calls.append(name)
        def add_index(self, **kw): pass
    class Vector:
        def create_schema(self, **kw): return Fields()
        def prepare_index_params(self): return Fields()
        def create_collection(self, *a, **kw): pass
        def upsert(self, name, rows): entities.extend(rows)
        def flush(self, name): pass
        def query(self, *a, **kw): return [{'count(*)': len(entities)}]
        def drop_collection(self, name): raise AssertionError('unexpected drop')
    monkeypatch.setattr(module, 'MilvusClient', lambda **kw: Vector())
    monkeypatch.setattr(module, 'embed', lambda texts, timeout: np.array([[1., 0.] for _ in texts]))
    db.db.snapshots.insert_one({'_id': 'kb', 'state': 'pending'})
    assert index_snapshot(db, 'kb') == 1
    assert {'body_vector', 'title_vector'} <= set(calls)
    assert set(entities[0]) == {'id', 'doc_id', 'body_vector', 'title_vector'}
    snapshot = db.db.snapshots.find_one({'_id': 'kb'})
    assert snapshot['index_schema'] == 'title-body-v1' and snapshot['index_ready']
    db.db.snapshots.insert_one({'_id': 'old', 'state': 'published', 'index_ready': True})
    with pytest.raises(ValueError, match='new heading-path'):
        index_snapshot(db, 'old')


def test_failed_index_build_does_not_activate_partial_vectors(db, state, monkeypatch):
    import xfagent.v2.retrieval as module
    dropped = []
    class Fields:
        def add_field(self, *a, **kw): pass
        def add_index(self, **kw): pass
    class Vector:
        def create_schema(self, **kw): return Fields()
        def prepare_index_params(self): return Fields()
        def create_collection(self, *a, **kw): pass
        def upsert(self, *a): raise RuntimeError('storage failed')
        def drop_collection(self, name): dropped.append(name)
    monkeypatch.setattr(module, 'MilvusClient', lambda **kw: Vector())
    monkeypatch.setattr(module, 'embed', lambda texts, timeout: np.array([[1., 0.] for _ in texts]))
    db.db.snapshots.insert_one({'_id': 'kb', 'state': 'pending'})
    with pytest.raises(RuntimeError): index_snapshot(db, 'kb')
    assert dropped and not db.db.snapshots.find_one({'_id': 'kb'}).get('index_ready')


def test_real_milvus_dual_fields_roundtrip(db, state, tmp_path, monkeypatch):
    pytest.importorskip('milvus_lite')
    import xfagent.v2.retrieval as module
    monkeypatch.setattr(module, 'MILVUS', str(tmp_path / 'vectors.db'))
    monkeypatch.setattr(module, 'embed', lambda texts, timeout: np.array([[1., 0.] for _ in texts], dtype='float32'))
    db.db.snapshots.insert_one({'_id': 'kb', 'state': 'pending'})
    assert index_snapshot(db, 'kb') == 1
    retriever = Retrieval(db)
    try:
        result = retriever.search(['消火栓'], 'kb', '2026-10-03', mode='rrf')
        assert [e['evidence_id'] for e in result['evidence']] == ['e']
        assert result['telemetry']['vector_fields'] == ['body_vector', 'title_vector']
        assert result['warnings'] == []
    finally:
        if retriever.vector:
            retriever.vector.close()


def test_numbered_standard_headings_do_not_swallow_article_numbers():
    _, children = structure('# 设施标准\n3 消火栓\n3.1 配置\n3.1.1 应完整。\n3.2 维护\n3.2.1 应保持清晰。', '设施标准', 'd')
    one = next(c for c in children if c['article'] == '3.1.1')
    two = next(c for c in children if c['article'] == '3.2.1')
    assert one['heading_path'] == ['设施标准', '3 消火栓', '3.1 配置']
    assert two['heading_path'] == ['设施标准', '3 消火栓', '3.2 维护']


def test_snapshot_migration_preserves_identical_text_under_different_headings(db, tmp_path, monkeypatch):
    import json
    import xfagent.v2.facts as module
    from xfagent.v2.store import digest
    root = tmp_path / 'data/legal'
    root.mkdir(parents=True)
    text = '# 规范\n## 消火栓\n第一条 应完整。\n## 灭火器\n第一条 应完整。'
    (root / 'source.txt').write_text(text)
    (root / 'manifest.json').write_text(json.dumps([{'id': 'd', 'title': '规范', 'status': 'source_verified',
        'kind': 'standard', 'raw_path': 'data/legal/source.txt', 'markdown_path': 'data/legal/source.txt',
        'sha256': digest(text.encode()), 'url': 'https://example.invalid/standard'}]))
    monkeypatch.setattr(module, 'ROOT', tmp_path)
    sid = module.prepare_snapshot(db)
    clauses = list(db.db.evidence.find({'snapshot_id': sid, 'article': '第一条'}))
    assert len(clauses) == 2 and clauses[0]['evidence_id'] != clauses[1]['evidence_id']
    result = Retrieval(db).search(['应完整'], sid, '2026-10-03', mode='bm25')
    assert len([e for e in result['evidence'] if e['article'] == '第一条']) == 2
    assert db.db.snapshots.find_one({'_id': sid})['structure_revision'] == 'heading-path-v2'


@pytest.mark.parametrize('governed', [False, True])
def test_main_graph_routes_uploaded_image_and_case_links_through_retrieval(db, state, tmp_path, monkeypatch, governed):
    from xfagent.v2 import graphs
    from xfagent.evidence_vision import VisionEvidence
    image = tmp_path / 'input.jpg'
    image.write_bytes(b'opaque-test-upload')
    state['request'].update(processed_image_path=str(image), use_model=False)
    state.update(calls=0, active_seconds=0, trace=[], warnings=[])
    seen = {}
    def references(self, request, facility, deadline, detections):
        seen['image'] = request['image']
        return {'similar_cases': [{'case_id': 'case1', 'linked_evidence_ids': ['e'],
                'authority': 'historical_case_not_current_fact', 'usable_as_legal_evidence': False}],
                'case_telemetry': {'routes': ['image_to_text']}, 'warnings': []}
    def search(self, queries, *a, **options):
        seen['links'] = options['linked_evidence_ids']
        return {'evidence': state['evidence'], 'queries': queries, 'warnings': []}
    monkeypatch.setattr(VisionEvidence, 'references', references)
    monkeypatch.setattr(graphs.Retrieval, 'search', search)
    graph = graphs.inspection_graph(db, governed=governed)
    result = graph.invoke(state, {'configurable': {'thread_id': 'cross-modal-' + str(governed)}, 'recursion_limit': 70})
    assert seen['image'].startswith('data:image/jpeg;base64,') and seen['links'] == ['e']
    assert result['report']['similar_cases'][0]['usable_as_legal_evidence'] is False
    assert result['case_telemetry']['routes'] == ['image_to_text']
    assert result['status'] == 'awaiting_review'
