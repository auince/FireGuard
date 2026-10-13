"""Compare live v2 retrieval against the unchanged, source-aligned v1 gold."""
import argparse,json,time
from pathlib import Path
from xfagent.v2.config import ROOT
from xfagent.v2.store import Store,digest
from xfagent.v2.retrieval import Retrieval
from xfagent.legal_benchmark import load_benchmark,query_text,score_case,aggregate

p=argparse.ArgumentParser();p.add_argument('--split',choices=['all','dev','test'],default='all');p.add_argument('--modes',nargs='+',default=['bm25','dense','rrf','rerank']);a=p.parse_args()
s=Store();sid=s.active_snapshot();r=Retrieval(s)
cases,evidence,manifest=load_benchmark(ROOT/'benchmarks/legal_scenarios/v1')
if a.split!='all':cases=[c for c in cases if c['split']==a.split]
docs={d['doc_id']:d for d in s.db.documents.find({'snapshot_id':sid})}
out=ROOT/'reports/v2/retrieval';out.mkdir(parents=True,exist_ok=True)
summary={'snapshot_id':sid,'benchmark':'legal_scenarios/v1','cases':len(cases),'modes':{},
 'review_status':'source_aligned_expert_review_pending','holdout_status':'historical_test_previously_viewed',
 'input_policy':'same observed facts and supplied conversation; no gold or desired answer in queries'}
for mode in a.modes:
 rows=[];target=out/(mode+'-'+a.split+'.jsonl');existing={}
 if target.exists():existing={x['id']:x for x in [json.loads(l) for l in target.read_text().splitlines()] if x.get('snapshot_id')==sid}
 with target.open('w') as f:
  for i,c in enumerate(cases):
   if c['id'] in existing:row=existing[c['id']]
   else:
    t=time.monotonic();hits=r.search([query_text(c)],sid,c['as_of'],'四川',mode=mode,k=5,parent_expand=True)
    normalized=[]
    for h in hits['evidence']:
     normalized.append({**h,'id':h['legacy_id'],'source_sha256':h['source_hash'],'score':h.get('rerank_score',h['rrf_score'])})
    row=score_case(c,normalized,evidence,docs)
    row.update(snapshot_id=sid,elapsed=time.monotonic()-t,warnings=hits['warnings'],hits=[{'id':h['id'],'doc_id':h['doc_id'],'evidence_id':h['evidence_id']} for h in normalized])
   f.write(json.dumps(row,ensure_ascii=False)+'\n');f.flush();rows.append(row)
   if (i+1)%25==0:print(mode,i+1,'/',len(cases),flush=True)
 summary['modes'][mode]={'all':aggregate(rows),'dev':aggregate([x for x in rows if x['split']=='dev']),
   'test':aggregate([x for x in rows if x['split']=='test']),'seconds':sum(x['elapsed'] for x in rows),
   'degraded_cases':sum(bool(x['warnings']) for x in rows)}
 (out/('summary-'+a.split+'.json')).write_text(json.dumps(summary,ensure_ascii=False,indent=2))
 print(mode,json.dumps(summary['modes'][mode]['all'],ensure_ascii=False),flush=True)
