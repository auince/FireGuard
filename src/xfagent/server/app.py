"""Same-origin business console. Durable execution remains in xfagent.v2.

One app instance per process: the legacy platform router owns a module-level Store.
Run a separate worker process; HTTP requests never execute model workflows.
"""
import os
import time
from contextlib import asynccontextmanager
from datetime import timedelta
from pathlib import Path

import jwt
from fastapi import APIRouter, Depends, FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.trustedhost import TrustedHostMiddleware

from xfagent.v2 import api as core
from xfagent.v2.auth import actor, access, secret
from xfagent.v2.config import MODEL, ROOT, now, today
from xfagent.v2.schema import Actor, InspectionInput, Review, Strategy
from xfagent.v2.store import Store, digest
from xfagent.v2.memory import MemoryContextBuilder
from xfagent.practice.rag import TrustedRAG

COOKIE = 'xf_session'
STATUS = {'awaiting_review': 'pending', 'awaiting_information': 'returned', 'complete': 'approved'}


def timestamp(value):
    return value.timestamp() if hasattr(value, 'timestamp') else value


def create_app(store=None):
    core.store = store or Store()
    storage = core.store
    rag = TrustedRAG(storage)

    @asynccontextmanager
    async def lifespan(app):
        secret()
        storage.setup()
        storage.db.policies.update_one({'_id':'baseline-v2'},{'$setOnInsert':{
            'state':'active','project_id':'default','spec':Strategy(name='基础策略').model_dump(),
            'version':1,'created_at':now()}},upsert=True)
        storage.db.auth_sessions.create_index('expires_at', expireAfterSeconds=0)
        yield

    app = FastAPI(title='消防巡检管理平台', version='7.0.0', lifespan=lifespan)
    app.state.store = storage
    hosts = os.getenv('XF_ALLOWED_HOSTS', '127.0.0.1,localhost').split(',')
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=hosts)

    @app.exception_handler(ValueError)
    async def invalid(request, exc):
        return JSONResponse({'detail': str(exc)}, status_code=400)

    @app.middleware('http')
    async def boundary(request, call_next):
        if request.method in {'POST', 'PUT', 'PATCH', 'DELETE'}:
            origin = request.headers.get('origin')
            allowed = os.getenv('XF_PUBLIC_ORIGIN', '').rstrip('/') or str(request.base_url).rstrip('/')
            if origin and origin != allowed:
                return JSONResponse({'detail': '请求来源不受信任'}, status_code=403)
            # Count streamed bodies too; a missing Content-Length is not a bypass.
            size = 0
            chunks = []
            async for chunk in request.stream():
                size += len(chunk)
                if size > 15 * 1024 * 1024:
                    return JSONResponse({'detail': '请求过大'}, status_code=413)
                chunks.append(chunk)
            request._body = b''.join(chunks)
        response = await call_next(request)
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['Referrer-Policy'] = 'same-origin'
        response.headers['Content-Security-Policy'] = "default-src 'self'; img-src 'self' data: blob:; style-src 'self'; script-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'self'"
        if request.url.path.startswith('/api/'):
            response.headers['Cache-Control'] = 'no-store'
        return response

    def current(request: Request):
        token = request.cookies.get(COOKIE, '')
        if not token:
            authorization = request.headers.get('authorization', '')
            token = authorization[7:] if authorization.lower().startswith('bearer ') else ''
        try:
            data = jwt.decode(token, secret(), algorithms=['HS256'], audience='xfagent-v2',
                              options={'require': ['sub', 'exp', 'iat', 'aud']})
            session = storage.db.auth_sessions.find_one({'_id': digest(token), 'expires_at': {'$gt': now()}})
            user = storage.db.users.find_one({'_id': data['sub'], 'disabled': {'$ne': True}})
            if not session or not user:
                raise ValueError('expired')
            # Refresh authorization from the current user record, not stale JWT roles.
            return Actor(user_id=user['_id'], role=user['role'], projects=user['projects'])
        except (ValueError, KeyError, jwt.PyJWTError):
            raise HTTPException(401, '请重新登录')

    app.dependency_overrides[actor] = current

    def user_view(who):
        return {'username': who.user_id, 'role': who.role, 'projects': who.projects,
                'project_id': who.projects[0] if who.projects else None}

    @app.post('/api/login')
    def login(body: dict, request: Request, response: Response):
        user = storage.db.users.find_one({'_id': str(body.get('username', '')), 'disabled': {'$ne': True}})
        if not user:
            # Core login still applies rate limits and constant-time hash comparison.
            core.login(body, request)
            raise HTTPException(401, '登录失败')
        result = core.login(body, request)
        token = result['access_token']
        storage.db.auth_sessions.insert_one({'_id': digest(token), 'owner': user['_id'],
                                            'expires_at': now()+timedelta(hours=8)})
        response.set_cookie(COOKIE, token, httponly=True, samesite='strict', max_age=28800,
                            secure=os.getenv('XF_COOKIE_SECURE', 'true').lower() == 'true', path='/')
        return {'actor': user_view(Actor(user_id=user['_id'], role=user['role'], projects=user['projects']))}

    @app.post('/api/logout')
    def logout(request: Request, response: Response):
        storage.db.auth_sessions.delete_one({'_id': digest(request.cookies.get(COOKIE, ''))})
        response.delete_cookie(COOKIE, path='/')
        return {'ok': True}

    @app.get('/api/me')
    def me(who: Actor = Depends(current)):
        return {'actor': user_view(who)}

    @app.get('/api/health')
    def health():
        return {'stage': 7, 'model': MODEL, 'inference': os.getenv('XF_INFERENCE_MODE','external_service'), 'execution': 'durable_worker'}

    def scoped(who):
        query = {'project_id': {'$in': who.projects}, 'kind': {'$in': ['inspection', 'retrieval', 'annotation']}}
        if who.role == 'inspector':
            query['owner'] = who.user_id
        return query

    def report_view(row, detail=False):
        state = row.get('result', {})
        report = state.get('report', {})
        req = state.get('request', row['input'])
        status = STATUS.get(row['status'], row['status'])
        if row['status'] == 'complete' and report.get('status') == 'rejected':
            status = 'rejected'
        if row['status'] == 'awaiting_review' and not report.get('verification', {}).get('passed'):
            status = 'blocked'
        value = {'id': row['_id'], 'owner': row['owner'], 'project_id': row['project_id'],
                 'revision': row['revision'], 'status': status, 'durable_status': row['status'],
                 'query': req['query'], 'facility': state.get('facility', req.get('facility')),
                 'session_id': req.get('session_id'), 'created_at': timestamp(row['created_at'])}
        if detail:
            conclusions = report.get('conclusions', state.get('conclusions', []))
            value.update({k: req.get(k) for k in ['scene', 'as_of', 'jurisdiction', 'retrieval_mode']})
            value.update(conclusions=conclusions, observations=report.get('observations', []),
                         image='/api/jobs/'+row['_id']+'/image' if req.get('processed_image_path') else None,
                         detector=report.get('detector', state.get('detector', {})),
                         similar_cases=report.get('similar_cases', []), evidence=report.get('evidence', []),
                         verification=report.get('verification', {}), trace=state.get('trace', []),
                         model=report.get('model_version', MODEL), model_calls=state.get('calls', 0),
                         warnings=report.get('warnings', []), error=row.get('error'),
                         answer={'hazards': [{'description': c['text'], 'suggestion': c.get('recommendation', ''),
                                              'evidence_ids': c.get('evidence_ids', [])} for c in conclusions],
                                 'missing_information': report.get('verification', {}).get('missing_fields', [])})
            value['reviews'] = [{**x.get('decision', {}), 'reviewer': x.get('reviewer'), 'at': timestamp(x['at'])}
                               for x in storage.db.events.find({'run_id': row['_id'], 'event': 'human_review'}).sort('at', 1)]
        return core.clean(value)

    @app.get('/api/reports')
    def reports(who: Actor = Depends(current)):
        rows = storage.db.jobs.find(scoped(who)).sort('created_at', -1).limit(100)
        return {'reports': [report_view(row) for row in rows], 'limit': 100}

    @app.get('/api/reports/{identifier}')
    def report(identifier: str, who: Actor = Depends(current)):
        row = storage.db.jobs.find_one({'_id': identifier})
        access(who, row)
        return report_view(row, True)

    @app.post('/api/reports/{identifier}/review', status_code=202)
    def review(identifier: str, body: Review, who: Actor = Depends(current)):
        row=storage.db.jobs.find_one({'_id':identifier})
        access(who,row,write=True)
        if row['revision']!=body.expected_revision or row['status'] not in {'awaiting_review','awaiting_information'}:
            raise HTTPException(409,'报告已变化，请刷新后审核')
        core.review(identifier, body, who)
        return report(identifier, who)

    @app.get('/api/sessions')
    def sessions(who: Actor = Depends(current)):
        query = scoped(who)
        query['owner'] = who.user_id
        query['input.session_id'] = {'$type': 'string'}
        groups = storage.db.jobs.aggregate([{'$match': query}, {'$sort': {'created_at': -1}},
            {'$group': {'_id': '$input.session_id', 'title': {'$first': '$input.query'},
                        'created_at': {'$min': '$created_at'}, 'updated_at': {'$max': '$created_at'}}},
            {'$sort': {'updated_at': -1}}, {'$limit': 100}])
        return {'sessions': [{'id': x['_id'], 'title': x['title'], 'created_at': timestamp(x['created_at']),
                              'updated_at': timestamp(x['updated_at'])} for x in groups]}

    @app.get('/api/sessions/{identifier}')
    def session(identifier: str, who: Actor = Depends(current)):
        query = {**scoped(who), 'owner': who.user_id, 'input.session_id': identifier}
        return {'id': identifier, 'turns': [report_view(x, True) for x in storage.db.jobs.find(query).sort('created_at', 1).limit(100)]}

    @app.get('/api/knowledge/documents')
    def documents(as_of: str = '', jurisdiction: str = '四川', who: Actor = Depends(current)):
        return core.clean(rag.documents(as_of or today(), jurisdiction))

    @app.get('/api/knowledge/documents/{identifier}')
    def document(identifier: str, as_of: str = '', jurisdiction: str = '四川', who: Actor = Depends(current)):
        value = rag.document(identifier, as_of or today(), jurisdiction)
        if value is None:
            raise HTTPException(404, '法规不存在或当前不可用')
        return core.clean(value)

    @app.get('/api/knowledge/search')
    def search_get(q: str, as_of: str = '', jurisdiction: str = '四川', who: Actor = Depends(current)):
        body=InspectionInput(query=q,as_of=as_of or today(),jurisdiction=jurisdiction,project_id=who.projects[0])
        return core.clean(rag.search(body.model_dump(mode='json'),[q]))

    @app.post('/api/knowledge/search')
    def search(body: InspectionInput, who: Actor = Depends(current)):
        if body.project_id not in who.projects:
            raise HTTPException(403, '项目访问被拒绝')
        return core.clean(rag.search(body.model_dump(mode='json'), [body.query]))

    @app.get('/api/memory')
    def memory(who: Actor = Depends(current)):
        row = storage.db.memories.find_one({'owner': who.user_id, 'project_id': who.projects[0], 'kind': 'user',
            'content.report_detail': {'$exists': True}, 'expires_at': {'$gt': now()}}) or {}
        return {'preferences': {'answer_style': row.get('content', {}).get('report_detail')}, 'context_budget_bytes': 1800,
                'working_ttl_minutes': 30, 'layers': [
                    {'name': '会话工作记忆', 'description': 'Redis 按人员、项目、会话隔离，30 分钟自动过期。'},
                    {'name': '历史与个人偏好', 'description': '情景记忆 90 天、摘要与自愿保存的偏好 180 天。'},
                    {'name': '组织知识', 'description': '管理员审核、绑定当前有效条款；只作背景参考。'},
                    {'name': '策略记忆', 'description': '经回放验证和灰度发布的受控策略。'}]}

    @app.post('/api/memory/preferences')
    def preference(body: dict, who: Actor = Depends(current)):
        if body.get('answer_style') not in {'concise', 'detailed'}:
            raise ValueError('不支持的回答偏好')
        return {'id': MemoryContextBuilder(storage).preference(who, who.projects[0], 'report_detail', body['answer_style'], body.get('consent'))}

    @app.delete('/api/memory/preferences')
    def forget(who: Actor = Depends(current)):
        result = storage.db.memories.delete_many({'owner': who.user_id, 'project_id': who.projects[0], 'kind': 'user',
                                                  'content.report_detail': {'$exists': True}})
        return {'deleted': result.deleted_count}

    # Reuse the durable platform routes, excluding superseded console contracts.
    excluded = {'/', '/api/auth/login', '/api/health', '/api/reports', '/api/reports/{identifier}/review', '/metrics', '/api/metrics'}
    platform = APIRouter()
    for route in core.app.routes:
        if route.path.startswith('/api/') and route.path not in excluded:
            platform.routes.append(route)

    app.include_router(platform)

    dist = ROOT / 'apps/practice/dist'
    if dist.is_dir():
        app.mount('/assets', StaticFiles(directory=dist/'assets'), name='assets')

        @app.get('/{path:path}')
        def console(path: str):
            if path.startswith('api/'):
                raise HTTPException(404, '接口不存在')
            candidate = (dist/path).resolve()
            if candidate.is_relative_to(dist.resolve()) and candidate.is_file():
                return FileResponse(candidate)
            return FileResponse(dist/'index.html')
    return app
