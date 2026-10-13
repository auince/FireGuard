import uuid
from typing import TypedDict
from langgraph.graph import StateGraph,START,END
from .model import complete
from .schema import Strategy
from .config import now
from .policy import Policies
from .retrieval import embed
from .store import digest
from .call_ledger import node_scope

class LoopState(TypedDict,total=False):
    feedback:dict;source:dict;category:str;attribution:dict;candidate_id:str|None
    calls:int;active_seconds:float;usage:dict;result:dict;run_id:str;execution_worker:str

def feedback_graph(store):
    def reflect(s):
        f=s['feedback'];source=s['source']
        if f['signal'] in ['like','copy']:
            return {'category':'weak_signal','attribution':{'source':'program','reason':'仅记录弱信号，不生成策略'}}
        if f.get('category'):
            return {'category':f['category'],'attribution':{'source':'human','reason':f['text']}}
        result=complete(s,'归因消防任务反馈。返回 {"category":"intent|vision|retrieval|applicability|generation|knowledge_gap","reason":"依据"}。点赞复制只是弱信号，不代表正确。',
            {'feedback':f,'report':source.get('result',{}).get('report',{}),'query':source['input']['query']},role='reflect')
        category=result.get('category')
        if category not in ['intent','vision','retrieval','applicability','generation','knowledge_gap']:raise ValueError('invalid attribution')
        return {'category':category,'attribution':result,'calls':s.get('calls',0)}
    def adapt(s):
        category=s['category'];f=s['feedback'];source=s['source']
        if category=='weak_signal':return {'candidate_id':None}
        saved=store.db.feedback.find_one({'_id':f['_id']}) or {}
        if saved.get('candidate_id'):return {'candidate_id':saved['candidate_id']}
        if category in ['vision','knowledge_gap']:
            name='annotation_backlog' if category=='vision' else 'knowledge_gaps'
            store.db[name].update_one({'_id':f['_id']},{'$setOnInsert':{
                'run_id':source['_id'],'project_id':source['project_id'],'owner':source['owner'],
                'query':source['input']['query'],'feedback':f['text'],'state':'pending','created_at':now()}},upsert=True)
            return {'candidate_id':None}
        seed={'name':'反馈修复：'+{'intent':'意图识别','retrieval':'条款检索','generation':'结论生成','applicability':'适用条件'}[category],'source_feedback_ids':[f['_id']],
              'trigger_terms':[], 'template':'standard'}
        if category in ['retrieval','intent']:
            obj=complete(s,'提出有限检索修复，输出 {"trigger_terms":["术语"],"expand_terms":["术语"],"parent_expand":true或false}，不得创造法规事实。',
                {'query':source['input']['query'],'feedback':f['text'],'category':category},role='adapt')
            seed.update(trigger_terms=[str(x)[:40] for x in obj.get('trigger_terms',[])[:8]],
                        expand_terms=[str(x)[:40] for x in obj.get('expand_terms',[])[:8]],parent_expand=obj.get('parent_expand') is True)
        elif category=='generation':
            seed.update(kind='hook',hook='before_draft',template='risk_action_evidence')
        else:
            # Bounded rules use known fields only; every Rule still requires admin review.
            allowed=['building_use','building_height','measured_width','pressure_measurement','required_quantity']
            missing=source.get('result',{}).get('report',{}).get('verification',{}).get('missing_fields',[])
            fields=[field for field in allowed if field in missing]
            if fields:seed.update(kind='rule',require_fields=fields,template='measurement_required')
            else:seed.update(kind='hook',hook='before_draft',template='measurement_required')
        spec=Strategy(**seed)
        version=f.get('attribution_version',1)
        candidate='feedback-'+f['_id']+('-r'+str(version) if version>1 else '')
        store.db.policies.update_one({'_id':candidate},{'$setOnInsert':{'spec':spec.model_dump(),'state':'draft',
            'project_id':source['project_id'],'owner':f['owner'],'version':1,'created_at':now()}},upsert=True)
        return {'candidate_id':candidate,'calls':s.get('calls',0)}
    def persist(s):
        f=s['feedback'];version=f.get('attribution_version',1)
        selector={'_id':f['_id'],'attribution_version':version} if version>1 else {'_id':f['_id'],'$or':[{'attribution_version':1},{'attribution_version':{'$exists':False}}]}
        def save(session):
            from .graphs import require_lease
            require_lease(store,s)
            updated=store.db.feedback.update_one(selector,{'$set':{'category':s['category'],
                'attribution':s['attribution'],'candidate_id':s.get('candidate_id'),'state':'attributed','attributed_at':now()}},session=session)
            if not updated.matched_count:
                if s.get('candidate_id'):
                    store.db.policies.update_one({'_id':s['candidate_id'],'state':'draft'},
                        {'$set':{'state':'deprecated','reason':'superseded_attribution'}},session=session)
                return {'result':{'state':'superseded_attribution','category':s['category']}}
            return {'result':{'category':s['category'],'candidate_id':s.get('candidate_id'),'state':'awaiting_regression_or_data'}}
        with store.client.start_session() as session:
            return session.with_transaction(save)
    g=StateGraph(LoopState)
    def bounded(name,fn):
        def run(s):
            # Feedback graphs restart from START; deterministic call keys reuse responses.
            local=dict(s);local.setdefault('run_id','feedback:'+s['feedback']['_id']+':'+str(s['feedback'].get('attribution_version',1)))
            import time
            local['_node_start']=time.monotonic()
            from .graphs import require_lease
            require_lease(store,local)
            with node_scope(store,local,name):result=fn(local)
            require_lease(store,local)
            result.update(calls=local.get('calls',0),usage=local.get('usage',{}),
                active_seconds=local.get('active_seconds',0)+time.monotonic()-local['_node_start'])
            return result
        return run
    for n,f in [('reflect',reflect),('adapt',adapt),('persist',persist)]:g.add_node(n,bounded(n,f))
    g.add_edge(START,'reflect');g.add_edge('reflect','adapt');g.add_edge('adapt','persist');g.add_edge('persist',END)
    return g.compile()

def cluster_gaps(store,project):
    from sklearn.cluster import DBSCAN
    rows=list(store.db.knowledge_gaps.find({'project_id':project,'state':'pending'}))
    unique={r['run_id']:r for r in rows};rows=list(unique.values())
    if len(rows)<20:return []
    vectors=embed([r['query'] for r in rows],timeout=120)
    labels=DBSCAN(eps=.2,min_samples=3,metric='cosine').fit_predict(vectors)
    output=[]
    for label in set(labels):
        if label<0:continue
        group=[r for r,l in zip(rows,labels) if l==label]
        if len(group)<20:continue
        identifier=digest(sorted(r['run_id'] for r in group))
        doc={'project_id':project,'state':'pending_source_collection','size':len(group),
             'representatives':[r['query'] for r in group[:5]],'run_ids':[r['run_id'] for r in group],'created_at':now()}
        store.db.knowledge_tickets.update_one({'_id':identifier},{'$setOnInsert':doc},upsert=True);output.append(identifier)
    return output
