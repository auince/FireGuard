"""Check ablation switches actually isolate ranking and result selection."""
import json
import numpy as np
import pytest
from xfagent.retrieval import SearchIndex

@pytest.fixture
def index(tmp_path):
    children=[{'id':f'c{i}','doc_id':'d','parent_id':'p0' if i<2 else 'p1','text':'消火栓故障','title':'测试法规','article':str(i)} for i in range(3)]
    docs=[{'id':'d','title':'测试法规','status':'source_verified','kind':'law','effective_from':'2021-01-01','url':'https://example.invalid','sha256':'fixed'}]
    (tmp_path/'corpus.json').write_text(json.dumps({'documents':docs,'children':children,'parents':[{'id':p,'text':'消火栓故障'} for p in ['p0','p1']]}))
    np.save(tmp_path/'text.npy',np.array([[1.,0.],[.9,.1],[.5,.8]],dtype=np.float32))
    np.save(tmp_path/'title.npy',np.array([[.1,.9],[.2,.8],[.8,.2]],dtype=np.float32))
    return SearchIndex(tmp_path)

def ids(hits):return [h['id'] for h in hits]
def test_parent_dedup_toggle_preserves_ranking(index):
    kwargs={'query':'消火栓','mode':'dense','query_vector':np.array([1.,0.]),'as_of':'2026-10-02'}
    assert ids(index.search(**kwargs))==['c0','c2']
    assert ids(index.search(**kwargs,deduplicate_parents=False))==['c0','c1','c2']

def test_title_gate_and_flat_hybrid_are_distinct(index):
    kwargs={'query':'消火栓','query_vector':np.array([1.,0.]),'as_of':'2026-10-02'}
    assert ids(index.search(**kwargs,mode='hierarchical'))==['c2']
    assert ids(index.search(**kwargs,mode='title_dense'))[0]=='c2'
    assert ids(index.search(**kwargs,mode='hybrid'))[0]=='c2'
    assert ids(index.search(**kwargs,mode='flat_hybrid'))[0]=='c0'

@pytest.mark.parametrize('mode',['bm25','dense','hierarchical','title_dense','weighted','hybrid','flat_hybrid'])
def test_ablation_never_disables_effective_date(index,mode):
    assert index.search('消火栓',mode=mode,query_vector=np.array([1.,0.]),as_of='2020-01-01')==[]
