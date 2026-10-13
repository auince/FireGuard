"""Validate, execute CPU retrieval, and run frozen-input live scenarios.

Defaults are read-only validation. Live calls require an explicit mode and do
not start services. Model references never become expert or production gold.
"""
import argparse
import copy
import hashlib
import json
import re
import time
from collections import Counter, defaultdict
from pathlib import Path
from unittest.mock import patch

def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def rows(path):return [json.loads(x) for x in Path(path).read_text().splitlines() if x.strip()]
def dump(path,x):Path(path).parent.mkdir(parents=True,exist_ok=True);Path(path).write_text(json.dumps(x,ensure_ascii=False,indent=2)+'\n')
def normal(text):return re.sub(r'[。；;\s]+$', '',text.strip())

def validate(suite, report):
 from xfagent.v2.schema import InspectionInput
 from xfagent.v2.store import Store
 manifest=json.loads((suite/'manifest.json').read_text());cases=rows(suite/'cases.jsonl');errors=[]
 for name,want in manifest['files'].items():
  if sha(suite/name)!=want:errors.append('hash:'+name)
 if len(cases)!=manifest['total_cases'] or len({r['id'] for r in cases})!=len(cases):errors.append('case_count_or_duplicate_id')
 families=defaultdict(set);images=defaultdict(set);image_seen={};image_count=0
 for r in cases:
  families[r['family_id']].add(r['split'])
  if r['suite']!='contract':
   try:InspectionInput.model_validate(r['input'])
   except Exception as e:errors.append(r['id']+':input:'+str(e)[:200])
  p=r['assets'].get('image_path')
  if p:
   h=r['assets']['image_sha256'];image_count+=1
   if p not in image_seen:image_seen[p]=sha(p)
   if image_seen[p]!=h:errors.append(r['id']+':image_hash')
   images[h].add(r['split'])
 for family,splits in families.items():
  if len(splits)>1:errors.append('family_split:'+family)
 for h,splits in images.items():
  if len(splits)>1:errors.append('image_split:'+h)
 for r in cases:
  if r['suite']=='visual' and r['input']['scene']:errors.append(r['id']+':visual_answer_leak')
  if any(k in r['input'] for k in ['expected','labels','gold','category','reference_answer']):errors.append(r['id']+':input_gold_leak')
  if r['suite']=='business':
   mask=r['expected']['evaluation_mask']
   if mask.get('retrieval_on_frozen_snapshot') and r['expected']['unindexed_reference_evidence']:errors.append(r['id']+':indexed_gold_missing')
   if r['source']['human_verified']:errors.append(r['id']+':mislabelled_expert_gold')
 # Read-only checks against frozen Mongo snapshots.
 store=Store();snapshots={r['snapshot_id'] for r in cases if 'snapshot_id' in r}
 for sid in snapshots:
  if not store.db.snapshots.find_one({'_id':sid,'state':'published'}):errors.append('snapshot_not_published:'+sid)
 report_value={'status':'passed' if not errors else 'failed','cases':len(cases),'counts':dict(Counter(r['suite'] for r in cases)),
     'errors':errors,'image_rows_verified':image_count,'unique_image_files_verified':len(image_seen),
     'frozen_snapshots':sorted(snapshots),'production_writes':0,'live_model_executions':0}
 dump(report,report_value);return report_value

