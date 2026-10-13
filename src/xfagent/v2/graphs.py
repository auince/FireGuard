"""All probabilistic nodes execute within bounded, persistent LangGraph workflows."""
import json,time,copy
from typing import TypedDict,Any
import requests
from langgraph.graph import StateGraph,START,END
from langgraph.types import interrupt
from langgraph.checkpoint.mongodb import MongoDBSaver
from .config import FACILITIES,MODEL,now
from .schema import Observation,Conclusion
from .model import complete,BudgetExhausted
from .call_ledger import node_scope
from .model_routes import resolve,manifest
from .store import digest
from .memory import MemoryContextBuilder
from .policy import Policies
from .retrieval import Retrieval
from .verify import verify
from .query_planning import multi_queries,hypothetical_hint

class State(TypedDict,total=False):
    run_id:str;owner:str;execution_worker:str;request:dict;snapshot_id:str;model_version:str;model_fingerprint:str;policy:dict;execution_version:str
    facility:str;memory:dict;frozen_memory:dict;similar_cases:list;observations:list;detector:dict;queries:list;evidence:list
    conclusions:list;context_gaps:list;verification:dict;report:dict;trace:list;warnings:list
    calls:int;usage:dict;active_seconds:float;retrieval_rounds:int;rewrites:int
    exhausted:bool;review:dict;status:str;forced_policy:str;semantic:dict;retrieval_telemetry:dict;retrieval_hint:dict;model_routes:dict;model_routes_hash:str

def verification_route(s):
    verification=s.get('verification',{})
    if s.get('exhausted') or verification.get('passed'):return 'review_ready'
    codes={e['code'] for e in verification.get('errors',[])}
    if codes & {'unknown_applicability','uncertain_observation','unmeasured_fact','inapplicable_evidence','semantic_verification_unavailable','measurement_value_mismatch','invalid_measurement_fact'}:
        return 'review_ready'
    if (not s.get('evidence') or codes & {'source_mismatch','missing_evidence'}) and s.get('retrieval_rounds',0)<2:
        return 'rewrite'
    return 'repair' if s.get('rewrites',0)<2 else 'review_ready'

class LeaseLost(RuntimeError):pass

def require_lease(store,s):
    if s.get('execution_worker'):
        job=store.db.jobs.find_one({'_id':s['run_id']},{'worker':1,'status':1,'lease_until':1})
        if not job or job.get('worker')!=s['execution_worker'] or job.get('status')!='running' or (job.get('lease_until') and job['lease_until']<=now()):raise LeaseLost('worker lease ownership changed')

def safe_node(store,name,fn):
    def wrapped(original):
        s=copy.deepcopy(original);require_lease(store,s);t=time.monotonic();s['_node_start']=t
        initial_calls=s.get('calls',0);initial_warnings=len(s.get('warnings',[]));outcome='ok'
        try:
            if s.get('active_seconds',0)>=300 and name not in ['review_ready','verify']:raise BudgetExhausted('active_time_limit')
            with node_scope(store,s,name):
                values=fn(s) or {}
        except Exception as exc:
            outcome='budget_exhausted' if isinstance(exc,BudgetExhausted) else 'error'
            values={'warnings':s.get('warnings',[])+[name+':'+type(exc).__name__+':'+str(exc)[:180]]}
            if isinstance(exc,BudgetExhausted):values['exhausted']=True
            if name in ['verify','finalize']:values['verification']={'passed':False,'errors':[{'code':'semantic_verification_unavailable'}],
                'missing_fields':[],'semantic_review':'unavailable','professional_review':'pending'}
        require_lease(store,s)
        elapsed=time.monotonic()-t
        values.setdefault('warnings',s.get('warnings',[]));values['context_gaps']=s.get('context_gaps',[])
        values.update(calls=s.get('calls',0),usage=s.get('usage',{}),active_seconds=s.get('active_seconds',0)+elapsed)
        if values['active_seconds']>=300:values['exhausted']=True
        event={'node':name,'seconds':round(elapsed,3),'calls':s.get('calls',0),'at':now().isoformat(),
               'calls_delta':s.get('calls',0)-initial_calls,'outcome':outcome,
               'warnings':values.get('warnings',[])[initial_warnings:]}
        event['degraded']=bool(event['warnings'])
        event['project_id']=s.get('request',{}).get('project_id');event['owner']=s.get('owner')
        event['execution_version']='2.2'
        values['trace']=s.get('trace',[])+[event]
        store.audit(s['run_id'],str(len(s.get('trace',[])))+':'+name,'node_complete',**event)
        return values
    return wrapped

