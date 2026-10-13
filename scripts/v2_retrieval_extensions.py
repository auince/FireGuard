"""Development-only component ablations; identical snapshot/candidate caps and no gold in model inputs."""
import json,time
from xfagent.v2.store import Store
from xfagent.v2.config import ROOT
from xfagent.v2.retrieval import Retrieval
from xfagent.v2.model import complete
from xfagent.legal_benchmark import load_benchmark,query_text,score_case,aggregate
s=Store();sid=s.active_snapshot();r=Retrieval(s);cases,gold,_=load_benchmark(ROOT/'benchmarks/legal_scenarios/v1');cases=[c for c in cases if c['split']=='dev']
out=ROOT/'reports/v2/retrieval';out.mkdir(parents=True,exist_ok=True);docs={d['doc_id']:d for d in s.db.documents.find({'snapshot_id':sid})}
variants=['base','rewrite','parent','memory','skill'];results={v:[] for v in variants}
path=out/'extensions-dev.jsonl';existing={}
if path.exists():existing={(x['variant'],x['id']):x for x in map(json.loads,path.read_text().splitlines()) if x['snapshot_id']==sid}
with path.open('w') as f:
 for c in cases:
  raw={**c,'input':{**c['input'],'history':[]}};q=query_text(raw);rewrite=None
  for v in variants:
   if (v,c['id']) in existing:row=existing[v,c['id']]
   else:
    queries=[q];parent=v=='parent';t=time.monotonic();warning=[]
    if v=='memory':queries=[query_text(c)]
    if v=='rewrite':
     try:
      obj=complete({'calls':0,'active_seconds':0},'把现场原话改写成最多2个规范术语法规检索问题，保留已知事实。返回{"queries":["..."]}。',{'query':q})
      queries += [str(x) for x in obj.get('queries',[])[:2]]
     except Exception as e:warning=[type(e).__name__]
    if v=='skill':queries=[q+' 消火栓 消防设施 维护管理']
    h=r.search(queries,sid,c['as_of'],'四川',mode='rerank',k=5,parent_expand=parent)
    normalized=[{**x,'id':x['legacy_id'],'source_sha256':x['source_hash']} for x in h['evidence']]
    row=score_case(c,normalized,gold,docs);row.update(variant=v,snapshot_id=sid,queries=queries,elapsed=time.monotonic()-t,warnings=warning+h['warnings'])
   results[v].append(row);f.write(json.dumps(row,ensure_ascii=False)+'\n');f.flush()
  print(c['id'],flush=True)
summary={'snapshot_id':sid,'split':'dev_only','cases':len(cases),'candidate_budget':{'bm25':20,'dense':40,'rrf_constant':60,'rerank_max':60,'output_k':5},
 'design':'each component added separately to no-history base; memory is supplied prior conversation only; parent affects contextual coverage, never child hit credit',
 'variants':{v:aggregate(rows) for v,rows in results.items()}}
(out/'extensions-dev-summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2))
