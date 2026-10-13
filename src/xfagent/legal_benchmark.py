"""Scenario benchmark helpers. No language model judging and no gold in system input."""
import hashlib,json,re
from pathlib import Path

def normalize(s):return re.sub(r'\s+','',s)
def digest(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def query_text(case):
    inp=case['input']
    return '\n'.join(['业务日期：'+case['as_of'],'场所：'+inp['setting'],*inp['observations'],
       *[x['content'] for x in inp.get('history',[])],inp['query']])
def load_benchmark(path):
    p=Path(path);manifest=json.loads((p/'manifest.json').read_text())
    for name,sha in manifest['files'].items():
        if digest(p/name)!=sha:raise ValueError('benchmark checksum mismatch: '+name)
    cases=[json.loads(s) for s in (p/'cases.jsonl').read_text().splitlines() if s.strip()]
    evidence=json.loads((p/'evidence.json').read_text())
    assert len(cases)==manifest['cases'] and len({c['id'] for c in cases})==len(cases)
    groups={}
    for c in cases:
        groups.setdefault(c['family_id'],set()).add(c['split'])
        assert all(k in evidence for k in c['gold_evidence_ids'])
        for key in c['gold_evidence_ids']:
            e=evidence[key]
            assert e['effective_from']<=c['as_of'] and (not e['effective_until'] or c['as_of']<e['effective_until'])
    assert all(len(s)==1 for s in groups.values()),'scenario branches leak between splits'
    return cases,evidence,manifest

def evidence_present(hit, gold, field):
    # A document/parent ID match alone never receives credit.
    return hit['doc_id']==gold['doc_id'] and hit.get('source_sha256')==gold['source_sha256'] and normalize(gold['quote']) in normalize(hit.get(field,''))
def score_case(case,hits,evidence,docs):
    temporal_errors=[h['id'] for h in hits if
        (docs[h['doc_id']].get('effective_from') or '')>case['as_of'] or
        (docs[h['doc_id']].get('effective_until') and docs[h['doc_id']]['effective_until']<=case['as_of']) or
        h['doc_id'] in case.get('forbidden_doc_ids',[])]
    result={'id':case['id'],'scenario_id':case['scenario_id'],'family_id':case['family_id'],
      'split':case['split'],'stage':case['stage'],'category':case['category'],'as_of':case['as_of'],
      'hit_ids':[h['id'] for h in hits],'temporal_error_ids':temporal_errors,'behavior_score':None,
      'behavior_status':'not_run_requires_system_answer_and_review','evidence_count':len(case['gold_evidence_ids'])}
    gold=[evidence[x] for x in case['gold_evidence_ids']]
    for name,field in [('child','text'),('parent_context','parent_text')]:
        ranks=[next((i for i,h in enumerate(hits,1) if evidence_present(h,e,field)),None) for e in gold]
        if not gold:result[name]=None;continue
        value={'ranks':ranks,'mrr':max((1/r for r in ranks if r),default=0)}
        for k in [1,3,5]:
            covered=sum(r is not None and r<=k for r in ranks)
            value.update({f'evidence_recall@{k}':covered/len(gold),f'all_evidence@{k}':float(covered==len(gold)),f'any_hit@{k}':float(covered>0)})
        result[name]=value
    return result

def aggregate(results):
    out={'cases':len(results),'retrievable_cases':sum(r['evidence_count']>0 for r in results),
      'insufficient_answer_cases':sum(r['evidence_count']==0 for r in results),
      'temporal_violation_cases':sum(bool(r['temporal_error_ids']) for r in results),
      'behavior_accuracy':None,'behavior_status':'not_evaluated; retrieval hits cannot prove refusal or answer correctness'}
    for field in ['child','parent_context']:
        scored=[r for r in results if r[field] is not None]
        keys=[k for k in scored[0][field] if k!='ranks'] if scored else []
        out[field]={key:sum(r[field][key] for r in scored)/len(scored) for key in keys}
        families=sorted({r['family_id'] for r in scored})
        out[field]['family_macro_all_evidence@5']=sum(sum(r[field]['all_evidence@5'] for r in scored if r['family_id']==f)/sum(r['family_id']==f for r in scored) for f in families)/len(families) if families else None
    return out
