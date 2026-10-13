import copy,json
from pathlib import Path
import pytest
from xfagent.legal_benchmark import load_benchmark,score_case,query_text,evidence_present,aggregate

BENCH=Path(__file__).resolve().parents[1]/'benchmarks/legal_scenarios/v1'
def fixture():
    c={'id':'x','scenario_id':'s','family_id':'s','split':'test','stage':'combined','category':'设施','as_of':'2026-10-02','gold_evidence_ids':['a','b']}
    ev={x:{'doc_id':'d','source_sha256':'sha','quote':text} for x,text in [('a','不得遮挡消火栓'),('b','落实整改期限')]}
    h={'id':'h','doc_id':'d','source_sha256':'sha','text':'不得遮挡消火栓','parent_text':'不得遮挡消火栓。落实整改期限。'}
    return c,ev,h,{'d':{'effective_from':'2021-01-01'}}

def test_scene_split_and_minimum():
    cases,ev,manifest=load_benchmark(BENCH)
    assert len(cases)==272
    assert sum(c['split']=='test' for c in cases)>=200
    assert manifest['scenario_families']==80
    assert sum(not c['gold_evidence_ids'] for c in cases)==20
    assert sum(c['expected']['action']=='accept_item_conditionally' for c in cases)==12
    assert all('expected' not in c['input'] and 'gold_evidence_ids' not in c['input'] for c in cases)

def test_same_document_is_not_evidence():
    c,ev,h,docs=fixture();h['text']='其他不相干条款'
    score=score_case(c,[h],ev,docs)
    assert score['child']['evidence_recall@5']==0
    assert score['parent_context']['all_evidence@5']==1

def test_combined_requires_both_and_normalizes_whitespace_only():
    c,ev,h,docs=fixture();h['text']='不得 遮挡\n消火栓'
    score=score_case(c,[h],ev,docs)
    assert score['child']['evidence_recall@5']==.5
    assert score['child']['all_evidence@5']==0
    h['text']='可以遮挡消火栓'
    assert not evidence_present(h,ev['a'],'text')

def test_wrong_source_hash_no_credit():
    c,ev,h,docs=fixture();h['source_sha256']='changed'
    assert score_case(c,[h],ev,docs)['parent_context']['all_evidence@5']==0

def test_version_half_open_interval_and_forbidden_version():
    c,ev,h,docs=fixture();docs['d']['effective_until']='2026-10-02'
    assert score_case(c,[h],ev,docs)['temporal_error_ids']==['h']
    docs['d']={'effective_from':'2027-01-01'}
    assert score_case(c,[h],ev,docs)['temporal_error_ids']==['h']

def test_insufficient_answer_not_automatically_correct_or_failed():
    c,ev,h,docs=fixture();c['gold_evidence_ids']=[]
    r=score_case(c,[h],ev,docs)
    assert r['child'] is None and r['behavior_score'] is None
    assert aggregate([r])['behavior_accuracy'] is None

def test_context_is_used_but_expected_answer_is_not():
    c={'as_of':'2026-10-02','input':{'setting':'学校','observations':['楼道遮挡'],'history':[{'content':'历史提问'}],'query':'如何处理'},'expected':{'secret':'CANARY_GOLD'}}
    q=query_text(c)
    assert '学校' in q and '楼道遮挡' in q and '历史提问' in q
    assert 'CANARY_GOLD' not in q

def test_manifest_tampering_rejected(tmp_path):
    import shutil
    shutil.copytree(BENCH,tmp_path/'b')
    with (tmp_path/'b/cases.jsonl').open('a') as f:f.write('\n')
    with pytest.raises(ValueError,match='checksum'):load_benchmark(tmp_path/'b')
