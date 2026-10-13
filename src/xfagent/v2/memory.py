import json
from datetime import timedelta
import redis
from .config import REDIS,now
from .store import digest
from .facts import fetch_evidence

class MemoryContextBuilder:
    def __init__(self,store):
        self.store=store;self.redis=redis.Redis.from_url(REDIS,decode_responses=True,socket_timeout=2)

    def build(self,owner,project,session,sid,as_of,jurisdiction,budget=1800):
        out={'working':{},'episodic':[],'preferences':[],'organization':[],'warnings':[]}
        try:
            raw=self.redis.get('xfv2:memory:'+digest([owner,project,session]))
            if raw:out['working']=json.loads(raw)
        except redis.RedisError:out['warnings'].append('working_memory_unavailable')
        # UTF-8 bytes bound text tokens conservatively without a separate model call.
        # Working memory shares the same budget and never crowds out official evidence.
        if budget<0:raise ValueError('memory budget must be nonnegative')
        cost=lambda value:len(json.dumps(value,ensure_ascii=False,separators=(',',':')).encode())
        used=cost(out['working']) if out['working'] else 0
        if used>budget:
            out['working']={};used=0;out['warnings'].append('working_memory_omitted_token_budget')
        for kind,key in [('user','preferences'),('organization','organization'),('episode','episodic')]:
            filt={'kind':kind,'project_id':project,'expires_at':{'$gt':now()}}
            if kind=='organization':filt['approved']=True
            else:filt['owner']=owner
            for row in self.store.db.memories.find(filt).sort('created_at',-1).limit(8):
                if kind=='organization':
                    bindings=row.get('evidence_ids',[])
                    if not bindings or not all(fetch_evidence(self.store,sid,e,as_of,jurisdiction) for e in bindings):
                        self.store.db.memories.update_one({'_id':row['_id']},{'$set':{'approved':False,'needs_review':True}})
                        continue
                content={'id':str(row['_id']),'content':row['content'],'authority':kind,'usable_as_legal_evidence':False}
                token_bound=cost(content)
                if used+token_bound>budget:
                    out['warnings'].append('memory_omitted_token_budget:'+kind);continue
                out[key].append(content);used+=token_bound
        out['budget']={'token_upper_bound':used,'limit':budget,'method':'utf8_bytes_conservative'}
        return out

    def remember(self,state):
        req=state['request'];working={'last_query':req['query'],'facility':state.get('facility'),
            'confirmed_scene':req['scene'],'session_id':req['session_id'],'as_of':req['as_of'],
            'source_run_id':state['run_id'],
            'prior_observations':[{'description':o['description'],'status':o['status'],
                'image_id':o.get('image_id'),'authority':'prior_run_observation_not_new_image_fact'}
                for o in state.get('observations',[])[:4]]}
        try:self.redis.set('xfv2:memory:'+digest([state['owner'],req['project_id'],req['session_id']]),json.dumps(working,ensure_ascii=False),ex=1800)
        except redis.RedisError:pass
        self.store.db.memories.update_one({'_id':'episode:'+state['run_id']},{'$setOnInsert':{
            'kind':'episode','owner':state['owner'],'project_id':req['project_id'],
            'content':{'original_query':req['query'],'rewritten_queries':state.get('queries',[]),
                'facility':state.get('facility'),'run_id':state['run_id']},
            'created_at':now(),'expires_at':now()+timedelta(days=90)}},upsert=True)
        recent=list(self.store.db.memories.find({'kind':'episode','owner':state['owner'],'project_id':req['project_id'],
            'content.original_query':{'$exists':True}}).sort('created_at',-1).limit(5))
        if len(recent)==5:
            originals=[x['content']['original_query'] for x in recent]
            key='summary:'+digest([state['owner'],req['project_id'],originals])
            self.store.db.memories.update_one({'_id':key},{'$setOnInsert':{'kind':'episode','owner':state['owner'],
                'project_id':req['project_id'],'content':{'summary_type':'extractive_original_user_messages','messages':originals},
                'created_at':now(),'expires_at':now()+timedelta(days=180)}},upsert=True)

    def preference(self,actor,project,key,value,consent):
        if consent is not True:raise ValueError('保存偏好需要明确同意')
        if key not in ['report_detail','preferred_facility']:raise ValueError('不支持保存此偏好')
        if len(str(value))>100:raise ValueError('偏好过长')
        identifier=digest([actor.user_id,project,key])
        self.store.db.memories.update_one({'_id':identifier},{'$set':{'kind':'user','owner':actor.user_id,
            'project_id':project,'content':{key:value},'consent':True,'created_at':now(),'expires_at':now()+timedelta(days=180)}},upsert=True)
        return identifier
