from xfagent.practice.contracts import Inspection
from xfagent.practice.harness import Harness
from test_prototype import Model, RAG


def test_fixed_dag_no_bypass_or_loop():
    harness = Harness(RAG(), Model())
    request = Inspection(query='检查室内消火栓').model_dump(mode='json')
    report = harness.execute(request)
    assert [row['node'] for row in report['trace']] == list(Harness.NODES)
    edges = {(e.source, e.target) for e in harness.graph.get_graph().edges}
    assert edges == {('__start__', 'Intent'), ('Intent', 'Rewrite'), ('Rewrite', 'Retrieval'),
                     ('Retrieval', 'Answer'), ('Answer', 'Verify'), ('Verify', '__end__')}
    assert report['model_calls'] == 3


def test_semantic_opposite_and_measurement_are_blocked():
    model = Model()
    original = model.complete
    def disputed(role, payload, image=None, **kwargs):
        return {'supported': False, 'issues': ['opposite meaning']} if role == 'verify' else original(role, payload, image, **kwargs)
    model.complete = disputed
    request = Inspection(query='检查室内消火栓').model_dump(mode='json')
    assert 'semantic_unsupported' in Harness(RAG(), model).execute(request)['verification']['errors']
    def invented(role, payload, image=None, **kwargs):
        result = original(role, payload, image, **kwargs)
        if role == 'answer': result['hazards'][0]['description'] = '现场实测压力为0.2MPa'
        return result
    model.complete = invented
    assert 'unmeasured_fact' in Harness(RAG(), model).execute(request)['verification']['errors']
