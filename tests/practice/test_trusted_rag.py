from types import SimpleNamespace

from xfagent.practice.rag import TrustedRAG


def test_current_rag_snapshot_date_and_mode_are_bound():
    observed = {}
    def search(queries, sid, as_of, jurisdiction, **options):
        observed.update(queries=queries, sid=sid, date=as_of, region=jurisdiction, **options)
        return {'evidence': [], 'warnings': []}
    rag = TrustedRAG(SimpleNamespace(active_snapshot=lambda: 'kb-current'), SimpleNamespace(search=search))
    result = rag.search({'as_of': '2026-10-13', 'jurisdiction': '四川', 'retrieval_mode': 'rerank'}, ['问题', '术语'])
    assert result['snapshot_id'] == 'kb-current'
    assert observed == {'queries': ['问题', '术语'], 'sid': 'kb-current', 'date': '2026-10-13',
                        'region': '四川', 'mode': 'rerank', 'k': 5, 'parent_expand': True}
