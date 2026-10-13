import os,time,uuid,traceback
from datetime import timedelta
import redis
from langgraph.types import Command
from .config import REDIS,now
from .store import Store
from .graphs import inspection_graph
from .feedback import feedback_graph,cluster_gaps
from .replay import run_replay

STREAM=os.getenv('XF_QUEUE_STREAM','xfv2:jobs');GROUP=os.getenv('XF_QUEUE_GROUP','workers')

def drain_outbox(store,r):
    for item in store.db.outbox.find({'sent':False}).sort('created_at',1).limit(100):
        r.xadd(STREAM,{'job_id':item['job_id'],'outbox_id':item['_id']})
        store.db.outbox.update_one({'_id':item['_id']},{'$set':{'sent':True,'sent_at':now()}})

def execute(store,g,job,worker):
    kind=job['kind'];identifier=job['_id']
    try:
        if kind in ['inspection','retrieval','annotation']:
            sid=job.get('snapshot_id') or store.active_snapshot()
            store.db.jobs.update_one({'_id':identifier,'worker':worker},{'$set':{'snapshot_id':sid}})
            config={'configurable':{'thread_id':identifier},'recursion_limit':70}
            if g.get_state(config).values:g.update_state(config,{'execution_worker':worker})
            if job.get('resume'):
                value=Command(resume={**job['resume'],'reviewer':job['review_actor']['user_id']})
            elif job['attempts']>1 and g.get_state(config).values:value=None
            else:value={'run_id':identifier,'execution_worker':worker,'owner':job['owner'],'request':job['input'],'snapshot_id':sid,
                'calls':0,'active_seconds':0,'trace':[],'warnings':[]}
            result=g.invoke(value,config);paused=bool(result.pop('__interrupt__',None))
            status=result.get('status','awaiting_review') if paused else result.get('status','complete')
            report={'owner':job['owner'],'project_id':job['project_id'],'revision':job['revision'],
                'report':result['report'],'updated_at':now()} if 'report' in result else None
            changed=store.finish(identifier,worker,{'status':status,'result':result,'resume':None},report=report)
            if changed and status=='complete':
                from .policy import Policies
                Policies(store).monitor(result.get('policy',{}).get('experiment_id'))
        elif kind=='feedback':
            f=store.db.feedback.find_one({'_id':job['input']['feedback_id']})
            if job['input'].get('attribution_version',1)!=f.get('attribution_version',1):
                store.finish(identifier,worker,{'status':'complete','result':{'status':'superseded_attribution'}});return
            source=store.db.jobs.find_one({'_id':f['run_id']})
            result=feedback_graph(store).invoke({'feedback':f,'source':source,'calls':0,'active_seconds':0,'run_id':identifier,'execution_worker':worker})
            tickets=cluster_gaps(store,job['project_id']) if result['category']=='knowledge_gap' else []
            store.finish(identifier,worker,{'status':'complete','result':{**result['result'],'knowledge_tickets':tickets}})
        elif kind=='legal_index':
            from .facts import prepare_snapshot
            from .retrieval import index_snapshot
            sid=prepare_snapshot(store);index_snapshot(store,sid)
            from .structure import materialize_structure
            materialize_structure(store,sid)
            store.finish(identifier,worker,{'status':'complete','result':{'snapshot_id':sid,'approval':'pending'}})
        elif kind=='replay':
            result=run_replay(store,job['input']['policy_id'],job['input']['run_ids'],job['project_id'])
            store.finish(identifier,worker,{'status':'complete','result':result})
        else:raise ValueError('unknown job kind')
    except Exception as exc:
        traceback.print_exc();store.finish(identifier,worker,{'status':'failed','error':type(exc).__name__+': '+str(exc)[:500]})

def main():
    import threading
    store=Store();store.setup();r=redis.Redis.from_url(REDIS,decode_responses=True,socket_timeout=5)
    worker='worker-'+uuid.uuid4().hex;g=inspection_graph(store,governed=os.getenv('XF_HARNESS_VERSION')=='8')
    try:r.xgroup_create(STREAM,GROUP,id='0',mkstream=True)
    except redis.ResponseError as exc:
        if 'BUSYGROUP' not in str(exc):raise
    next_reconcile=0
    import signal
    stop=threading.Event()
    if threading.current_thread() is threading.main_thread():
        for sig in (signal.SIGTERM,signal.SIGINT):signal.signal(sig,lambda *_:stop.set())
    while not stop.is_set():
        try:
            store.db.workers.update_one({'_id':worker},{'$set':{'heartbeat_at':now(),'state':'idle','queue':STREAM}},upsert=True)
            if time.monotonic()>=next_reconcile:
                store.recover_dispatch();next_reconcile=time.monotonic()+60
            drain_outbox(store,r)
            # Lease expiry and pending-message claim are independent; both are required.
            stale=r.xautoclaim(STREAM,GROUP,worker,min_idle_time=370000,start_id='0-0',count=1)
            entries=stale[1] if stale and stale[1] else []
            if not entries:
                batch=r.xreadgroup(GROUP,worker,{STREAM:'>'},count=1,block=1000)
                entries=batch[0][1] if batch else []
            for message_id,fields in entries:
                job=store.claim(fields['job_id'],worker)
                if not job:
                    current=store.db.jobs.find_one({'_id':fields['job_id']})
                    if current and current['status'] not in ['queued','running']:r.xack(STREAM,GROUP,message_id)
                    continue
                if job['attempts']>6:
                    store.finish(job['_id'],worker,{'status':'failed','error':'recovery_attempt_limit'});r.xack(STREAM,GROUP,message_id);continue
                store.db.workers.update_one({'_id':worker},{'$set':{'state':'running','run_id':job['_id']}})
                done=threading.Event()
                def heartbeat():
                    while not done.wait(30):
                        store.db.workers.update_one({'_id':worker},{'$set':{'heartbeat_at':now()}})
                        store.db.jobs.update_one({'_id':job['_id'],'worker':worker,'status':'running','lease_until':{'$gt':now()}},
                            {'$set':{'lease_until':now()+timedelta(seconds=360)}})
                thread=threading.Thread(target=heartbeat,daemon=True);thread.start()
                try:execute(store,g,job,worker)
                finally:done.set()
                r.xack(STREAM,GROUP,message_id)
        except Exception as exc:
            print('worker loop:',type(exc).__name__,str(exc)[:300],flush=True);stop.wait(2)

if __name__=='__main__':main()
