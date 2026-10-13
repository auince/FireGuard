import uuid,time,json,copy
from pathlib import Path
from .replay_protocol import PROTOCOL,execution_hash,retrieval_metrics,evaluate_pairs
from .graphs import inspection_graph
from .store import digest
from .config import now,MODEL,ROOT
from .model_routes import manifest

def run_replay(store,policy_id,run_ids,project):
    p=store.db.policies.find_one({'_id':policy_id,'project_id':project})
    if not p:raise ValueError('unknown policy')
    if len(set(run_ids))<3 or len(set(run_ids))>60:raise ValueError('回放需3至60个开发任务')
    path=ROOT/'benchmarks/inspection_scenarios/v2/cases.jsonl'
    protected=[c for c in map(json.loads,path.read_text().splitlines()) if c['split']=='holdout'] if path.exists() else []
    protected_queries={c['input']['query'] for c in protected};protected_images={c.get('image_sha256') for c in protected if c.get('image_sha256')}
    g=inspection_graph(store);results=[];code_hash=execution_hash();routes_hash=digest(manifest())
    for source_id in dict.fromkeys(run_ids):
        source=store.db.jobs.find_one({'_id':source_id,'project_id':project,'kind':{'$in':['inspection','retrieval']}})
        if not source:raise ValueError('invalid source run')
        req=source['input']
        if req.get('query') in protected_queries or req.get('image_sha256') in protected_images:raise ValueError('最终验收样本不能用于策略回放')
        if source.get('benchmark_split',req.get('benchmark_split')) in ['test','holdout']:raise ValueError('禁止用最终验收集生成策略')
        fingerprint=source.get('result',{}).get('model_fingerprint')
        current=(store.db.settings.find_one({'_id':'generator_fingerprint'}) or {}).get('value')
        if not fingerprint or fingerprint!=current:raise ValueError('模型权重指纹变化，不能进行同模型策略对比')
        if source.get('result',{}).get('model_routes_hash')!=routes_hash:raise ValueError('源任务缺少同版本角色模型配置摘要，请先收集新 Trace')
        pinned=source.get('snapshot_id') or source.get('result',{}).get('snapshot_id')
        if not pinned:raise ValueError('source snapshot missing')
        frozen=copy.deepcopy(source.get('result',{}).get('memory',{}))
        input_hash=digest(req);image_path=req.get('processed_image_path')
        image_hash=digest(Path(image_path).read_bytes()) if image_path else None
        gold=store.db.replay_gold.find_one({'source_run_id':source_id,'input_hash':input_hash,'verified':True,'split':'dev'})
        row={'source_run_id':source_id,'snapshot_id':pinned,'input_hash':input_hash,'memory_hash':digest(frozen),
             'image_content_hash':image_hash,'model_fingerprint':current}
        for label,policy in [('control','baseline-v2'),('treatment',policy_id)]:
            rid='replay-'+uuid.uuid4().hex
            state={'run_id':rid,'owner':source['owner'],'request':copy.deepcopy(req),'snapshot_id':pinned,
                'forced_policy':policy,'frozen_memory':copy.deepcopy(frozen),'calls':0,'active_seconds':0,'trace':[],'warnings':[]}
            t=time.monotonic()
            try:
                if digest(manifest())!=routes_hash:raise ValueError('model role configuration changed during replay')
                if execution_hash()!=code_hash:raise ValueError('execution code changed during replay')
                if (store.db.settings.find_one({'_id':'generator_fingerprint'}) or {}).get('value')!=current:raise ValueError('model fingerprint changed')
                if image_path and digest(Path(image_path).read_bytes())!=image_hash:raise ValueError('source image changed')
                result=g.invoke(state,{'configurable':{'thread_id':rid},'recursion_limit':70})
                report=result.get('report',{});v=report.get('verification',{});ids=[e['evidence_id'] for e in result.get('evidence',[])]
                warnings=result.get('warnings',[])
                row[label]={'run_id':rid,'elapsed':time.monotonic()-t,'calls':result.get('calls',0),
                    'hard_errors':v.get('errors',[]),'semantic':v.get('semantic_review'),'warnings':warnings,
                    'draft_present':report.get('status')=='draft','execution_error':None if not any('Timeout' in w or 'HTTPError' in w for w in warnings) else 'model_or_tool_failure',
                    'queries':result.get('queries',[]),'evidence_ids':ids,'retrieval_metrics':retrieval_metrics(ids,gold['evidence_ids'] if gold else None),
                    'conclusions':report.get('conclusions',[]),'policy':result.get('policy',{})}
            except Exception as exc:
                row[label]={'run_id':rid,'elapsed':time.monotonic()-t,'calls':0,'hard_errors':[],
                            'execution_error':type(exc).__name__+':'+str(exc)[:300],'draft_present':False}
        results.append(row)
    verdict=evaluate_pairs(results)
    report={'_id':uuid.uuid4().hex,'policy_id':policy_id,'policy_hash':digest(p['spec']),'project_id':project,
        'status':'passed' if verdict['passed'] else 'failed','scope':'engineering_regression_not_expert_quality','professional_review':'pending',
        'protocol':PROTOCOL,'execution_hash':code_hash,'model_routes_hash':routes_hash,'model_fingerprint':current,
        'model_version':MODEL,'results':results,'created_at':now(),'control_defects':verdict['metrics']['control']['defect_cases'],
        'treatment_defects':verdict['metrics']['treatment']['defect_cases'],**verdict}
    store.db.evaluations.insert_one(report)
    return {'evaluation_id':report['_id'],'status':report['status'],'cases':len(results),'gates':verdict['gates']}
