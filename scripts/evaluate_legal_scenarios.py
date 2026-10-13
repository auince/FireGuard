"""Frozen scenario retrieval evaluation, with batched identical query embeddings."""
import argparse,json,time
from pathlib import Path
import numpy as np
from xfagent.config import ROOT
from xfagent.retrieval import SearchIndex,embed
from xfagent.legal_benchmark import load_benchmark,query_text,score_case,aggregate,digest

def main():
    p=argparse.ArgumentParser();p.add_argument('--benchmark',type=Path,default=ROOT/'benchmarks/legal_scenarios/v1')
    p.add_argument('--output',type=Path,default=ROOT/'reports/legal_scenarios_v1')
    p.add_argument('--modes',nargs='+',default=['bm25','dense','hierarchical','weighted','hybrid'])
    p.add_argument('--split',choices=['dev','test','all'],default='all');a=p.parse_args()
    cases,evidence,manifest=load_benchmark(a.benchmark)
    if a.split!='all':cases=[c for c in cases if c['split']==a.split]
    idx=SearchIndex();a.output.mkdir(parents=True,exist_ok=True)
    for e in evidence.values():
        if idx.docs[e['doc_id']]['sha256']!=e['source_sha256']:raise ValueError('source changed; benchmark needs explicit new version')
    queries=[query_text(c) for c in cases];vectors=None
    if any(m!='bm25' for m in a.modes):
        batches=[]
        for start in range(0,len(queries),12):
            batches.append(embed(queries[start:start+12]));print(f'embedded {min(start+12,len(queries))}/{len(queries)}',flush=True)
        vectors=np.concatenate(batches)
    summaries={}; started=time.time()
    for mode in a.modes:
        result=[];ts=time.time()
        with (a.output/(mode+'.jsonl')).open('w') as f:
            for i,(c,q) in enumerate(zip(cases,queries)):
                hits=idx.search(q,k=5,mode=mode,as_of=c['as_of'],query_vector=None if vectors is None else vectors[i])
                row=score_case(c,hits,evidence,idx.docs)
                row['hits']=[{k:h[k] for k in ['id','doc_id','parent_id','article','score','source_url']} for h in hits]
                f.write(json.dumps(row,ensure_ascii=False)+'\n');result.append(row)
        summaries[mode]={'all':aggregate(result),'by_split':{s:aggregate([r for r in result if r['split']==s]) for s in ['dev','test']},
          'by_stage':{s:aggregate([r for r in result if r['stage']==s]) for s in sorted({r['stage'] for r in result})},
          'seconds_excluding_embedding':time.time()-ts}
        print(mode,json.dumps(summaries[mode]['all'],ensure_ascii=False),flush=True)
    report={'benchmark_manifest_sha256':digest(a.benchmark/'manifest.json'),'corpus_sha256':digest(idx.path/'corpus.json'),
      'index_arrays_sha256':{f:digest(idx.path/(f+'.npy')) for f in ['text','title'] if (idx.path/(f+'.npy')).exists()},
      'retrieval_source_sha256':digest(ROOT/'src/xfagent/retrieval.py'),'benchmark':manifest,'modes':summaries,
      'input_policy':'setting + observed facts + supplied user history + query; no gold, expected action, or target article provided',
      'gold_scope':'Closed seed evidence set: equivalent correct citations may be unlabelled. Parent context and child proposition reported separately.',
      'limitations':['Synthetic scenario suite pending expert review, not independent production accuracy.',
        'No generator invoked; 20 insufficient-answer cases and behavior assertions require answer-level review; no refusal success rate inferred.',
        'First joint dev/test baseline only; subsequent tuning must use dev. Previously viewed test results are not a blind holdout.'],
      'seconds_excluding_embedding':time.time()-started}
    (a.output/'summary.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    lines=['# 法规场景检索基线','',f"{len(cases)} 个用例；{manifest['scenario_families']} 个场景族。专家审定待完成。",'',
      '| 检索方式 | 子块证据 Recall@5 | 子块全证据@5 | 整章上下文全证据@5 | 子块 MRR | 时效违规用例 |',
      '|---|---:|---:|---:|---:|---:|']
    for m,s in summaries.items():
        v=s['all'];lines.append(f"| {m} | {v['child']['evidence_recall@5']:.2%} | {v['child']['all_evidence@5']:.2%} | {v['parent_context']['all_evidence@5']:.2%} | {v['child']['mrr']:.4f} | {v['temporal_violation_cases']} |")
    lines+=['','子块指标要求具体证据原文出现在返回片段中；整章指标要求其确实出现在返回的父级全文中。两者均核对文档版本与源文件哈希。同名法规命中不计分。',
      '', '分母仅含有标注证据的用例；无充分答案场景不混入召回率。20 个不足场景和所有业务行为断言尚未做生成回答评审，不能据此声称拒答正确率或端到端准确率。',
      '', '同场景分支按族隔离到 dev/test；当前为首次共同基线，test 已被查看，不再宣称盲测。后续优化仅使用 dev。',
      '', '原文对齐是自动核验，尚无消防专家审定；候选金标未穷尽等价合法条款。此结果用于工程回归，不替代真实应用性能。']
    (a.output/'REPORT.md').write_text('\n'.join(lines)+'\n')
if __name__=='__main__':main()