def image_data(req):
    import base64
    from pathlib import Path
    if not req.get('processed_image_path'):return None
    return 'data:image/jpeg;base64,'+base64.b64encode(Path(req['processed_image_path']).read_bytes()).decode()

CHECKS={
 'indoor_hydrant':['组件是否可见或缺失','箱门标识与遮挡','软管弯折与栓口方向'],
 'outdoor_hydrant':['本体是否能确认','圈占遮挡与取用空间','破损锈蚀与标识'],
 'fire_extinguisher':['压力表是否清晰及指针区域','喷管压把与瓶体外观','遮挡与取用；不得凭单图判断应配数量']}

def facility_graph(store,facility):
    def detect(s):
        from xfagent.evidence_vision import VisionEvidence
        req={**s['request'],'image':image_data(s['request'])}
        value=VisionEvidence().analyze(req,facility,time.monotonic()+max(.1,300-s.get('active_seconds',0)))
        value['warnings']=s.get('warnings',[])+value['warnings']
        return value
    def observe(s):
        im=image_data(s['request'])
        if not im:return {'observations':[]}
        obj=complete(s,'分析图片，最多输出4条观察，每条description不超过80字，labels最多3项；如对应已有检测框，可填写detector_id（如d1），不得编造框。输出 {"observations":[{"status":"visible_anomaly|no_visible_anomaly|uncertain","description":"可见依据","labels":[]}]}。不可见不等于缺失。检测框只用于定位，不是隐患结论。',
            {'facility':FACILITIES[facility],'checks':CHECKS[facility],'scene':s['request']['scene'],
             'query':s['request']['query'],'detections':s.get('detector',{})},im,role='vision')
        rows=[];regions={d.get('detector_id'):d.get('bboxNorm') for d in s.get('detector',{}).get('detections',[])}
        for i,o in enumerate(obj.get('observations',[])[:8]):
            rows.append(Observation(observation_id=f'o{i+1}',image_id=s['request'].get('image_sha256'),facility=facility,
                status=o['status'],description=o['description'],labels=o.get('labels',[]),region=regions.get(o.get('detector_id'))).model_dump())
        if not rows:raise ValueError('empty observations')
        return {'observations':rows}
    def specialist(s):
        if not s.get('observations'):return {}
        obj=complete(s,'专项复核图像观察。输出 {"corrections":[{"observation_id":"o1","status":"uncertain","description":"理由"}]}。只修正存在的观察；不新增未经测量的数值。',
            {'checks':CHECKS[facility],'observations':s['observations']},image_data(s['request']),role='vision')
        rows=copy.deepcopy(s['observations']);byid={r['observation_id']:r for r in rows}
        for fix in obj.get('corrections',[]):
            if fix.get('observation_id') in byid and fix.get('status') in ['uncertain','visible_anomaly','no_visible_anomaly']:
                byid[fix['observation_id']].update(status=fix['status'],description=str(fix.get('description','需人工复核'))[:1500])
        return {'observations':rows}
    g=StateGraph(State)
    for name,fn in [('detector',detect),('observe',observe),('specialist',specialist)]:g.add_node(name,safe_node(store,facility+':'+name,fn))
    g.add_edge(START,'detector');g.add_edge('detector','observe');g.add_edge('observe','specialist');g.add_edge('specialist',END)
    return g.compile()

