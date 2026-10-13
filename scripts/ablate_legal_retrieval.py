"""Fixed-config paired retrieval ablation. No tuning on the observed test set."""
import json,time,platform
from pathlib import Path
from collections import defaultdict
from datetime import datetime,timezone
import numpy as np
from xfagent.config import ROOT
from xfagent.retrieval import SearchIndex,embed
from xfagent.legal_benchmark import load_benchmark,query_text,score_case,aggregate,digest

VARIANTS={
 'bm25':('BM25',{'mode':'bm25'}),
 'dense':('仅正文向量',{'mode':'dense'}),
 'title_dense':('仅标题向量',{'mode':'title_dense'}),
 'weighted':('正文0.8＋标题0.2',{'mode':'weighted'}),
 'hierarchical':('标题筛选→正文向量',{'mode':'hierarchical'}),
 'flat_hybrid':('BM25＋正文向量RRF（无标题筛选）',{'mode':'flat_hybrid'}),
 'hybrid':('现有完整混合检索',{'mode':'hybrid'}),
 'hybrid_no_dedup':('完整混合检索去掉父章节去重',{'mode':'hybrid','deduplicate_parents':False}),
}
PAIRS=[('hybrid','hierarchical','加入BM25分支及RRF融合'),('hybrid','bm25','加入标题筛选后的向量分支及RRF融合'),
 ('hierarchical','dense','正文向量增加标题筛选'),('weighted','dense','正文向量增加20%标题权重'),
 ('hybrid','flat_hybrid','混合检索增加标题筛选'),('hybrid_no_dedup','hybrid','关闭每章只返回一个片段限制')]

def comparison(a,b,field,metric):
    # Cluster bootstrap: keep all same-scene branches together in paired resampling.
    groups=defaultdict(list)
    for x,y in zip(a,b):
        assert x['id']==y['id']
        if x[field] is not None:groups[x['family_id']].append(x[field][metric]-y[field][metric])
    vals=list(groups.values());sums=np.array([sum(v) for v in vals]);sizes=np.array([len(v) for v in vals])
    rng=np.random.default_rng(20261002);pick=rng.integers(0,len(vals),size=(3000,len(vals)))
    dist=sums[pick].sum(axis=1)/sizes[pick].sum(axis=1)
    return {'delta':float(sums.sum()/sizes.sum()),'cluster_bootstrap_ci95':np.quantile(dist,[.025,.975]).tolist(),
      'improved':sum(v>1e-9 for vs in vals for v in vs),'worsened':sum(v< -1e-9 for vs in vals for v in vs),
      'unchanged':sum(abs(v)<=1e-9 for vs in vals for v in vs),'families':len(vals)}

