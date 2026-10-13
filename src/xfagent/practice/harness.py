"""Stage 1 self-built orchestration: no agent framework imports."""
import time
import uuid

from .contracts import Answer
from .model import Model
from .vector import BasicVectorRAG


class Harness:
    def __init__(self, rag=None, model=None):
        self.rag = rag or BasicVectorRAG()
        self.model = model or Model()

    def execute(self, request, owner='anonymous'):
        state = {'id': uuid.uuid4().hex, 'revision': 1, 'status': 'draft', **request,
                 'owner': owner, 'trace': [], 'model': self.model.name, 'framework': 'self-built'}
        started = time.monotonic()
        retrieved = self.rag.search(request, [request['query']])
        state.update(retrieved)
        state['trace'].append({'node': 'Retrieval', 'status': 'complete', 'seconds': time.monotonic()-started})
        started = time.monotonic()
        result = (self.model.complete('answer', {'query': request['query'], 'scene': request.get('scene', {}),
                    'evidence': state['evidence']}, request.get('image')) if state['evidence'] else
                  {'hazards': [], 'missing_information': ['未召回相关条款，请补充资料或调整问题']})
        state['answer'] = Answer.model_validate(result).model_dump()
        known = {e['evidence_id'] for e in state['evidence']}
        errors = ['forged_citation'] if any(set(h['evidence_ids'])-known for h in state['answer']['hazards']) else []
        state['verification'] = {'passed': not errors and bool(state['evidence']), 'errors': errors}
        state['trace'].append({'node': 'Answer', 'status': 'complete', 'seconds': time.monotonic()-started})
        return state
