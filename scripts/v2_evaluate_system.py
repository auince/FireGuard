"""Frozen-input scenario executions with real 9B calls. Program checks and model judgments stay separate from expert gold."""
import argparse,json,time,uuid,hashlib,os
from pathlib import Path
from concurrent.futures import ProcessPoolExecutor,as_completed
from xfagent.v2.config import ROOT,MODEL
from xfagent.v2.store import Store,digest


def run(case,snapshot,fingerprint):
 import requests
 from PIL import Image
 from xfagent.v2.graphs import inspection_graph
 from xfagent.v2.verify import verify
 store=Store();request=dict(case['input']);request['retrieval_mode']='rrf'
 request['session_id']='eval-'+case['id'];rid='system-'+uuid.uuid4().hex
 if case.get('image_path'):
  raw=Path(case['image_path']).read_bytes();image=Image.open(case['image_path']).convert('RGB');image.thumbnail((1600,1600))
  folder=ROOT/'runtime/v2/benchmark-images';folder.mkdir(parents=True,exist_ok=True);target=folder/(case['image_sha256']+'.jpg');image.save(target,'JPEG',quality=92)
  request.update(processed_image_path=str(target),image_sha256=case['image_sha256'])
 memory={'working':{},'episodic':[],'preferences':[],'organization':[]}
 if case['category']=='follow_up':
  memory['working']={'facility':case['facility'],'last_query':'该设施前堆放杂物，已确认有遮挡现象。','confirmed_scene':request['scene']};request['query']='这个要怎么改？'
 if case['category']=='facility_switch':
  memory['working']={'facility':next(x for x in ['indoor_hydrant','outdoor_hydrant','fire_extinguisher'] if x!=case['facility']),
    'last_query':'上一个设施压力表损坏，观察编号old-o1。'}
 injected=[]
 if case['category']=='partial_failure':
  original=requests.post
  def post(url,*a,**kw):
   if ':8005' in url:raise requests.Timeout('scenario injected reranker outage')
   return original(url,*a,**kw)
  requests.post=post;request['retrieval_mode']='rerank';injected=['reranker_timeout']
 started=time.monotonic()
 try:
  result=inspection_graph(store).invoke({'run_id':rid,'owner':'scenario-evaluator','request':request,'snapshot_id':snapshot,
    'forced_policy':'baseline-v2','frozen_memory':memory,'calls':0,'active_seconds':0,'trace':[],'warnings':[]},
    {'configurable':{'thread_id':rid},'recursion_limit':70})
  result.pop('__interrupt__',None);report=result.get('report',{});v=report.get('verification',{})
  checks={'has_reviewable_draft':report.get('status')=='draft','not_auto_final':report.get('status')!='final',
    'calls_within_16':result.get('calls',0)<=16,'active_within_305_tolerance':result.get('active_seconds',0)<=305,
    'no_forged_citation_final_draft':not any(e['code'] in ['forged_citation','source_mismatch'] for e in v.get('errors',[])),
    'no_stale_observation_reference':all('old-o1' not in c.get('observation_ids',[]) for c in report.get('conclusions',[]))}
  if injected:checks['explicit_rrf_fallback']=any('reranker_unavailable' in w for w in result.get('warnings',[]))
  record={'case_id':case['id'],'family_id':case['family_id'],'split':case['split'],'facility':case['facility'],'category':case['category'],
    'snapshot_id':snapshot,'model':MODEL,'model_fingerprint':fingerprint,'run_id':rid,'elapsed':time.monotonic()-started,
    'program_checks':checks,'hard_verification':v,'model_semantic_review':v.get('semantic_review'),'expert_review':'pending',
    'fault_injection':injected,'calls':result.get('calls',0),'warnings':result.get('warnings',[]),'report':report}
 except Exception as exc:
  record={'case_id':case['id'],'split':case['split'],'facility':case['facility'],'snapshot_id':snapshot,'model_fingerprint':fingerprint,
   'error':type(exc).__name__+':'+str(exc)[:500],'expert_review':'pending','elapsed':time.monotonic()-started}
 if injected:requests.post=original
 store.db.benchmark_runs.update_one({'_id':rid},{'$set':record},upsert=True)
 return record

def main():
 parser=argparse.ArgumentParser();parser.add_argument('--split',default='all',choices=['all','dev','validation','holdout']);parser.add_argument('--workers',type=int,default=4);parser.add_argument('--limit',type=int);args=parser.parse_args()
 store=Store();sid=store.active_snapshot();fingerprint=(store.db.settings.find_one({'_id':'generator_fingerprint'}) or {}).get('value')
 cases=[c for c in map(json.loads,(ROOT/'benchmarks/inspection_scenarios/v2/cases.jsonl').read_text().splitlines()) if args.split=='all' or c['split']==args.split]
 if args.limit:cases=cases[:args.limit]
 out=ROOT/'reports/v2/system';out.mkdir(parents=True,exist_ok=True);path=out/(args.split+'.jsonl');existing={}
 if path.exists():existing={x['case_id']:x for x in map(json.loads,path.read_text().splitlines()) if x.get('snapshot_id')==sid and x.get('model_fingerprint')==fingerprint}
 missing=[c for c in cases if c['id'] not in existing];rows=list(existing.values())
 with path.open('a') as f, ProcessPoolExecutor(max_workers=args.workers) as pool:
  futures={pool.submit(run,c,sid,fingerprint):c['id'] for c in missing}
  for future in as_completed(futures):
   row=future.result();rows.append(row);f.write(json.dumps(row,ensure_ascii=False,default=str)+'\n');f.flush();print(len(rows),'/',len(cases),row['case_id'],round(row['elapsed'],1),flush=True)
 summary={'cases':len(rows),'snapshot_id':sid,'model_fingerprint':fingerprint,'model':MODEL,'split':args.split,'expert_review':'pending',
  'quality_accuracy':None,'interpretation':'程序约束检查与模型辅助核验，不是专业业务准确率','execution_errors':sum('error' in r for r in rows),
  'program_constraint_pass':sum(all(r.get('program_checks',{'execution':False}).values()) for r in rows),
  'hard_verification_pass':sum(r.get('hard_verification',{}).get('passed') is True for r in rows),
  'model_supported':sum(r.get('model_semantic_review')=='model_supported' for r in rows)}
 (out/(args.split+'-summary.json')).write_text(json.dumps(summary,ensure_ascii=False,indent=2))
if __name__=='__main__':main()
