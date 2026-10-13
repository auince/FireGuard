"""Small persistent practice store: opaque sessions and revision-fenced reports."""
import hashlib
import hmac
import json
import os
import secrets
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path


def password_hash(password, salt):
    return hashlib.pbkdf2_hmac('sha256', password.encode(), bytes.fromhex(salt), 200_000).hex()


class Conflict(ValueError):
    pass


class Storage:
    def __init__(self, path=None):
        self.path = Path(path or os.getenv('XF_PRACTICE_DB', str(Path(__file__).resolve().parents[3] / 'runtime/practice/state.sqlite')))
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connection() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS users(username TEXT PRIMARY KEY,salt TEXT,hash TEXT,role TEXT,project TEXT);
                CREATE TABLE IF NOT EXISTS tokens(hash TEXT PRIMARY KEY,username TEXT,expires REAL);
                CREATE TABLE IF NOT EXISTS reports(id TEXT PRIMARY KEY,owner TEXT,project TEXT,revision INTEGER,body TEXT);
                CREATE INDEX IF NOT EXISTS reports_owner ON reports(owner,project);
            ''')
        self.path.chmod(0o600)

    @contextmanager
    def connection(self):
        db = sqlite3.connect(self.path, timeout=20)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    def add_user(self, username, password, role='inspector', project='practice'):
        if role not in {'inspector', 'reviewer', 'admin'} or not password:
            raise ValueError('invalid user')
        salt = secrets.token_hex(16)
        with self.connection() as db:
            db.execute('INSERT INTO users VALUES(?,?,?,?,?)', (username, salt, password_hash(password, salt), role, project))

    def login(self, username, password):
        with self.connection() as db:
            row = db.execute('SELECT * FROM users WHERE username=?', (username,)).fetchone()
            salt = row['salt'] if row else '00' * 16
            actual = password_hash(password, salt)
            if not row or not hmac.compare_digest(actual, row['hash']):
                raise ValueError('用户名或密码错误')
            token = secrets.token_urlsafe(32)
            db.execute('DELETE FROM tokens WHERE expires<?', (time.time(),))
            db.execute('INSERT INTO tokens VALUES(?,?,?)', (hashlib.sha256(token.encode()).hexdigest(), username, time.time()+8*3600))
            return {'token': token, 'actor': {'username': username, 'role': row['role'], 'project_id': row['project']}}

    def actor(self, token):
        with self.connection() as db:
            row = db.execute('SELECT u.username,u.role,u.project FROM tokens t JOIN users u ON t.username=u.username '
                             'WHERE t.hash=? AND t.expires>?', (hashlib.sha256(token.encode()).hexdigest(), time.time())).fetchone()
            return {'username': row['username'], 'role': row['role'], 'project_id': row['project']} if row else None

    def logout(self, token):
        with self.connection() as db:
            db.execute('DELETE FROM tokens WHERE hash=?', (hashlib.sha256(token.encode()).hexdigest(),))

    def save(self, report):
        with self.connection() as db:
            db.execute('INSERT INTO reports VALUES(?,?,?,?,?)', (report['id'], report['owner'], report['project_id'],
                        report['revision'], json.dumps(report, ensure_ascii=False)))

    def get(self, identifier):
        with self.connection() as db:
            row = db.execute('SELECT body FROM reports WHERE id=?', (identifier,)).fetchone()
            return json.loads(row['body']) if row else None

    def visible(self, actor):
        with self.connection() as db:
            sql = 'SELECT body FROM reports WHERE project=?'
            args = [actor['project_id']]
            if actor['role'] == 'inspector':
                sql += ' AND owner=?'; args.append(actor['username'])
            rows = db.execute(sql + ' ORDER BY rowid DESC LIMIT 50', args).fetchall()
        return [json.loads(row['body']) for row in rows]

    def cas(self, identifier, revision, states, transform, increment=True):
        with self.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT body FROM reports WHERE id=? AND revision=?', (identifier, revision)).fetchone()
            if not row:
                raise Conflict('报告版本已更新，请刷新后重试')
            report = json.loads(row['body'])
            if report['status'] not in states:
                raise Conflict('当前报告状态不允许此操作')
            report = transform(report)
            report['revision'] = revision + int(increment)
            db.execute('UPDATE reports SET revision=?,body=? WHERE id=? AND revision=?',
                       (report['revision'], json.dumps(report, ensure_ascii=False), identifier, revision))
            return report

    def recover_interrupted(self):
        with self.connection() as db:
            for row in db.execute('SELECT id,body FROM reports').fetchall():
                report = json.loads(row['body'])
                if report['status'] in {'queued', 'running'}:
                    report.update(status='failed', error='服务重启中断了任务，请补充或重新提交')
                    db.execute('UPDATE reports SET body=? WHERE id=?', (json.dumps(report, ensure_ascii=False), row['id']))
