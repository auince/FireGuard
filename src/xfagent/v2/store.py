"""Mongo is authoritative; transactional outbox bridges durable jobs to Redis."""
import hashlib,json,uuid
from datetime import timedelta
from pymongo import MongoClient, ReturnDocument
from pymongo.errors import DuplicateKeyError
from .config import MONGO,DB,now

def digest(value):
    raw=value if isinstance(value,bytes) else json.dumps(value,ensure_ascii=False,sort_keys=True,default=str).encode()
    return hashlib.sha256(raw).hexdigest()

def public(doc):
    if doc is None:return None
    return {('id' if k=='_id' else k):v for k,v in doc.items()}

def equivalent_request(left,right):
    # Adding an opt-in feature must not break retries of pre-upgrade requests.
    def normalized(value):
        value=dict(value)
        if value.get('query_strategy')=='standard':value.pop('query_strategy')
        return value
    return digest(normalized(left))==digest(normalized(right))

class Store:
    def __init__(self,uri=MONGO,name=DB):
        self.client=MongoClient(uri,serverSelectionTimeoutMS=5000,tz_aware=True)
        self.db=self.client[name]

    def setup(self):
        for name,keys,opts in [
            ('jobs',[('owner',1),('idempotency_key',1)],{'unique':True}),
            ('events',[('run_id',1),('event_key',1)],{'unique':True}),
            ('evidence',[('snapshot_id',1),('legacy_id',1)],{'unique':True}),
            ('documents',[('snapshot_id',1),('doc_id',1)],{'unique':True}),
            ('documents',[('snapshot_id',1),('ready',1),('status',1),('jurisdiction',1),('effective_from',1),('effective_until',1)],{}),
            ('events',[('event',1),('project_id',1),('at',-1)],{}),
            ('memories',[('expires_at',1)],{'expireAfterSeconds':0}),
            ('jobs',[('status',1),('lease_until',1)],{}),
            ('model_calls',[('run_id',1),('node',1)],{}),
            ('outbox',[('sent',1),('created_at',1)],{}),
        ]:self.db[name].create_index(keys,**opts)

    def audit(self,run_id,event_key,event,**fields):
        self.db.events.update_one({'run_id':run_id,'event_key':event_key},
            {'$setOnInsert':{'event':event,'at':now(),**fields}},upsert=True)

    def submit(self,kind,payload,actor,key):
        identifier=uuid.uuid4().hex
        body={'_id':identifier,'owner':actor.user_id,'project_id':payload.get('project_id','default'),
              'kind':kind,'input':payload,'input_hash':digest(payload),'idempotency_key':key,
              'status':'queued','revision':1,'created_at':now(),'attempts':0}
        try:
            with self.client.start_session() as s:
                with s.start_transaction():
                    self.db.jobs.insert_one(body,session=s)
                    self.db.outbox.insert_one({'_id':identifier+':1','job_id':identifier,'sent':False,'created_at':now()},session=s)
        except DuplicateKeyError:
            old=self.db.jobs.find_one({'owner':actor.user_id,'idempotency_key':key})
            if old is None or (old['input_hash']!=body['input_hash'] and not equivalent_request(old['input'],payload)):
                raise ValueError('幂等键已用于不同请求')
            return old
        return body

    def claim(self,identifier,worker):
        t=now()
        return self.db.jobs.find_one_and_update({'_id':identifier,'$or':[
            {'status':'queued'},{'status':'running','lease_until':{'$lt':t}}]},
            {'$set':{'status':'running','worker':worker,'lease_until':t+timedelta(seconds=360),'started_at':t},
             '$inc':{'attempts':1}},return_document=ReturnDocument.AFTER)

    def recover_dispatch(self):
        """Re-dispatch durable work after Redis loss; duplicates remain lease-fenced."""
        t=now();cutoff=t-timedelta(seconds=60)
        status={'$or':[{'status':'queued'},{'status':'running','lease_until':{'$lt':t}}]}
        overdue={'$or':[{'dispatch_recovered_at':{'$lt':cutoff}},{'dispatch_recovered_at':{'$exists':False}}]}
        selector={'$and':[status,overdue,{'created_at':{'$lt':cutoff}}]};count=0
        for row in self.db.jobs.find(selector,{'_id':1}).limit(100):
            with self.client.start_session() as session:
                with session.start_transaction():
                    changed=self.db.jobs.update_one({'_id':row['_id'],**selector},
                        {'$set':{'dispatch_recovered_at':t}},session=session).modified_count
                    if changed:
                        self.db.outbox.insert_one({'_id':row['_id']+':dispatch-recovery:'+uuid.uuid4().hex,
                            'job_id':row['_id'],'sent':False,'created_at':t,'reason':'durable_job_reconciliation'},session=session)
                        count+=1
        return count

    def finish(self,identifier,worker,values,report=None):
        # Fence the report and task transition together: an expired worker must
        # never overwrite the report produced by its replacement.
        with self.client.start_session() as session:
            with session.start_transaction():
                changed=self.db.jobs.update_one({'_id':identifier,'worker':worker,'status':'running',
                    '$or':[{'lease_until':{'$gt':now()}},{'lease_until':{'$exists':False}}]},
                    {'$set':{**values,'updated_at':now()},'$unset':{'lease_until':''}},session=session).modified_count
                if changed and report is not None:
                    self.db.reports.update_one({'_id':identifier},{'$set':report},upsert=True,session=session)
                if changed and values.get('status')=='complete':
                    self.db.treatments.update_one({'_id':identifier},{'$set':{'completed':True,'completed_at':now()}},session=session)
        return changed

    def enqueue_resume(self,job,review,actor):
        revision=job['revision']+1
        with self.client.start_session() as s:
            with s.start_transaction():
                changed=self.db.jobs.update_one({'_id':job['_id'],'revision':review['expected_revision'],
                    'status':{'$in':['awaiting_review','awaiting_information','failed']}},
                    {'$set':{'status':'queued','resume':review,'review_actor':actor.model_dump()},'$inc':{'revision':1}},session=s)
                if not changed.modified_count:raise ValueError('报告版本已更新或当前不可复核')
                self.db.outbox.insert_one({'_id':job['_id']+':'+str(revision),'job_id':job['_id'],
                    'sent':False,'created_at':now()},session=s)
        return revision

    def active_snapshot(self):
        pointer=self.db.settings.find_one({'_id':'active_snapshot'})
        if not pointer:raise ValueError('尚未发布法规快照')
        return pointer['value']
