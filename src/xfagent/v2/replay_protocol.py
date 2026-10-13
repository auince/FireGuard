"""Versioned release gates with paired regressions and explicit metric denominators."""
import hashlib,json
from pathlib import Path
import numpy as np

PROTOCOL='paired-engineering-v2.2'

def execution_hash():
    root=Path(__file__).parent
    return hashlib.sha256(''.join(p.name+hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(root.glob('*.py'))).encode()).hexdigest()

def retrieval_metrics(ids,gold):
    if gold is None:return None
    required=set(gold)
    if not required:return {'required_count':0,'hit@1':None,'hit@3':None,'hit@5':None,'recall@5':None,'all_evidence@5':None,'mrr':None}
    rank=next((i for i,e in enumerate(ids,1) if e in required),None)
    return {'required_count':len(required),**{'hit@'+str(k):int(bool(set(ids[:k])&required)) for k in [1,3,5]},
            'recall@5':len(set(ids[:5])&required)/len(required),'all_evidence@5':int(required<=set(ids[:5])),
            'mrr':1/rank if rank else 0}

def evaluate_pairs(results):
    def good(row):return not row.get('execution_error') and row.get('draft_present') and not row.get('hard_errors')
    summaries={}
    for label in ['control','treatment']:
        rows=[r[label] for r in results];count=len(rows)
        gold=[r['retrieval_metrics'] for r in rows if r.get('retrieval_metrics') and r['retrieval_metrics']['required_count']]
        summaries[label]={'cases':count,'execution_errors':sum(bool(r.get('execution_error')) for r in rows),
            'drafts':sum(bool(r.get('draft_present')) for r in rows),'verified_drafts':sum(bool(good(r)) for r in rows),
            'defect_cases':sum(bool(r.get('hard_errors')) for r in rows),'model_calls':sum(r.get('calls',0) for r in rows),
            'p50_seconds':float(np.percentile([r['elapsed'] for r in rows],50)) if rows else None,
            'p95_seconds':float(np.percentile([r['elapsed'] for r in rows],95)) if rows else None,
            'reviewed_retrieval_cases':len(gold),'retrieval':{k:sum(g[k] for g in gold)/len(gold) for k in ['hit@1','hit@3','hit@5','recall@5','all_evidence@5','mrr']} if gold else None,
            'expert_accuracy':None}
    regressions=[]
    for r in results:
        a,b=r['control'],r['treatment'];reasons=[]
        if good(a) and not good(b):reasons.append('previously_verified_now_failed')
        if a.get('semantic')=='model_supported' and b.get('semantic')!='model_supported':reasons.append('semantic_support_regressed')
        if a.get('retrieval_metrics') and b.get('retrieval_metrics'):
            for key in ['recall@5','all_evidence@5']:
                av=a['retrieval_metrics'][key];bv=b['retrieval_metrics'][key]
                if av is not None and bv is not None and bv<av:reasons.append(key+'_regressed')
        if reasons:regressions.append({'source_run_id':r['source_run_id'],'reasons':reasons})
    a,b=summaries['control'],summaries['treatment']
    gates={'actual_paired_execution':len(results)>=3 and all(r[l].get('draft_present') and r[l].get('calls',0)>0 and not r[l].get('execution_error') for r in results for l in ['control','treatment']),
        'no_new_paired_regressions':not regressions,'defect_count_not_increased':b['defect_cases']<=a['defect_cases'],
        'no_critical_citations':not any(e['code'] in ['forged_citation','source_mismatch'] for r in results for e in r['treatment'].get('hard_errors',[])),
        'latency_within_20_percent':bool(a['p95_seconds'] and b['p95_seconds']<=a['p95_seconds']*1.2),
        'candidate_actually_triggered':any(r['treatment'].get('policy',{}).get('triggered') for r in results)}
    return {'metrics':summaries,'regressions':regressions,'gates':gates,'passed':all(gates.values())}
