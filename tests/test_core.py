import json,sqlite3
from pathlib import Path
import pytest
from xfagent.ingest import structure,html_markdown
from xfagent.retrieval import rrf,SearchIndex
from xfagent.data import Store,curate,export_reviewed,image_hash
from xfagent.graphs import annotation_graph,retrieval_graph
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.types import Command

def test_hierarchical_chunks_keep_article_and_parent():
    parents,children=structure('第一章 总则\n第一条 维护消防设施完好。\n第二条 禁止遮挡。\n第二章 管理\n第三条 定期检查。','规定','law')
    assert len(parents)==2
    assert {c['article'] for c in children if c['article']}=={'第一条','第二条','第三条'}
    assert '禁止遮挡' in parents[0]['text']

def test_extract_removes_scripts_preserves_tables():
    text=html_markdown('<article><p>'+('消防管理。'*30)+'</p><script>bad()</script><table><tr><td>项目</td><td>要求</td></tr></table></article>')
    assert 'bad()' not in text and '项目 | 要求' in text

def test_rrf_matches_two_lists():
    order,scores=rrf([[1,2],[2,3]])
    assert order[0]==2 and scores[2]==pytest.approx(1/62+1/61)

def test_dates_exclude_future_and_expired(tmp_path):
    docs=[{'id':name,'title':name,'url':'https://www.mem.gov.cn/x','sha256':name,'status':'source_verified',**dates} for name,dates in [('current',{}),('future',{'effective_from':'2027-01-01'}),('expired',{'effective_until':'2026-01-01'})]]
    parents=[];children=[]
    for d in docs:
        p,c=structure('消防设施应当保持完好','消防法',d['id']);parents+=p;children+=c
    (tmp_path/'corpus.json').write_text(json.dumps({'documents':docs,'parents':parents,'children':children}))
    hits=SearchIndex(tmp_path).search('消防设施',mode='bm25',as_of='2026-10-02')
    assert [h['doc_id'] for h in hits]==['current']

def test_review_interrupt_survives_new_graph(tmp_path,monkeypatch):
    monkeypatch.setattr('xfagent.graphs.complete',lambda *a,**kw:'{"labels":[],"verdict":"合规"}')
    config={'configurable':{'thread_id':'review-1'}}
    with SqliteSaver.from_conn_string(str(tmp_path/'checkpoint.db')) as saver:
        result=annotation_graph(saver).invoke({'image':'data:image/jpeg;base64,eA==','image_sha256':'abc','mode':'model_first'},config)
        assert result.get('__interrupt__') and not result.get('approved')
    with SqliteSaver.from_conn_string(str(tmp_path/'checkpoint.db')) as saver:
        result=annotation_graph(saver).invoke(Command(resume={'reviewer':'tester','labels':[],'accepted':True,'scope':'箱体外观','verdict':'合规','evidence':'箱门与标识可见'}),config)
        assert result['approved']['accepted'] and result['exported'] is False

def test_store_job_does_not_overwrite_annotation(tmp_path):
    store=Store(tmp_path/'app.db');store.put('annotation',{'labels':['a']},'same');store.put('job',{'status':'complete'},'same')
    assert store.get('same','annotation')['payload']['labels']==['a']
    assert store.get('same')['payload']['status']=='complete'

def test_curation_excludes_content_duplicates_and_frozen(tmp_path):
    from PIL import Image
    paths=[]
    for i in range(5):
        p=tmp_path/f'{i}.png';Image.new('RGB',(8,8),(i*40,0,0)).save(p);paths.append(str(p))
    data=[{'id':str(i),'images':[p],'messages':[{'role':'assistant','content':'answer'}]} for i,p in enumerate(paths)]
    source=tmp_path/'source.jsonl';frozen=tmp_path/'frozen.jsonl'
    source.write_text('\n'.join(json.dumps(x) for x in data+[data[2]]));frozen.write_text(json.dumps(data[0]))
    result=curate(source,frozen,tmp_path/'out')
    assert result['train']+result['validation']==4
    assert result['frozen_overlap']==result['train_validation_overlap']==0

def test_retrieval_iteration_bounded(monkeypatch):
    class Index:
        def search(self,*args,**kwargs):return []
    def complete(prompt):return '{"queries":["消火栓"],"sufficient":false,"next_queries":["消防箱"]}'
    monkeypatch.setattr('xfagent.graphs.complete',complete)
    result=retrieval_graph(Index()).invoke({'query':'问题','max_rounds':2,'mode':'bm25','use_model':True})
    assert result['rounds']==2 and '未检索到' in result['answer']

def test_verifiable_rewards_prefer_correct_labels():
    from xfagent.rewards import label_reward,verdict_reward
    correct='检查范围：内部组件\n结论：不合规\n隐患标签：室内消火栓手轮缺失\n可见证据：手轮缺失。'
    wrong='检查范围：内部组件\n结论：合规\n隐患标签：无\n可见证据：完好。'
    assert label_reward([correct,wrong],[['室内消火栓手轮缺失']]*2)==[1.,0.]
    assert verdict_reward([correct,wrong],['不合规']*2)==[1.,0.]

def test_contradictory_visual_report_requires_review():
    from xfagent.vision import consistency_guard
    report='检查范围：箱体外观\n结论：不合规\n可见依据：未见明确隐患。\n隐患标签：操作说明缺失'
    checked,warnings=consistency_guard(report)
    assert '结论：无法判断' in checked and '待复核候选：操作说明缺失' in checked
    assert warnings==['evidence_verdict_conflict']

def test_api_rejects_invalid_images_and_unregistered_case(tmp_path,monkeypatch):
    import xfagent.api as api
    monkeypatch.setattr(api,'Store',lambda:Store(tmp_path/'api.db'))
    app=api.create_app();client=app.test_client()
    assert client.post('/api/inspect',json={'image':'file:///etc/passwd'}).status_code==400
    assert client.post('/api/inspect',json={'image':'data:image/jpeg;base64,eA=='}).status_code==400
    assert client.get('/api/cases/image/not-a-registered-case').status_code==404
