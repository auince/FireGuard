"""Atomic feedback intake: feedback, execution job and outbox share a transaction."""
import uuid
from .config import now
from .store import digest


def submit_feedback(store, body, actor, source, key):
    identifier=digest([actor.user_id,key or uuid.uuid4().hex])
    job_id='feedback-'+identifier
    value=body.model_dump()
    payload={'feedback_id':identifier,'project_id':source['project_id']}
    def transaction(session):
        existing=store.db.feedback.find_one({'_id':identifier},session=session)
        if existing:
            if existing.get('submission_hash',digest({k:existing.get(k) for k in value}))!=digest(value):
                raise ValueError('同一反馈提交标识不能用于不同内容')
            return {'feedback_id':identifier,'id':job_id}
        store.db.feedback.insert_one({'_id':identifier,**value,'submission_hash':digest(value),
            'owner':actor.user_id,'project_id':source['project_id'],'state':'queued','attribution_version':1,'created_at':now()},session=session)
        store.db.jobs.insert_one({'_id':job_id,'owner':actor.user_id,'project_id':source['project_id'],'kind':'feedback','input':payload,
            'input_hash':digest(payload),'idempotency_key':'feedback:'+identifier,'status':'queued','revision':1,'attempts':0,'created_at':now()},session=session)
        store.db.outbox.insert_one({'_id':job_id+':1','job_id':job_id,'sent':False,'created_at':now()},session=session)
        return {'feedback_id':identifier,'id':job_id}
    with store.client.start_session() as session:
        return session.with_transaction(transaction)