def run_rag(suite, report, limit, split):
 from xfagent.v2.store import Store
 from xfagent.v2.retrieval import Retrieval
 from xfagent.legal_benchmark import score_case,aggregate
 cases=[r for r in rows(suite/'rag.jsonl') if split=='all' or r['split']==split]
 if limit:cases=cases[:limit]
 evidence=json.loads((suite/'rag-evidence.json').read_text());store=Store();retriever=Retrieval(store)
 documents={};records=[]
 for c in cases:
  sid=c['snapshot_id']
  if sid not in documents:documents[sid]={d['doc_id']:d for d in store.db.documents.find({'snapshot_id':sid})}
  t=time.monotonic();q=c['input']
  try:
   result=retriever.search([q['query']],sid,q['as_of'],q['jurisdiction'],mode='bm25',k=5,parent_expand=True)
   hits=[{**e,'id':e['legacy_id'],'source_sha256':e['source_hash']} for e in result['evidence']]
   legacy={'id':c['id'],'scenario_id':c['source']['case_id'],'family_id':c['family_id'],'split':c['split'],
      'stage':'enhanced_retrieval','category':'legacy','as_of':q['as_of'],
      'gold_evidence_ids':c['expected']['legacy_evidence_ids'],'forbidden_doc_ids':c['expected']['forbidden_doc_ids']}
   value=score_case(legacy,hits,evidence,documents[sid]);value.update(snapshot_id=sid,elapsed=time.monotonic()-t,warnings=result['warnings'])
   value['source_kind']=c['oracle_kind'];records.append(value)
  except Exception as exc:records.append({'id':c['id'],'error':str(exc),'snapshot_id':sid})
  if len(records)%25==0:print('RAG',len(records),'/',len(cases),flush=True)
 good=[r for r in records if 'error' not in r]
 value={'mode':'cpu_bm25','cases':len(records),'execution_errors':len(records)-len(good),'snapshot_ids':sorted(documents),
        'metrics':aggregate(good) if good else None,'records':records,'production_writes':0,
        'note':'Historical frozen snapshot paired with its original evidence truth; regression only, not current-law deployment guidance.'}
 dump(report,value);return {k:v for k,v in value.items() if k!='records'}

def retrieval_group_metrics(ids, groups):
 """Each requirement can be satisfied by any of its valid alternatives."""
 groups=[set(g['any_of']) for g in groups if g.get('any_of')]
 if not groups:return None
 return {'requirement_groups':len(groups),'group_recall@5':sum(bool(g&set(ids[:5])) for g in groups)/len(groups),
         'all_groups@5':all(g&set(ids[:5]) for g in groups),
         'hit@1':any(g&set(ids[:1]) for g in groups)}

def score_output(case,result,vocabulary=None):
 report=result.get('report',{});v=report.get('verification',{});trace=result.get('trace',[])
 checks={'reviewable_draft':report.get('status')=='draft','not_auto_final':report.get('status')!='final',
         'calls_within_16':result.get('calls',0)<=16,'retrieval_rounds_within_2':result.get('retrieval_rounds',0)<=2,
         'rewrites_within_2':result.get('rewrites',0)<=2,'active_within_305_tolerance':result.get('active_seconds',0)<=305,
         'no_stale_observation_reference':all('old-o1' not in c.get('observation_ids',[]) for c in report.get('conclusions',[]))}
 value={'program_checks':checks,'verification':v,'semantic_correctness':None,'expert_accuracy':None,
        'semantic_review_required':True,'model_semantic_review':v.get('semantic_review'),'trace':trace}
 if case['suite']=='visual':
  aliases={normal(text):item['id'] for item in vocabulary or [] for text in [item['text'],*item.get('aliases',[])]}
  raw={normal(x) for o in result.get('observations',[]) for x in o.get('labels',[])}
  predicted={aliases[x] for x in raw if x in aliases};unmapped=sorted(x for x in raw if x not in aliases)
  expected=set(case['expected']['label_ids']);tp=len(predicted&expected);scorable=not unmapped
  states=[o.get('status') for o in result.get('observations',[])]
  actual='visible_anomaly' if 'visible_anomaly' in states else ('uncertain' if 'uncertain' in states or not states else 'no_visible_anomaly')
  value['visual']={'expected':case['expected']['visual_status'],'actual':actual,'status_match':actual==case['expected']['visual_status'],
     'true_positive_labels':tp if scorable else None,'false_positive_labels':len(predicted-expected) if scorable else None,
     'false_negative_labels':len(expected-predicted) if scorable else None,
     'exact_label_match':predicted==expected if scorable else None,'predicted_label_ids':sorted(predicted),
     'unmapped_labels_require_review':unmapped,'label_metric_eligible':scorable,
     'scope_accuracy':None,'scope_note':'v2 does not emit the old explicit scope field; never infer a score from gold.'}
 else:
  mask=case['expected']['evaluation_mask'];ids=[e['evidence_id'] for e in result.get('evidence',[])]
  value['evaluation_mask']=mask
  value['retrieval']=retrieval_group_metrics(ids,case['expected']['evidence_requirements']) if mask.get('retrieval_on_frozen_snapshot') else None
  states=[o.get('status') for o in result.get('observations',[])]
  actual='abnormal' if 'visible_anomaly' in states else ('uncertain' if 'uncertain' in states or not states else 'normal')
  value['visual']={'actual':actual,'expected':case['expected']['visual_decision'],
    'binary_match':actual==case['expected']['visual_decision'] if mask.get('visual_binary') else None,
    'three_state_match':actual==case['expected']['visual_decision'] if mask.get('visual_uncertainty') else None}
  if 'reranker_timeout' in case.get('context',{}).get('fault_injection',[]):
   checks['explicit_rerank_fallback']=any(w.startswith('reranker_unavailable') for w in result.get('warnings',[]))
 return value

