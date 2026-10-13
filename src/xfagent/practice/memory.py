"""Owner-scoped conversation memory. Historical text is never legal evidence."""
import hashlib
import json
import os
import time
import uuid

from .contracts import FACILITIES


class Memory:
    TTL = 24 * 3600
    BUDGET = 2048  # UTF-8 byte upper bound, conservative relative to token budget.

    def __init__(self, storage, cache=None):
        self.storage = storage
        self.cache = cache
        if cache is None and os.getenv('XF_PRACTICE_REDIS'):
            import redis
            self.cache = redis.Redis.from_url(os.environ['XF_PRACTICE_REDIS'], socket_timeout=.2, socket_connect_timeout=.2)
        with storage.connection() as db:
            db.executescript('''
              CREATE TABLE IF NOT EXISTS conversations(id TEXT PRIMARY KEY,owner TEXT,project TEXT,created REAL,updated REAL);
              CREATE TABLE IF NOT EXISTS preferences(owner TEXT,project TEXT,key TEXT,value TEXT,updated REAL,PRIMARY KEY(owner,project,key));
            ''')
            # Upgrade the fourth-stage reports without exposing other owners' sessions.
            for row in db.execute('SELECT owner,project,body FROM reports').fetchall():
                r = json.loads(row['body'])
                sid = r.get('session_id')
                if sid:
                    db.execute('INSERT OR IGNORE INTO conversations VALUES(?,?,?,?,?)',
                        (sid, row['owner'], row['project'], r['created_at'], r['created_at']))

    def ensure(self, sid, actor):
        with self.storage.connection() as db:
            if sid:
                row = db.execute('SELECT id FROM conversations WHERE id=? AND owner=? AND project=?',
                                 (sid, actor['username'], actor['project_id'])).fetchone()
                if not row:
                    raise LookupError('会话不存在或无权访问')
            else:
                sid = uuid.uuid4().hex
                db.execute('INSERT INTO conversations VALUES(?,?,?,?,?)',
                           (sid, actor['username'], actor['project_id'], time.time(), time.time()))
        return sid

    def sessions(self, actor):
        with self.storage.connection() as db:
            rows = db.execute('SELECT id,created,updated FROM conversations WHERE owner=? AND project=? ORDER BY updated DESC LIMIT 50',
                              (actor['username'], actor['project_id'])).fetchall()
        result = []
        for row in rows:
            item = dict(row)
            history = self.history(item['id'], actor)
            item['title'] = history[0]['query'][:80] if history else '新巡检会话'
            result.append(item)
        return result

    def history(self, sid, actor):
        self.ensure(sid, actor)
        with self.storage.connection() as db:
            rows = db.execute("SELECT body FROM reports WHERE owner=? AND project=? AND json_extract(body,'$.session_id')=? ORDER BY rowid DESC LIMIT 30",
                              (actor['username'], actor['project_id'], sid)).fetchall()
        fields = ['id', 'query', 'facility', 'status', 'created_at', 'answer', 'model', 'revision', 'error']
        return [{k: r.get(k) for k in fields} for r in reversed([json.loads(row['body']) for row in rows])]

    def preferences(self, actor):
        with self.storage.connection() as db:
            rows = db.execute('SELECT key,value FROM preferences WHERE owner=? AND project=?',
                              (actor['username'], actor['project_id'])).fetchall()
        return {row['key']: row['value'] for row in rows}

    def set_preference(self, actor, value, consent):
        if consent is not True or value not in {'concise', 'detailed'}:
            raise ValueError('长期偏好需要明确同意，且只能选择简洁或详细')
        with self.storage.connection() as db:
            db.execute('INSERT OR REPLACE INTO preferences VALUES(?,?,?,?,?)',
                       (actor['username'], actor['project_id'], 'answer_style', value, time.time()))
        return self.preferences(actor)

    def clear_preferences(self, actor):
        with self.storage.connection() as db:
            db.execute('DELETE FROM preferences WHERE owner=? AND project=?', (actor['username'], actor['project_id']))

    def key(self, sid, actor):
        scope = json.dumps([str(self.storage.path.resolve()), actor['username'], actor['project_id'], sid])
        return 'xfpractice:working:' + hashlib.sha256(scope.encode()).hexdigest()

    def touch(self, sid, actor):
        with self.storage.connection() as db:
            db.execute('UPDATE conversations SET updated=? WHERE id=? AND owner=? AND project=?',
                       (time.time(), sid, actor['username'], actor['project_id']))
        if self.cache is not None:
            try:
                self.cache.delete(self.key(sid, actor))
            except Exception:
                pass  # SQLite remains the durable authority.

    def context(self, request, actor, exclude_id=None):
        sid = request['session_id']
        self.ensure(sid, actor)
        history = self.history(sid, actor)
        valid = [r for r in history if r['id'] != exclude_id and r['status'] in {'pending', 'approved'}
                 and time.time() - r['created_at'] < self.TTL]
        working = {}
        if valid and not request.get('image'):
            last = valid[-1]
            working = {'previous_query': (last['query'] or '')[:300], 'facility': last['facility'],
                       'report_id': last['id'], 'authority': 'user_context_only'}
        # Validate cache against durable current history: a rejected/expired report cannot survive in Redis.
        cache_state = 'sqlite_only'
        if self.cache is not None:
            try:
                encoded = json.dumps(working, ensure_ascii=False)
                cached = self.cache.get(self.key(sid, actor))
                if cached is not None and (cached.decode() if isinstance(cached, bytes) else cached) == encoded:
                    working = json.loads(cached)
                    cache_state = 'redis_hit'
                else:
                    remaining = max(1, int(self.TTL - (time.time() - valid[-1]['created_at']))) if valid else self.TTL
                    self.cache.setex(self.key(sid, actor), remaining, encoded)
                    cache_state = 'redis_refreshed'
            except Exception:
                cache_state = 'redis_unavailable_sqlite_fallback'
        result = {'working': working, 'preferences': self.preferences(actor), 'authority': 'not_evidence',
                  'cache': cache_state, 'budget_bytes': self.BUDGET,
                  'policy': '历史仅用于理解指代；照片、测量、条款和旧结论不作为本轮事实。'}
        while len(json.dumps(result, ensure_ascii=False).encode()) > self.BUDGET and result['working'].get('previous_query'):
            result['working']['previous_query'] = result['working']['previous_query'][:-20]
        return result


def resolve_followup(request, context):
    """Only explicit anaphora may inherit facility, never an old photo or measurement."""
    query = request['query']
    explicit = any(term in query for term in FACILITIES.values())
    anaphora = any(word in query for word in ['这个', '它', '上述', '刚才', '上一轮', '继续', '再检查', '怎么整改', '如何整改'])
    facility = context.get('working', {}).get('facility')
    if request['facility'] == 'auto' and not request.get('image') and not explicit and anaphora and facility in FACILITIES:
        return facility
    return None
