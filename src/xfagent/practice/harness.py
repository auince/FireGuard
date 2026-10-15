"""Stage 3: exactly five LangGraph nodes; no planning loop or retrieval bypass."""
import time
import uuid
from typing import TypedDict

from langgraph.graph import END, START, StateGraph
from xfagent.v2.fact_checks import condition_matches, measurement_checks

from .contracts import Answer, FACILITIES
from .model import Model
from xfagent.evidence_vision import VisionEvidence
from .memory import resolve_followup
from .rag import TrustedRAG


class State(TypedDict, total=False):
    id: str
    revision: int
    status: str
    owner: str
    request: dict
    facility: str
    queries: list
    evidence: list
    warnings: list
    snapshot_id: str
    rag_version: str
    telemetry: dict
    trace: list
    answer: dict
    verification: dict
    deadline: float
    model: str
    framework: str
    memory_context: dict
    detector: dict
    similar_cases: list
    case_telemetry: dict
    model_calls: int


class Harness:
    NODES = ('Intent', 'Rewrite', 'Retrieval', 'Answer', 'Verify')

    def __init__(self, rag=None, model=None, vision=None):
        self.rag = rag or TrustedRAG()
        self.model = model or Model()
        self.vision = vision or VisionEvidence()
        graph = StateGraph(State)
        for name, function in zip(self.NODES, [self.intent, self.rewrite, self.retrieve, self.answer, self.verify]):
            graph.add_node(name, self.timed(name, function))
        for left, right in zip((START,) + self.NODES, self.NODES + (END,)):
            graph.add_edge(left, right)
        self.graph = graph.compile()

    def timed(self, name, function):
        def invoke(state, config):
            started = time.monotonic()
            if started >= state['deadline']:
                raise TimeoutError('Harness execution budget exhausted')
            values = function(state)
            trace = state['trace'] + [{'node': name, 'status': 'complete', 'seconds': time.monotonic()-started}]
            callback = config.get('configurable', {}).get('on_trace')
            if callback:
                callback(trace)
            return dict(values, trace=trace, model_calls=state.get('model_calls', 0))
        return invoke

    def complete(self, state, role, payload, image=None):
        remaining = state['deadline'] - time.monotonic()
        if remaining <= 0 or state.get('model_calls', 0) >= 4:
            raise TimeoutError('Harness model budget exhausted')
        state['model_calls'] = state.get('model_calls', 0) + 1
        return self.model.complete(role, payload, image, timeout=remaining)

    def intent(self, state):
        request = state['request']
        facility = resolve_followup(request, state.get('memory_context', {})) or request['facility']
        if facility == 'auto':
            matches = [key for key, term in FACILITIES.items() if term in request['query']]
            if len(matches) == 1:
                facility = matches[0]
            else:
                facility = self.complete(state, 'intent', {'query': request['query']}, request.get('image')).get('facility')
        facility = facility if facility in FACILITIES else 'unknown'
        visual = self.vision.analyze(request, facility, state['deadline']) if request.get('image') else {'detector': {'status': 'not_requested', 'detections': []}, 'similar_cases': [], 'warnings': []}
        return {'facility': facility, **visual}

    def rewrite(self, state):
        request = state['request']
        result = self.complete(state, 'rewrite', {'query': request['query'], 'facility': state['facility'],
                    'scene': request['scene'], 'conversation_context': state.get('memory_context', {}).get('working', {}), 'as_of': request['as_of'], 'jurisdiction': request['jurisdiction']})
        queries = [(FACILITIES.get(state['facility'], '') + ' ' + request['query']).strip()] + [q[:400] for q in result.get('queries', []) if isinstance(q, str) and q.strip()]
        return {'queries': list(dict.fromkeys(queries))[:3]}

    def retrieve(self, state):
        result = self.rag.search(state['request'], state['queries'])
        result['warnings'] = state.get('warnings', []) + result.get('warnings', [])
        return {key: result[key] for key in ['evidence', 'warnings', 'snapshot_id', 'rag_version', 'telemetry'] if key in result}

    def answer(self, state):
        request = state['request']
        result = (self.complete(state, 'answer', {'query': request['query'], 'facility': state['facility'],
                    'scene': request['scene'], 'evidence': state['evidence'],
                    'preferences': state.get('memory_context', {}).get('preferences', {}),
                    'detector_localization_only': state.get('detector', {}),
                    'historical_references_not_current_facts': state.get('similar_cases', [])}, request.get('image'))
                  if state['evidence'] else {'hazards': [], 'missing_information': ['未召回相关条款，请补充资料或调整问题']})
        return {'answer': Answer.model_validate(result).model_dump()}

    def verification(self, report, semantic=True):
        request = report['request']
        evidence = report['evidence']
        answer = Answer.model_validate(report['answer']).model_dump()
        known = {e['evidence_id'] for e in evidence}
        errors = []
        if not evidence:
            errors.append('missing_evidence')
        if not answer['hazards']:
            errors.append('no_supported_hazard')
        if answer['missing_information']:
            errors.append('missing_information')
        for i, hazard in enumerate(answer['hazards']):
            if set(hazard['evidence_ids']) - known:
                errors.append('forged_citation')
            measured, _ = measurement_checks({'text': hazard['description'] + '；' + hazard['suggestion'],
                                              'claim_id': str(i)}, request['scene'])
            errors.extend(e['code'] for e in measured)
        for item in evidence:
            for field, expected in item.get('conditions', {}).items():
                if field not in request['scene']:
                    errors.append('unknown_applicability:' + field)
                elif not condition_matches(request['scene'][field], expected):
                    errors.append('inapplicable_evidence:' + field)
        if hasattr(self.rag, 'validate'):
            errors.extend(self.rag.validate(evidence, request, report['snapshot_id']))
        review = 'blocked_by_deterministic_checks'
        if not errors and semantic:
            result = self.complete(report, 'verify', {'query': request['query'], 'scene': request['scene'],
                        'answer': answer, 'evidence': evidence}, request.get('image'))
            review = 'model_supported' if result.get('supported') is True else 'model_disputed'
            if result.get('supported') is not True:
                errors.append('semantic_unsupported')
        return {'passed': not errors, 'errors': list(dict.fromkeys(errors)), 'semantic_review': review}

    def verify(self, state):
        return {'verification': self.verification(state)}

    def execute(self, request, owner='anonymous', run_id=None, on_trace=None, memory_context=None):
        state = {'id': run_id or uuid.uuid4().hex, 'revision': 1, 'status': 'draft', 'request': request,
                 'owner': owner, 'memory_context': memory_context or {}, 'trace': [], 'model': self.model.name, 'framework': 'langgraph-fixed-dag',
                 'warnings': [], 'model_calls': 0, 'deadline': time.monotonic() + 300}
        result = self.graph.invoke(state, config={'recursion_limit': 10, 'configurable': {'on_trace': on_trace}})
        return {**request, **{key: value for key, value in result.items() if key not in {'request', 'deadline'}}}