def run_live(suite, report, subset, split, limit):
 import requests
 from PIL import Image
 from xfagent.v2.config import MODEL_URL,MODEL,ROOT
 from xfagent.v2.store import Store
 from xfagent.v2.graphs import inspection_graph
 from xfagent.v2.replay_protocol import execution_hash
 if split=='holdout':raise ValueError('Holdout is reserved; use a separate final-acceptance run after freezing all parameters.')
 cases=[r for r in rows(suite/(subset+'.jsonl')) if r['split']==split]
 if not cases:raise ValueError('No cases in requested split')
 if limit:cases=cases[:limit]
 # Do not launch or change services if resources are occupied.
 response=requests.get(MODEL_URL+'/models',timeout=(3,5));response.raise_for_status()
 if MODEL not in {m['id'] for m in response.json().get('data',[])}:raise ValueError('Configured model is not advertised by the inference service')
 store=Store();temp_name='xfagent_coverage_live_'+__import__('uuid').uuid4().hex;temp=Store(name=temp_name)
 records=[];frozen_hash=execution_hash();fingerprint=(store.db.settings.find_one({'_id':'generator_fingerprint'}) or {}).get('value')
 if not fingerprint:raise ValueError('Missing model fingerprint')
 snapshots={c.get('snapshot_id',store.active_snapshot()) for c in cases}
 try:
  temp.setup()
  for collection in ['documents','evidence','evidence_locations','source_units','snapshots']:
   for d in store.db[collection].find({'snapshot_id':{'$in':list(snapshots)}} if collection!='snapshots' else {'_id':{'$in':list(snapshots)}}):
    temp.db[collection].replace_one({'_id':d['_id']},d,upsert=True)
  baseline=store.db.policies.find_one({'_id':'baseline-v2'});temp.db.policies.insert_one(baseline)
  temp.db.settings.insert_one({'_id':'generator_fingerprint','value':fingerprint})
  graph=inspection_graph(temp);vocabulary=json.loads((suite/'label-vocabulary.json').read_text())
  images=ROOT/'runtime/v2/coverage-images';images.mkdir(parents=True,exist_ok=True)
  for c in cases:
   if execution_hash()!=frozen_hash:raise ValueError('Production execution code changed during the experiment')
   if (store.db.settings.find_one({'_id':'generator_fingerprint'}) or {}).get('value')!=fingerprint:raise ValueError('Model fingerprint changed')
   inp=copy.deepcopy(c['input']);path=c['assets'].get('image_path');rid='coverage-live-'+__import__('uuid').uuid4().hex
   if path:
    if sha(path)!=c['assets']['image_sha256']:raise ValueError('Source image changed: '+c['id'])
    with Image.open(path) as im:
     im=im.convert('RGB');im.thumbnail((1600,1600));target=images/(c['assets']['image_sha256']+'.jpg');im.save(target,'JPEG',quality=92)
    inp.update(processed_image_path=str(target),image_sha256=c['assets']['image_sha256'])
   ctx=c.get('context',{});sid=c.get('snapshot_id',store.active_snapshot());t=time.monotonic()
   original_post=requests.post
   def post(url,*a,**k):
    if 'reranker_timeout' in ctx.get('fault_injection',[]) and ':8005' in url:raise requests.Timeout('coverage injected reranker outage')
    return original_post(url,*a,**k)
   try:
    with patch('requests.post',side_effect=post):
     result=graph.invoke({'run_id':rid,'owner':'coverage-evaluator','request':inp,'snapshot_id':sid,'forced_policy':'baseline-v2',
         'frozen_memory':copy.deepcopy(ctx.get('frozen_memory',{'working':{},'episodic':[],'preferences':[],'organization':[]})),
         'calls':0,'active_seconds':0,'trace':[],'warnings':[]},{'configurable':{'thread_id':rid},'recursion_limit':70})
    result.pop('__interrupt__',None)
    record={'id':c['id'],'split':c['split'],'snapshot_id':sid,'input_hash':digest_safe(inp),'model_fingerprint':fingerprint,
      'execution_hash':frozen_hash,'elapsed':time.monotonic()-t,'calls':result.get('calls',0),**score_output(c,result,vocabulary),'report':result.get('report')}
   except Exception as exc:record={'id':c['id'],'error':type(exc).__name__+':'+str(exc),'elapsed':time.monotonic()-t}
   records.append(record);dump(report,{'status':'running','records':records});print('LIVE',len(records),'/',len(cases),c['id'],flush=True)
  value={'status':'complete','cases':len(records),'errors':sum('error' in r for r in records),'records':records,'production_mongo_writes':0,
      'temporary_database':temp_name,'expert_accuracy':None,'semantic_correctness':None,'note':'Program scores and model-reference visual/retrieval scores; semantic review remains separate.'}
  dump(report,value);return {k:v for k,v in value.items() if k!='records'}
 finally:
  assert temp.db.name==temp_name and temp_name.startswith('xfagent_coverage_live_')
  temp.client.drop_database(temp_name);temp.client.close()

