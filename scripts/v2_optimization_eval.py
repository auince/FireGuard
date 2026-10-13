"""Development-only optimization measurements; historical full baseline is immutable."""
import argparse,json,time,importlib.util,uuid
from concurrent.futures import ProcessPoolExecutor,as_completed
import numpy as np
from xfagent.v2.config import ROOT,MODEL
from xfagent.v2.store import Store,digest
from xfagent.v2.retrieval import Retrieval
from xfagent.v2.query_planning import hypothetical_hint
from xfagent.v2.replay_protocol import execution_hash
from xfagent.legal_benchmark import load_benchmark,query_text,score_case,aggregate
from v2_evaluate_system import run

OUT=ROOT/'reports/v2/optimization-20261004';OUT.mkdir(parents=True,exist_ok=True)
def write(name,obj):
    (OUT/name).write_text(json.dumps(obj,ensure_ascii=False,indent=2,default=str))

def performance(store):
    spec=importlib.util.spec_from_file_location('xfagent.v2.retrieval_baseline',ROOT/'runtime/v2/optimization-baseline/retrieval.py')
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    old=module.Retrieval(store);new=Retrieval(store);sid=store.active_snapshot()
    cases,_,_=load_benchmark(ROOT/'benchmarks/legal_scenarios/v1');cases=[c for c in cases if c['split']=='dev'][::5][:12]
    rows=[]
    for c in cases:
        q=query_text(c);queries=[q,'消防设施现场核查 '+q,'法规适用条件 '+q];row={'id':c['id']}
        for label,engine in [('baseline',old),('batched_cold',new),('batched_warm',new)]:
            if label=='batched_cold':new.embeddings.clear()
            t=time.monotonic();result=engine.search(queries,sid,c['as_of'],'四川',mode='rrf',k=5,parent_expand=True)
            row[label]={'seconds':time.monotonic()-t,'ids':[x['evidence_id'] for x in result['evidence']],
                        'warnings':result['warnings'],'telemetry':result.get('telemetry')}
        row['same_ranking']=row['baseline']['ids']==row['batched_cold']['ids']==row['batched_warm']['ids'];rows.append(row)
        print('retrieval performance',len(rows),'/',len(cases),flush=True)
    report={'cases':len(rows),'split':'dev','snapshot':sid,'query_count':3,'rows':rows,
            'same_rankings':sum(r['same_ranking'] for r in rows),'degraded_runs':sum(bool(r[l]['warnings']) for r in rows for l in ['baseline','batched_cold','batched_warm']),
            'median_seconds':{l:float(np.median([r[l]['seconds'] for r in rows])) for l in ['baseline','batched_cold','batched_warm']},
            'scope':'12 three-query retrieval requests; not end-to-end latency or production capacity'}
    write('retrieval-performance.json',report)

def hyde(store):
    sid=store.active_snapshot();engine=Retrieval(store);cases,evidence,_=load_benchmark(ROOT/'benchmarks/legal_scenarios/v1')
    cases=[c for c in cases if c['split']=='dev'][::5][:12];docs={d['doc_id']:d for d in store.db.documents.find({'snapshot_id':sid})};rows=[]
    for c in cases:
        q=query_text(c);state={'request':{'query':q,'scene':{}},'calls':0,'active_seconds':0}
        t=time.monotonic();hint=hypothetical_hint(state);generation=time.monotonic()-t
        row={'id':c['id'],'split':'dev','hypothesis':{'text':hint,'usable_as_evidence':False},'extra_model_calls':state['calls'],'generation_seconds':generation}
        for mode in ['rrf','hyde']:
            result=engine.search([q],sid,c['as_of'],'四川',mode=mode,k=5,parent_expand=True,dense_hint=hint if mode=='hyde' else None)
            hits=[{**h,'id':h['legacy_id'],'source_sha256':h['source_hash'],'score':h['rrf_score']} for h in result['evidence']]
            row[mode]=score_case(c,hits,evidence,docs);row[mode]['warnings']=result['warnings']
        rows.append(row);print('HyDE development',len(rows),'/',len(cases),flush=True)
    write('hyde-dev.json',{'snapshot':sid,'cases':len(cases),'rows':rows,'metrics':{m:aggregate([r[m] for r in rows]) for m in ['rrf','hyde']},
                         'default_enabled':False,'scope':'small development ablation, no holdout; extra LLM calls reported separately'})

def system(store):
    sid=store.active_snapshot();fingerprint=store.db.settings.find_one({'_id':'generator_fingerprint'})['value']
    cases=[c for c in map(json.loads,(ROOT/'benchmarks/inspection_scenarios/v2/cases.jsonl').read_text().splitlines()) if c['split']=='dev']
    selected=[]
    for facility in ['indoor_hydrant','outdoor_hydrant','fire_extinguisher']:
        group=[c for c in cases if c['facility']==facility];images=[c for c in group if c.get('image_path')][:2]
        text=[c for c in group if not c.get('image_path')];used=set();chosen=[]
        for c in text:
            if c['category'] not in used:chosen.append(c);used.add(c['category'])
            if len(chosen)==4:break
        selected+=images+chosen
    write('system-selection.json',{'case_ids':[c['id'] for c in selected],'split':'dev','execution_hash':execution_hash(),'frozen_before_execution':True})
    rows=[]
    with (OUT/'system-dev.jsonl').open('w') as out,ProcessPoolExecutor(max_workers=4) as pool:
        for f in as_completed([pool.submit(run,c,sid,fingerprint) for c in selected]):
            row=f.result();rows.append(row);out.write(json.dumps(row,ensure_ascii=False,default=str)+'\n');out.flush()
            print('system dev',len(rows),'/',len(selected),row['case_id'],flush=True)
    old={r['case_id']:r for r in map(json.loads,(ROOT/'reports/v2/system/all.jsonl').read_text().splitlines())}
    def summary(rs):
        return {'cases':len(rs),'execution_errors':sum('error' in r for r in rs),'program_constraint_pass':sum(all(r.get('program_checks',{'failed':False}).values()) for r in rs),
                'combined_verification_pass':sum(r.get('hard_verification',{}).get('passed') is True for r in rs),
                'model_supported':sum(r.get('model_semantic_review')=='model_supported' for r in rs),'expert_accuracy':None}
    write('system-dev-summary.json',{'before':summary([old[r['case_id']] for r in rows]),'after':summary(rows),
            'scope':'18 matched development cases, code changed; not new full-300 or expert accuracy','execution_hash':execution_hash()})

def replay(store):
    from xfagent.v2.policy import Policies
    from xfagent.v2.replay import run_replay
    policy=Policies(store).candidate({'name':'开发实验：现场核查术语扩展','trigger_terms':['照片'],'expand_terms':['消防设施维护']},'default','engineering-evaluator')
    sources=[x['run_id'] if 'run_id' in x else x['job']['id'] for x in json.loads((ROOT/'reports/v2/live/results.json').read_text())]
    result=run_replay(store,policy,sources,'default')
    report=store.db.evaluations.find_one({'_id':result['evaluation_id']})
    write('policy-replay.json',report);print('new paired replay',result['status'],result['gates'],flush=True)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('mode',choices=['performance','hyde','system','replay','all']);a=p.parse_args();s=Store()
    for name,fn in [('performance',performance),('hyde',hyde),('system',system),('replay',replay)]:
        if a.mode in [name,'all']:fn(s)
