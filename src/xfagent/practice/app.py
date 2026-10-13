import threading
import time
import uuid
from contextlib import asynccontextmanager
from datetime import date
from pathlib import Path
from typing import Literal

from fastapi import BackgroundTasks, Depends, FastAPI, HTTPException, Query
from fastapi.responses import FileResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, ConfigDict, Field

from . import STAGE
from .contracts import Inspection
from .harness import Harness
from .review import approval_gate
from .storage import Conflict, Storage


class Login(BaseModel):
    username: str = Field(min_length=1, max_length=100)
    password: str = Field(min_length=1, max_length=200)


class Review(BaseModel):
    model_config = ConfigDict(extra='forbid')
    expected_revision: int = Field(ge=1)
    action: Literal['approve', 'return', 'reject']
    comment: str = Field(default='', max_length=3000)


class Revision(BaseModel):
    expected_revision: int = Field(ge=1)
    input: Inspection


def create_app(engine=None, storage=None):
    storage = storage or Storage()
    @asynccontextmanager
    async def lifespan(app):
        storage.recover_interrupted()
        yield
    app = FastAPI(title='XFAgent 迭代原型', version=str(STAGE), lifespan=lifespan)
    app.state.engine = engine
    app.state.storage = storage
    engine_lock = threading.RLock()
    admission = threading.BoundedSemaphore(4)
    bearer = HTTPBearer(auto_error=False)
    login_attempts = {}
    login_lock = threading.Lock()
    web = Path(__file__).resolve().parents[3] / 'apps/practice/dist'

    def get_engine():
        with engine_lock:
            if app.state.engine is None:
                app.state.engine = Harness()
            return app.state.engine

    def actor(credentials: HTTPAuthorizationCredentials | None = Depends(bearer)):
        who = storage.actor(credentials.credentials) if credentials else None
        if not who:
            raise HTTPException(401, '请先登录，或重新登录已过期的会话')
        return who

    def accessible(identifier, who):
        report = storage.get(identifier)
        if not report or report['project_id'] != who['project_id'] or (
            who['role'] == 'inspector' and report['owner'] != who['username']):
            raise HTTPException(404, '报告不存在或无权访问')
        return report

    @app.middleware('http')
    async def headers(request, call_next):
        response = await call_next(request)
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['Cache-Control'] = 'no-store'
        response.headers['Content-Security-Policy'] = "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data: blob:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'"
        return response

    @app.get('/api/health')
    def health():
        model = app.state.engine.model.name if app.state.engine is not None else 'xf-qwen3.5-9b'
        return {'stage': STAGE, 'model': model, 'scope': 'resume-practice',
                'inference': 'injected_fixture' if 'fixture' in model else 'live_model_required'}

    @app.post('/api/login')
    def login(body: Login):
        with login_lock:
            now = time.monotonic()
            recent = [t for t in login_attempts.get(body.username, []) if now-t < 60]
            if len(recent) >= 5:
                raise HTTPException(429, '尝试过于频繁，请一分钟后重试')
            login_attempts[body.username] = recent + [now]
        try:
            result = storage.login(body.username, body.password)
            with login_lock:
                login_attempts.pop(body.username, None)
            return result
        except ValueError as exc:
            raise HTTPException(401, str(exc)) from exc

    @app.post('/api/logout')
    def logout(credentials: HTTPAuthorizationCredentials = Depends(bearer), who=Depends(actor)):
        storage.logout(credentials.credentials)
        return {'logged_out': True}

    def run(identifier, revision, request, owner):
        try:
            def trace_update(trace):
                storage.cas(identifier, revision, {'queued', 'running'},
                            lambda report: dict(report, trace=trace, status='running'), increment=False)
            with engine_lock:
                result = get_engine().execute(request, owner=owner, run_id=identifier, on_trace=trace_update)
            status = 'pending' if result['verification']['passed'] else 'blocked'
            storage.cas(identifier, revision, {'queued', 'running'},
                        lambda report: dict(report, **{key: value for key, value in result.items() if key not in {'revision', 'status'}},
                                            status=status), increment=False)
        except Exception:
            try:
                storage.cas(identifier, revision, {'queued', 'running'},
                            lambda report: dict(report, status='failed', error='巡检执行失败，请检查法规索引、嵌入服务和 9B 模型服务'), increment=False)
            except Conflict:
                pass
        finally:
            admission.release()

    @app.post('/api/inspect', status_code=202)
    def inspect(body: Inspection, tasks: BackgroundTasks, who=Depends(actor)):
        if body.project_id != who['project_id']:
            raise HTTPException(403, '无权访问此项目')
        if not admission.acquire(blocking=False):
            raise HTTPException(429, '正在处理较多请求，请稍后重试')
        request = body.model_dump(mode='json')
        request['session_id'] = request['session_id'] or uuid.uuid4().hex
        identifier = uuid.uuid4().hex
        report = dict(request, id=identifier, revision=1, status='queued', owner=who['username'],
                      created_at=time.time(), trace=[], reviews=[], answer={'hazards': [], 'missing_information': []},
                      evidence=[], verification={'passed': False, 'errors': []})
        try:
            storage.save(report)
        except Exception:
            admission.release()
            raise
        tasks.add_task(run, identifier, 1, request, who['username'])
        return {'id': identifier, 'revision': 1, 'status': 'queued', 'session_id': request['session_id']}

    @app.get('/api/reports')
    def reports(who=Depends(actor)):
        rows = storage.visible(who)
        return {'reports': [{key: row[key] for key in ['id', 'revision', 'status', 'query', 'facility', 'created_at', 'session_id']}
                            for row in rows]}

    @app.get('/api/reports/{identifier}')
    def report(identifier: str, who=Depends(actor)):
        return accessible(identifier, who)

    @app.post('/api/reports/{identifier}/review')
    def review(identifier: str, body: Review, who=Depends(actor)):
        if who['role'] not in {'reviewer', 'admin'}:
            raise HTTPException(403, '只有复核员或管理员可以审核')
        previous = accessible(identifier, who)
        if previous['revision'] != body.expected_revision:
            raise HTTPException(409, '报告版本已更新，请刷新后重试')
        try:
            checked = None
            if body.action == 'approve':
                with engine_lock:
                    checked = approval_gate(get_engine(), previous)
            def transform(report):
                report['status'] = {'approve': 'approved', 'return': 'returned', 'reject': 'rejected'}[body.action]
                if checked is not None:
                    report['verification'] = checked
                report['reviews'].append({'action': body.action, 'comment': body.comment,
                                          'reviewer': who['username'], 'at': time.time()})
                return report
            return storage.cas(identifier, body.expected_revision, {'pending', 'blocked'}, transform)
        except Conflict as exc:
            raise HTTPException(409, str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        except Exception as exc:
            raise HTTPException(503, '定稿前复核暂不可用，报告仍保持原状态') from exc

    @app.post('/api/reports/{identifier}/revise', status_code=202)
    def revise(identifier: str, body: Revision, tasks: BackgroundTasks, who=Depends(actor)):
        previous = accessible(identifier, who)
        if previous['owner'] != who['username'] and who['role'] != 'admin':
            raise HTTPException(403, '只有提交者或管理员可以补充报告')
        request = body.input.model_dump(mode='json')
        if request['project_id'] != previous['project_id']:
            raise HTTPException(403, '不能修改报告所属项目')
        request['session_id'] = previous.get('session_id') or uuid.uuid4().hex
        if not admission.acquire(blocking=False):
            raise HTTPException(429, '请求过多，请稍后重试')
        try:
            result = storage.cas(identifier, body.expected_revision, {'returned', 'blocked', 'failed'},
                lambda report: dict(report, **request, status='queued', error=None, trace=[], evidence=[],
                    answer={'hazards': [], 'missing_information': []}, verification={'passed': False, 'errors': []}))
        except Conflict as exc:
            admission.release()
            raise HTTPException(409, str(exc)) from exc
        tasks.add_task(run, identifier, result['revision'], request, previous['owner'])
        return {'id': identifier, 'revision': result['revision'], 'status': 'queued', 'session_id': request['session_id']}

    @app.get('/api/knowledge/documents')
    def documents(as_of: date = Query(default_factory=date.today), jurisdiction: Literal['四川', '全国'] = '四川', who=Depends(actor)):
        try:
            return get_engine().rag.documents(as_of.isoformat(), jurisdiction)
        except Exception as exc:
            raise HTTPException(503, '法规库暂不可用，请检查事实库服务') from exc

    @app.get('/api/knowledge/documents/{doc_id}')
    def document(doc_id: str, as_of: date = Query(default_factory=date.today), jurisdiction: Literal['四川', '全国'] = '四川', who=Depends(actor)):
        try:
            result = get_engine().rag.document(doc_id, as_of.isoformat(), jurisdiction)
        except Exception as exc:
            raise HTTPException(503, '法规原文读取或完整性校验失败') from exc
        if result is None:
            raise HTTPException(404, '法规不存在或不在所选日期地域生效')
        return result

    @app.get('/api/knowledge/search')
    def knowledge_search(q: str = Query(min_length=1, max_length=1000),
                         as_of: date = Query(default_factory=date.today), jurisdiction: Literal['四川', '全国'] = '四川', who=Depends(actor)):
        try:
            request = {'as_of': as_of.isoformat(), 'jurisdiction': jurisdiction, 'retrieval_mode': 'bm25'}
            return get_engine().rag.search(request, [q])
        except Exception as exc:
            raise HTTPException(503, '条款检索暂不可用') from exc

    @app.get('/{path:path}')
    def frontend(path: str):
        candidate = (web / path).resolve()
        if path and web.resolve() in candidate.parents and candidate.is_file():
            return FileResponse(candidate)
        routes = {'', 'login', 'inspect', 'history', 'review', 'regulations', 'monitor', 'sessions', 'memory'}
        if path not in routes and not (path.startswith('reports/') and '/' not in path[8:]):
            raise HTTPException(404, '页面不存在')
        if not (web / 'index.html').is_file():
            raise HTTPException(503, '前端尚未构建，请在 apps/practice 执行 npm ci 和 npm run build')
        return FileResponse(web / 'index.html')

    return app


app = create_app()