def digest_safe(value):return hashlib.sha256(json.dumps(value,ensure_ascii=False,sort_keys=True).encode()).hexdigest()

def run_load(suite,report,base_url,concurrency,samples,repetitions,warmup):
 """Explicit API load mode. Run on an isolated deployment/project with its own token."""
 import os,uuid,base64
 import requests
 import numpy as np
 from datetime import datetime
 from concurrent.futures import ThreadPoolExecutor
 token=os.environ.get('XF_COVERAGE_BEARER');project=os.environ.get('XF_COVERAGE_PROJECT')
 if not token or not project:raise ValueError('Set XF_COVERAGE_BEARER and XF_COVERAGE_PROJECT for an isolated load environment.')
 if samples<1 or repetitions<1 or any(n<1 or n>32 for n in concurrency):raise ValueError('Invalid load parameters')
 selected=[c for c in rows(suite/'business.jsonl') if c['split']=='dev' and c['assets'].get('image_path')
           and not c['context'].get('fault_injection') and not c['context']['frozen_memory'].get('working')]
 grouped=defaultdict(list)
 for c in selected:grouped[c['input']['facility']].append(c)
 if len(grouped)!=3:raise ValueError('Load data must include three facilities')
 balanced=[]
 for i in range(max(len(v) for v in grouped.values())):
  for facility in sorted(grouped):balanced.append(grouped[facility][i%len(grouped[facility])])
 headers={'Authorization':'Bearer '+token};image_data={}
 for c in balanced:
  path=c['assets']['image_path']
  if path not in image_data:
   if sha(path)!=c['assets']['image_sha256']:raise ValueError('Load source image changed')
   image_data[path]='data:image/jpeg;base64,'+base64.b64encode(Path(path).read_bytes()).decode()
 run_group='coverage-load-'+uuid.uuid4().hex
 def one(i):
  c=balanced[i%len(balanced)];body=copy.deepcopy(c['input']);body['project_id']=project
  body['session_id']=run_group+'-'+uuid.uuid4().hex;body['image']=image_data[c['assets']['image_path']]
  start=time.monotonic();jobid=None
  try:
   h={**headers,'Idempotency-Key':body['session_id']}
   r=requests.post(base_url+'/api/inspect',headers=h,json=body,timeout=(3,30));r.raise_for_status();jobid=r.json()['id']
   deadline=start+1800
   while True:
    response=requests.get(base_url+'/api/jobs/'+jobid,headers=headers,timeout=(3,10));response.raise_for_status();job=response.json()
    if job['status'] not in ['running','queued']:break
    if time.monotonic()>=deadline:raise TimeoutError('task did not produce a draft within 1800 seconds')
    time.sleep(1)
   result=job.get('result',{})
   parse=lambda x:datetime.fromisoformat(x.replace('Z','+00:00'))
   queue=(parse(job['started_at'])-parse(job['created_at'])).total_seconds() if job.get('started_at') else None
   return {'case_id':c['id'],'facility':body['facility'],'job_id':jobid,'status':job['status'],
      'end_to_end_seconds':time.monotonic()-start,'queue_seconds':queue,'active_seconds':result.get('active_seconds'),
      'calls':result.get('calls'),'usage':result.get('usage'),'snapshot_id':job.get('snapshot_id'),
      'model_fingerprint':result.get('model_fingerprint'),'execution_version':result.get('execution_version'),
      'failed':job['status']=='failed'}
  except Exception as exc:return {'case_id':c['id'],'job_id':jobid,'failed':True,'error':type(exc).__name__+':'+str(exc),
                                'end_to_end_seconds':time.monotonic()-start}
 warmup_rows=[one(i) for i in range(warmup)]
 output={'mode':'real_api_load','run_group':run_group,'base_url':base_url,'project_id':project,
   'warmup_excluded_from_metrics':warmup_rows,'samples_per_level_per_repetition':samples,'repetitions':repetitions,
   'completion_boundary':'first reviewable draft, excludes human waiting','levels':[],'expert_accuracy':None}
 for repetition in range(repetitions):
  for n in concurrency:
   started=time.monotonic()
   with ThreadPoolExecutor(max_workers=n) as pool:records=list(pool.map(one,range(samples)))
   elapsed=time.monotonic()-started;successful=[r for r in records if not r['failed']]
   values=[r['end_to_end_seconds'] for r in successful]
   output['levels'].append({'concurrency':n,'repetition':repetition+1,'samples':len(records),
       'successful':len(successful),'failure_rate':1-len(successful)/len(records),
       'throughput_per_minute':len(successful)/elapsed*60,'p50_seconds':float(np.percentile(values,50)) if values else None,
       'p95_seconds':float(np.percentile(values,95)) if values else None,'records':records,
       'measurement_boundary':'client-observed time to draft; queue and active time also retained'})
   dump(report,output);print('LOAD',repetition+1,n,len(successful),'/',samples,flush=True)
 output['status']='complete';dump(report,output)
 return {k:v for k,v in output.items() if k not in ['levels','warmup_excluded_from_metrics']}

if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--suite',type=Path,default=Path('benchmarks/coverage_v1'));p.add_argument('--mode',choices=['validate','rag','live','load'],default='validate');p.add_argument('--subset',choices=['visual','business'],default='business');p.add_argument('--split',default='dev');p.add_argument('--limit',type=int);p.add_argument('--report',type=Path,required=True)
 p.add_argument('--base-url',default='http://127.0.0.1:8080');p.add_argument('--concurrency',default='1,2,4,8');p.add_argument('--load-samples',type=int,default=100);p.add_argument('--load-repetitions',type=int,default=3);p.add_argument('--warmup',type=int,default=10)
 a=p.parse_args()
 if a.mode=='validate':r=validate(a.suite,a.report)
 elif a.mode=='rag':r=run_rag(a.suite,a.report,a.limit,a.split)
 elif a.mode=='live':r=run_live(a.suite,a.report,a.subset,a.split,a.limit)
 else:r=run_load(a.suite,a.report,a.base_url,[int(n) for n in a.concurrency.split(',')],a.load_samples,a.load_repetitions,a.warmup)
 print(json.dumps(r,ensure_ascii=False,indent=2))
 if r.get('status')=='failed' or r.get('execution_errors',0):raise SystemExit(1)
