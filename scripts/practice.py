"""Independent practice entry point, using the shared Python environment."""
import argparse

parser = argparse.ArgumentParser()
sub = parser.add_subparsers(dest='command', required=True)
serve = sub.add_parser('serve')
serve.add_argument('--host', default='127.0.0.1')
serve.add_argument('--port', type=int, default=8080)
ingest = sub.add_parser('ingest')
ingest.add_argument('path')
ingest.add_argument('--title', required=True)
ingest.add_argument('--source-url', default='')
publish = sub.add_parser('publish-kb')
publish.add_argument('--database', default='xfagent_practice_kb')
sub.add_parser('init-users')
args = parser.parse_args()
if args.command == 'serve':
    import uvicorn
    uvicorn.run('xfagent.practice.app:app', host=args.host, port=args.port)
elif args.command == 'ingest':
    from xfagent.practice.vector import BasicVectorRAG, read_document
    print({'chunks': BasicVectorRAG().ingest(read_document(args.path), args.title, args.source_url)})
elif args.command == 'init-users':
    import json
    import secrets
    from xfagent.practice.storage import Storage
    store = Storage()
    path = store.path.parent / 'credentials.json'
    if path.exists():
        parser.error('账号已初始化，请使用已有凭据文件')
    credentials = []
    for role in ['inspector', 'reviewer', 'admin']:
        password = secrets.token_urlsafe(18)
        store.add_user(role, password, role)
        credentials.append({'username': role, 'password': password, 'role': role})
    import os
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, 'w') as output:
        json.dump(credentials, output, ensure_ascii=False, indent=2)
    print({'credentials_file': str(path), 'note': '私有凭据文件，不提交 Git'})
else:
    if not args.database.startswith('xfagent_practice_'):
        parser.error('练手发布只允许 xfagent_practice_ 数据库前缀')
    from xfagent.v2.store import Store
    from xfagent.v2.facts import prepare_snapshot, publish_snapshot
    from xfagent.v2.retrieval import index_snapshot
    store = Store(name=args.database)
    store.setup()
    snapshot = prepare_snapshot(store)
    count = index_snapshot(store, snapshot)
    publish_snapshot(store, snapshot)
    print({'database': args.database, 'snapshot': snapshot, 'evidence': count})
