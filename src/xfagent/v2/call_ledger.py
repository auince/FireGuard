"""Reserve inference quota before HTTP; uncertain deliveries are never resent.

Mongo transactions serialize competing reservations for a run. A response is
cached before a graph checkpoint, so restart can reuse it without new inference.
This is at-most-once dispatch, not exactly-once execution by the model server.
"""
from contextlib import contextmanager
from contextvars import ContextVar
from pymongo import ReturnDocument
from .config import now
from .store import digest

CURRENT = ContextVar('xf_model_node', default=None)

@contextmanager
def node_scope(store, state, name):
    token = CURRENT.set({'store': store, 'state': state, 'node': name,
                         'visit': len(state.get('trace', [])), 'ordinal': 0})
    try:
        yield
    finally:
        CURRENT.reset(token)

class CallLedger:
    def __init__(self, scope):
        self.scope = scope
        self.store = scope['store']
        self.state = scope['state']
        self.run_id = self.state['run_id']

    def key(self, request):
        scope = self.scope
        ordinal = scope['ordinal']; scope['ordinal'] += 1
        return digest([self.run_id, scope['node'], scope['visit'], ordinal, request])

    def reserve(self, key, route):
        from .model import BudgetExhausted
        db = self.store.db
        initial_calls = self.state.get('calls', 0)
        def transaction(session):
            worker = self.state.get('execution_worker')
            if worker:
                from .graphs import LeaseLost
                job = db.jobs.find_one({'_id': self.run_id, 'status': 'running', 'worker': worker}, session=session)
                if not job or (job.get('lease_until') and job['lease_until'] <= now()):
                    raise LeaseLost('model dispatch without current worker lease')
            db.model_budgets.update_one({'_id': self.run_id},
                {'$max': {'calls': initial_calls},
                 '$setOnInsert': {'created_at': now()}}, upsert=True, session=session)
            budget = db.model_budgets.find_one({'_id': self.run_id}, session=session)
            self.state['calls'] = budget['calls']
            prior = db.model_calls.find_one({'_id': key}, session=session)
            if prior:
                if prior['status'] == 'completed':
                    return prior
                raise BudgetExhausted('model_delivery_uncertain_or_failed_requires_new_run')
            if budget['calls'] >= 16:
                raise BudgetExhausted('model_call_limit_durable')
            budget = db.model_budgets.find_one_and_update({'_id': self.run_id, 'calls': {'$lt': 16}},
                {'$inc': {'calls': 1}}, return_document=ReturnDocument.AFTER, session=session)
            if not budget:
                raise BudgetExhausted('model_call_limit_durable')
            self.state['calls'] = budget['calls']
            db.model_calls.insert_one({'_id': key, 'run_id': self.run_id,
                'node': self.scope['node'], 'status': 'reserved', 'route': route,
                'reserved_at': now(), 'call_number': budget['calls']}, session=session)
            return None
        with self.store.client.start_session() as session:
            return session.with_transaction(transaction)

    def completed(self, key, result, usage):
        self.store.db.model_calls.update_one({'_id': key, 'status': 'reserved'},
            {'$set': {'status': 'completed', 'result': result, 'usage': usage, 'finished_at': now()}})

    def failed(self, key, exc):
        # Even a timeout can have executed on the model server. No refund/retry.
        self.store.db.model_calls.update_one({'_id': key, 'status': 'reserved'},
            {'$set': {'status': 'failed_delivery_unknown', 'error_type': type(exc).__name__, 'finished_at': now()}})