def main():
    bench=ROOT/'benchmarks/legal_scenarios/v1';out=ROOT/'reports/legal_retrieval_ablation_v1';out.mkdir(parents=True,exist_ok=True)
    cases,ev,manifest=load_benchmark(bench);idx=SearchIndex();queries=[query_text(c) for c in cases]
    for e in ev.values():assert idx.docs[e['doc_id']]['sha256']==e['source_sha256']
    start=time.perf_counter();batches=[]
    for i in range(0,len(cases),12):
        batches.append(embed(queries[i:i+12]));print('embedded',min(i+12,len(cases)),flush=True)
    vec=np.concatenate(batches);embedding_seconds=time.perf_counter()-start
    np.save(out/'query_vectors.npy',vec)
    (out/'query_inputs.jsonl').write_text(''.join(json.dumps({'id':c['id'],'query':q},ensure_ascii=False)+'\n' for c,q in zip(cases,queries)))
    results={k:[] for k in VARIANTS};timings={k:[] for k in VARIANTS};diagnostics=[];raw_hits={k:[] for k in VARIANTS}
    # Interleave variants to avoid making timing a run-order comparison.
    keys=list(VARIANTS);rng=np.random.default_rng(20261002)
    for i,(c,q) in enumerate(zip(cases,queries)):
        order=rng.permutation(keys)
        for key in order:
            t=time.perf_counter();hits=idx.search(q,k=5,as_of=c['as_of'],query_vector=vec[i],**VARIANTS[key][1]);elapsed=time.perf_counter()-t
            r=score_case(c,hits,ev,idx.docs);r['hits']=[{k:h[k] for k in ['id','doc_id','parent_id','article','source_url','score']} for h in hits]
            r['returned_child_chars']=sum(len(h['text']) for h in hits)
            r['unique_parent_chars']=sum(len(idx.parents[p]['text']) for p in {h['parent_id'] for h in hits})
            results[key].append(r);timings[key].append(elapsed);raw_hits[key].append([h['id'] for h in hits])
        allowed=[j for j,x in enumerate(idx.children) if
            idx.docs[x['doc_id']].get('status')=='source_verified' and idx.docs[x['doc_id']].get('kind') not in ['catalog','announcement'] and
            (idx.docs[x['doc_id']].get('effective_from') or '')<=c['as_of'] and
            (not idx.docs[x['doc_id']].get('effective_until') or c['as_of']<idx.docs[x['doc_id']]['effective_until'])]
        qv=vec[i]/np.linalg.norm(vec[i]);scores=idx.vectors['title']@qv;body=idx.vectors['text']@qv
        eligible=[j for j in allowed if scores[j]>=.4];fallback=not eligible
        if fallback:
            parents={idx.children[j]['parent_id'] for j in sorted(allowed,key=lambda j:-scores[j])[:5]}
            eligible=[j for j in allowed if idx.children[j]['parent_id'] in parents]
        top60=sorted(allowed,key=lambda j:-body[j])[:60]
        diagnostics.append({'id':c['id'],'allowed':len(allowed),'retained':len(eligible),'fallback':fallback,
          'body_top60_removed':sum(j not in set(eligible) for j in top60),
          'dense_hierarchical_same_top5':raw_hits['dense'][-1]==raw_hits['hierarchical'][-1],
          'hybrid_flat_same_top5':raw_hits['hybrid'][-1]==raw_hits['flat_hybrid'][-1]})
        if (i+1)%50==0:print('evaluated',i+1,flush=True)
    summaries={}
    for key,rows in results.items():
        (out/(key+'.jsonl')).write_text(''.join(json.dumps(r,ensure_ascii=False)+'\n' for r in rows))
        summaries[key]={'label':VARIANTS[key][0],'config':{'k':5,'title_threshold':.4,'deduplicate_parents':True,**VARIANTS[key][1]},
          'all':aggregate(rows),'by_split':{s:aggregate([r for r in rows if r['split']==s]) for s in ['dev','test']},
          'by_stage':{s:aggregate([r for r in rows if r['stage']==s]) for s in sorted({r['stage'] for r in rows})},
          'mean_ranking_ms':float(np.mean(timings[key])*1000),'p95_ranking_ms':float(np.quantile(timings[key],.95)*1000),
          'mean_child_chars':float(np.mean([r['returned_child_chars'] for r in rows])),
          'mean_unique_parent_chars':float(np.mean([r['unique_parent_chars'] for r in rows]))}
    pairs=[]
    for a,b,label in PAIRS:
        pairs.append({'a':a,'b':b,'change':label,**{split:{f'{field}/{metric}':comparison(
          [r for r in results[a] if split=='all' or r['split']==split],[r for r in results[b] if split=='all' or r['split']==split],field,metric)
          for field,metric in [('child','evidence_recall@5'),('child','all_evidence@5'),('child','mrr'),('parent_context','all_evidence@5')]}
          for split in ['all','test']}})
    prior=ROOT/'reports/legal_scenarios_v1';regression={}
    for key in ['bm25','dense','hierarchical','weighted','hybrid']:
        old=[json.loads(s) for s in (prior/(key+'.jsonl')).read_text().splitlines()]
        assert [r['id'] for r in old]==[r['id'] for r in results[key]]
        regression[key]=sum(x['hit_ids']!=y['hit_ids'] for x,y in zip(old,results[key]))
    report={'created_at':datetime.now(timezone.utc).isoformat(),'benchmark':manifest,'variants':summaries,'paired_comparisons':pairs,
      'diagnostics':{'fallback_queries':sum(d['fallback'] for d in diagnostics),'mean_retained_fraction':float(np.mean([d['retained']/d['allowed'] for d in diagnostics])),
        'queries_removing_any_body_top60':sum(d['body_top60_removed']>0 for d in diagnostics),
        'dense_hierarchical_identical_top5':sum(d['dense_hierarchical_same_top5'] for d in diagnostics),
        'hybrid_flat_identical_top5':sum(d['hybrid_flat_same_top5'] for d in diagnostics)},
      'baseline_changed_top5_counts':regression,'embedding_seconds_once_for_all_variants':embedding_seconds,
      'environment':{'python':platform.python_version(),'platform':platform.platform()},
      'fingerprints':{str(p.relative_to(ROOT)):digest(p) for p in [bench/'manifest.json',idx.path/'corpus.json',idx.path/'text.npy',idx.path/'title.npy',ROOT/'src/xfagent/retrieval.py',Path(__file__),out/'query_vectors.npy',out/'query_inputs.jsonl']},
      'controls':'Identical frozen corpus, title/body vectors, query inputs, evidence, as_of, candidate limit 60, RRF k=60 and output k=5. No query rewriting or model-generated answers. Default parent dedup retained except explicit no_dedup ablation.',
      'limitations':['Synthetic source-aligned gold pending expert review; alternatives may be unlabelled.',
       '272 cases, 252 retrievable; test 215 cases, 199 retrievable. Twenty insufficient-answer cases have no answer-level score.',
       'Test was previously observed; these are descriptive fixed-configuration ablations, no test-based tuning and no independent blind evaluation claim.',
       'Child versus parent context scores measure different evidence budgets; context character counts are reported.',
       'Timing excludes query embedding/network and contains shared implementation overhead; not an optimized algorithm speed comparison.',
       'Bootstrap clusters by scene, not legal article; shared source propositions still induce dependence. Intervals are descriptive only.']}
    (out/'summary.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    (out/'gate_diagnostics.jsonl').write_text(''.join(json.dumps(d)+'\n' for d in diagnostics))
    lines=['# 法规检索方式消融实验','', '固定272例场景测试输入，召回指标分母为252例有标注证据的用例；单独报告test的199例。未改动语料或金标，未搜索阈值、融合权重。默认检索方式保持不变。', '']
    for scope in ['all','test']:
        lines += ['## '+('全量描述性对比（252例）' if scope=='all' else '既有test分组（199例，非盲测）'),'','| 方案 | 片段证据Recall@5 | 片段全证据@5 | 片段MRR | 整章全证据@5 |','|---|---:|---:|---:|---:|']
        for key,s in summaries.items():
            v=s['all'] if scope=='all' else s['by_split']['test']
            lines.append(f"| {s['label']} | {v['child']['evidence_recall@5']:.2%} | {v['child']['all_evidence@5']:.2%} | {v['child']['mrr']:.4f} | {v['parent_context']['all_evidence@5']:.2%} |")
        lines+=['']
    lines += ['## 控制变量对比','','正差表示前者更高；区间为按场景族成组的3000次配对bootstrap，非独立泛化或因果保证。','','| 仅改变的组件 | 片段Recall@5变化（百分点） | 95%区间 | 改善/退化/不变用例 |','|---|---:|---|---|']
    for p in pairs:
        v=p['all']['child/evidence_recall@5'];lo,hi=v['cluster_bootstrap_ci95']
        lines.append(f"| {p['change']} | {v['delta']*100:+.2f} | [{lo*100:+.2f}, {hi*100:+.2f}] | {v['improved']}/{v['worsened']}/{v['unchanged']} |")
    lines+=['','## 分场景：片段全部所需证据命中率@5','','| 场景 | BM25 | 正文向量 | 完整混合 | 混合取消章节去重 |','|---|---:|---:|---:|---:|']
    for stage in ['finding','proposal','verification','combined','temporal','untrusted_input']:
        labels={'finding':'现场发现','proposal':'整改方案','verification':'复核补证','combined':'跨条款处置','temporal':'版本边界','untrusted_input':'工单干扰（仅检索）'}
        lines.append('| '+labels[stage]+' | '+' | '.join(f"{summaries[k]['by_stage'][stage]['child']['all_evidence@5']:.2%}" for k in ['bm25','dense','hybrid','hybrid_no_dedup'])+' |')
    lines+=['','## 实现诊断','',json.dumps(report['diagnostics'],ensure_ascii=False),'',
      '标题向量来自现有 index_title，包含法规名、章节、条号及此前增强的关键词；不是只编码一个简短标题。门控为相似度≥0.4，无候选时保留标题最靠前的五个子块所对应父章节。所有混合均用RRF(k=60)，单路最多60候选。正文与标题加权组为0.8/0.2。',
      '', '父章节去重会让同章的其他证据片段失去返回机会；取消去重也可能挤掉其他章节，因此同时报告跨条款覆盖和父级上下文覆盖，不能只挑一个上升指标。',
      '', '语料/证据/代码/查询向量哈希、每例排名、dev/test、按场景拆分、配对区间及耗时详见 summary.json 和逐方案 JSONL。标题筛选诊断见 gate_diagnostics.jsonl。',
      '', '## 复现与限制','', '`OPENBLAS_NUM_THREADS=1 .venv/bin/python scripts/ablate_legal_retrieval.py`','',
      '这不是端到端Agent评测。20例证据不足场景及拒答、澄清、抗干扰行为尚未进行回答级评审。测试集为合成业务场景，待专家核定；当前test已被查看，不作为独立盲测。耗时不含查询编码和网络，不用于宣称生产响应时间。']
    (out/'REPORT.md').write_text('\n'.join(lines)+'\n')
    print(json.dumps({'diagnostics':report['diagnostics'],'baseline_changed_top5_counts':regression,'output':str(out)},ensure_ascii=False),flush=True)
if __name__=='__main__':main()
