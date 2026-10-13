"""Stage 2 reuses the project's current RAG, including canonical refilling."""
import os

from xfagent.v2.retrieval import Retrieval
from xfagent.v2.store import Store
from xfagent.v2.facts import fetch_evidence
from xfagent.v2.facts import eligible


class TrustedRAG:
    def __init__(self, store=None, retriever=None):
        # By default read the existing published KB. This adapter never publishes it.
        self.store = store or Store(name=os.getenv('XF_PRACTICE_KB_DB', 'xfagent_v2'))
        self.retriever = retriever or Retrieval(self.store)

    def search(self, request, queries):
        snapshot = self.store.active_snapshot()
        result = self.retriever.search(queries, snapshot, request['as_of'], request['jurisdiction'],
            mode=request.get('retrieval_mode', 'rrf'), k=5, parent_expand=True)
        return dict(result, snapshot_id=snapshot, rag_version='current-v2-canonical-hybrid')

    def validate(self, evidence, request, snapshot):
        errors = []
        fields = ['text', 'quote_hash', 'source_hash', 'version_id', 'conditions', 'source_url']
        for reported in evidence:
            current = fetch_evidence(self.store, snapshot, reported['evidence_id'],
                                     request['as_of'], request['jurisdiction'])
            if not current or any(reported.get(k) != current.get(k) for k in fields):
                errors.append('source_mismatch:' + reported['evidence_id'])
        return errors

    def documents(self, as_of, jurisdiction):
        sid = self.store.active_snapshot()
        rows = self.store.db.documents.find({'snapshot_id': sid})
        fields = ['doc_id', 'title', 'version_id', 'effective_from', 'effective_until',
                  'jurisdiction', 'lifecycle', 'url', 'sha256']
        return {'snapshot_id': sid, 'documents': [
            {key: doc.get(key) for key in fields} for doc in rows if eligible(doc, as_of, jurisdiction)]}

    def document(self, doc_id, as_of, jurisdiction):
        from xfagent.v2.store import digest
        sid = self.store.active_snapshot()
        doc = self.store.db.documents.find_one({'snapshot_id': sid, 'doc_id': doc_id})
        if not doc or not eligible(doc, as_of, jurisdiction):
            return None
        body = doc.get('full_text', '')
        if not body or digest(body.encode()) != doc.get('body_hash'):
            raise ValueError('法规原文完整性校验失败')
        return {key: doc.get(key) for key in ['doc_id', 'title', 'version_id', 'full_text', 'url', 'effective_from']}
