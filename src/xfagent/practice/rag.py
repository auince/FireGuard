"""Stage 2 reuses the project's current RAG, including canonical refilling."""
import os

from xfagent.v2.retrieval import Retrieval
from xfagent.v2.store import Store
from xfagent.v2.facts import fetch_evidence


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