def inspection_graph(store,checkpointer=True):
    memory=MemoryContextBuilder(store);policies=Policies(store);retriever=Retrieval(store)
    def context(s):
        r=s['request']
        context=s['frozen_memory'] if 'frozen_memory' in s else memory.build(s['owner'],r['project_id'],r['session_id'],s['snapshot_id'],r['as_of'],r['jurisdiction'])
        return {'memory':context,'warnings':s.get('warnings',[])+context.get('warnings',[]),
                'execution_version':'2.2','model_routes':manifest(),'model_routes_hash':digest(manifest()),'model_version':MODEL,
                'model_fingerprint':(store.db.settings.find_one({'_id':'generator_fingerprint'}) or {}).get('value','unavailable')}
    def intent(s):
        r=s['request'];facility=r.get('facility','auto')
        if facility=='auto':
            matches=[k for k,v in FACILITIES.items() if v in r['query']]
            facility=matches[0] if len(matches)==1 else None
            if facility is None and r.get('use_model',True):
                obj=complete(s,'识别本次主要设施与任务意图，只返回 {"facility":"indoor_hydrant|outdoor_hydrant|fire_extinguisher|unknown"}。新图片优先于旧会话。',
                    {'query':r['query'],'last_context':s.get('memory',{}).get('working',{})},
                    image_data(r) if resolve('intent')['supports_images'] else None,role='intent')
                facility=obj.get('facility')
            facility=facility if facility in FACILITIES else 'unknown'
        pol=policies.choose(s['owner'],r['project_id'],r['session_id'],r['query'],facility,s.get('forced_policy'))
        return {'facility':facility,'policy':pol}
    def rewrite(s):
        r=s['request'];queries=[r['query']]
        working=s.get('memory',{}).get('working',{})
        if (working.get('facility') and working['facility']!=s.get('facility')) or r.get('processed_image_path'):working={}
        if r.get('use_model',True) and not s.get('exhausted'):
            obj=complete(s,'结合已确认设施、原话及上下文生成最多2条独立法规检索问题，保持日期、地域及条件，不引入猜测。输出 {"queries":["..."]}。',
                {'query':r['query'],'facility':s.get('facility'),'observations':s.get('observations',[]),
                 'working':working,'scene':r['scene'],'prior_evidence_missing':s.get('retrieval_rounds',0)>0},role='rewrite')
            queries.extend(str(q)[:400] for q in obj.get('queries',[])[:2] if isinstance(q,str))
        p=s.get('policy',{});spec=p.get('spec',{})
        if p.get('triggered') and not (spec.get('kind')=='hook' and spec.get('hook')=='before_draft') and spec.get('expand_terms'):queries[0]+=' '+' '.join(spec['expand_terms'])
        if p.get('triggered'):
            store.audit(s['run_id'],'strategy-application','strategy_applied',kind=spec.get('kind'),hook=spec.get('hook'),
                evidence_k=spec.get('evidence_k'),parent_expand=spec.get('parent_expand'),query_before=r['query'],query_after=queries[0])
        if r.get('query_strategy')=='multi':queries=multi_queries(queries[0],s.get('facility'),r['scene'],working,queries[1:])
        hint={}
        if r.get('retrieval_mode')=='hyde' and r.get('use_model',True) and not s.get('exhausted'):
            try:hint={'text':hypothetical_hint(s),'authority':'retrieval_hypothesis_only','usable_as_evidence':False}
            except BudgetExhausted:raise
            except Exception as exc:s.setdefault('warnings',[]).append('hyde_unavailable:'+type(exc).__name__)
        return {'queries':list(dict.fromkeys(queries))[:3],'retrieval_hint':hint}
    def retrieve(s):
        if s.get('retrieval_rounds',0)>=2:return {'warnings':s.get('warnings',[])+['max_retrieval_rounds_reached']}
        r=s['request'];spec=s.get('policy',{}).get('spec',{}) if s.get('policy',{}).get('triggered') else {}
        result=retriever.search(s.get('queries') or [r['query']],s['snapshot_id'],r['as_of'],r['jurisdiction'],
            mode=r.get('retrieval_mode','rrf'),k=spec.get('evidence_k',5),parent_expand=spec.get('parent_expand',False),
            deadline=time.monotonic()+max(.1,300-s.get('active_seconds',0)),dense_hint=s.get('retrieval_hint',{}).get('text'))
        return {'evidence':result['evidence'],'queries':result['queries'],'retrieval_rounds':s.get('retrieval_rounds',0)+1,
                'warnings':s.get('warnings',[])+result['warnings'],'retrieval_telemetry':result.get('telemetry',{})}
    def fallback(s):
        rows=[Conclusion(claim_id='c'+str(i+1),text=o['description'],observation_ids=[o['observation_id']],
                kind='observation').model_dump() for i,o in enumerate(s.get('observations',[]))]
        rows.append(Conclusion(claim_id='information',text='现有材料不足以形成已核验的法规性结论，请人工核查现场与相关原文。',kind='information_request').model_dump())
        return rows
    def draft(s):
        r=s['request']
        if s.get('exhausted') or not s.get('evidence') or not r.get('use_model',True):return {'conclusions':fallback(s)}
        aliases={'e'+str(i+1):e['evidence_id'] for i,e in enumerate(s['evidence'])}
        evidence=[{**{k:e[k] for k in ['text','document_title','conditions','parent_text'] if k in e},'evidence_id':'e'+str(i+1)} for i,e in enumerate(s['evidence'])]
        spec=s.get('policy',{}).get('spec',{})
        obj=complete(s,'recommendation填写整改建议，不得在建议中编造实测值或法规结论。历史案例只作思路参考，不能引用为本次事实或法律依据。生成核查草稿，最多4条结论，每条text不超过100字；不要重复引文全文。返回 {"conclusions":[...]}。引用使用本次给定的e1/e2等短编号，不生成长哈希。每条必须显式填写kind：单纯描述图像用observation，提示补测或无法判断用information_request；只有关联法规判定才用legal_assessment且evidence_ids不得为空。检索条款不相关时保留现场观察和待核查问题，不能硬套。每条符合 schema。引用仅用给定 evidence_id；现场判断必须关联 observation_id；未知条件保留 missing_fields。信息不全时 applicability=unknown、sufficiency=insufficient。',
            {'schema':Conclusion.model_json_schema(),'query':r['query'],'scene':r['scene'],'observations':s.get('observations',[]),
             'evidence':evidence,'prior_errors':s.get('verification',{}).get('errors',[]),'template':spec.get('template','standard'),
             'report_preferences':s.get('memory',{}).get('preferences',[]),
             'historical_cases_not_current_facts':s.get('similar_cases',[]),
             'non_authoritative_experience':s.get('memory',{}).get('organization',[]),
             'conversation_background_not_current_facts':s.get('memory',{}).get('episodic',[])},role='answer')
        rows=[Conclusion.model_validate(x).model_dump() for x in obj.get('conclusions',[])[:8]]
        for c in rows:c['evidence_ids']=[aliases.get(e,e) for e in c['evidence_ids']]
        if s.get('policy',{}).get('triggered') and spec.get('kind')=='hook' and spec.get('hook')=='before_draft':
            store.audit(s['run_id'],'hook-before-draft:'+str(s.get('rewrites',0)),'hook_applied',hook='before_draft',template=spec.get('template'))
        required=spec.get('require_fields',[]) if s.get('policy',{}).get('triggered') else []
        for c in rows:
            if s.get('context_gaps') and c['kind']=='legal_assessment':
                c['missing_fields'].append('完整父条款上下文');c['sufficiency']='insufficient';c['applicability']='unknown'
            missing=[f for f in required if f not in r['scene']]
            if missing:
                c['missing_fields']=sorted(set(c['missing_fields']+missing));c['sufficiency']='insufficient';c['applicability']='unknown'
        return {'conclusions':rows or fallback(s)}
    def verified(s,claims=None):
        claims=s.get('conclusions',[]) if claims is None else claims
        result=verify(store,s,claims)
        if result['passed'] and any(c.get('kind')=='legal_assessment' for c in claims):
            if not s['request'].get('use_model',True) or s.get('exhausted'):
                result.update(passed=False,semantic_review='unavailable')
                result['errors'].append({'code':'semantic_verification_unavailable'})
                return result
            obj=complete(s,'核验每个结论是否被原文和现场观察支持、是否遗漏适用条件。输出 {"supported":true或false,"issues":[{"claim_id":"...","reason":"..."}]}。不判断为专业人工审核。',
                {'conclusions':claims,'observations':s.get('observations',[]),'scene':s['request']['scene'],
                 'evidence':[{'evidence_id':e['evidence_id'],'text':e['text'],'conditions':e.get('conditions',{})} for e in s.get('evidence',[])]},role='verify')
            result['semantic_review']='model_supported' if obj.get('supported') is True else 'model_disputed'
            if obj.get('supported') is not True:
                result['errors'].append({'code':'semantic_unsupported','issues':obj.get('issues',[])})
                result['passed']=False
        result['binding_hash']=digest([s['snapshot_id'],s['request'],claims,s.get('observations',[]),s.get('evidence',[])])
        return result
    def check(s):
        result=verified(s)
        policy=s.get('policy',{})
        if policy.get('group')=='treatment' and any(e['code'] in ['forged_citation','source_mismatch'] for e in result['errors']):
            policies.rollback(policy['experiment_id'],'critical_verification_failure')
        return {'verification':result}
    def repair(s):return {'rewrites':s.get('rewrites',0)+1}
    def review_ready(s):
        if not s.get('conclusions'):
            s['conclusions']=fallback(s);s['verification']=verify(store,s)
        if not s.get('verification'):s['verification']=verify(store,s)
        report={'run_id':s['run_id'],'status':'draft','facility':s.get('facility','unknown'),'snapshot_id':s['snapshot_id'],'execution_version':s.get('execution_version','2.0'),
                'model_version':s.get('model_version',MODEL),'model_routes':s.get('model_routes',{}),'model_fingerprint':s.get('model_fingerprint'),'policy_version':s.get('policy',{}).get('policy_id','baseline-v2'),
                'detector':s.get('detector',{}),'observations':s.get('observations',[]),'similar_cases':s.get('similar_cases',[]),'evidence':s.get('evidence',[]),'conclusions':s['conclusions'],
                'verification':s['verification'],'warnings':s.get('warnings',[]),'professional_review':'pending'}
        if not s.get('forced_policy'):
            memory.remember(s);policies.record(s)
        return {'report':report,'conclusions':s['conclusions'],'verification':s['verification'],'status':'awaiting_review'}
    def human(s):
        answer=interrupt({'run_id':s['run_id'],'report':s['report'],'allowed_actions':['approve','return','reject']})
        return {'review':answer}
    def finalize(s):
        action=s['review']['action'];report=copy.deepcopy(s['report']);r=copy.deepcopy(s['request'])
        r['scene'].update(s['review'].get('confirmed_scene',{}))
        if action=='approve':
            claims=s['review']['conclusions'] if s['review'].get('conclusions') is not None else s['conclusions']
            s['request']=r
            try:result=verified(s,claims)
            except Exception as exc:
                result=verify(store,s,claims);result.update(passed=False,semantic_review='unavailable')
                result['errors'].append({'code':'semantic_verification_unavailable','reason':type(exc).__name__})
                if isinstance(exc,BudgetExhausted):s['exhausted']=True
            if not result['passed']:
                report.update(conclusions=claims,verification=result,status='draft')
                return {'report':report,'verification':result,'status':'awaiting_review','request':r,'conclusions':claims}
            report.update(conclusions=claims,verification=result,status='final',reviewer=s['review'].get('reviewer'),
                          review_comment=s['review'].get('comment',''),finalized_at=now().isoformat(),professional_review='human_reviewed_not_expert_certified')
            return {'report':report,'status':'complete','request':r,'conclusions':claims,'verification':result}
        if action=='reject':report['status']='rejected';return {'report':report,'status':'complete'}
        report['review_comment']=s['review'].get('comment','')
        if s['review'].get('confirmed_scene'):
            return {'report':report,'request':r,'status':'redrafting','rewrites':0}
        return {'report':report,'request':r,'status':'awaiting_information','rewrites':0}
    g=StateGraph(State)
    for name,fn in [('context',context),('intent',intent),('rewrite',rewrite),('retrieve',retrieve),('draft',draft),('verify',check),('repair',repair),('review_ready',review_ready)]:
        g.add_node(name,safe_node(store,name,fn))
    for facility in FACILITIES:g.add_node(facility,facility_graph(store,facility))
    g.add_node('human',human);g.add_node('finalize',safe_node(store,'finalize',finalize))
    g.add_edge(START,'context');g.add_edge('context','intent')
    g.add_conditional_edges('intent',lambda s:s['facility'] if s.get('facility') in FACILITIES and s['request'].get('processed_image_path') and s['request'].get('use_model',True) else 'rewrite')
    for f in FACILITIES:g.add_edge(f,'rewrite')
    g.add_edge('rewrite','retrieve');g.add_edge('retrieve','draft');g.add_edge('draft','verify')
    g.add_conditional_edges('verify',verification_route);g.add_edge('repair','draft');g.add_edge('review_ready','human');g.add_edge('human','finalize')
    g.add_conditional_edges('finalize',lambda s:END if s['status']=='complete' else ('draft' if s['status']=='redrafting' else 'human'))
    cp=MongoDBSaver(store.client,db_name=store.db.name,checkpoint_collection_name='checkpoints',writes_collection_name='checkpoint_writes') if checkpointer else None
    return g.compile(checkpointer=cp)
