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
args = parser.parse_args()
if args.command == 'serve':
    import uvicorn
    uvicorn.run('xfagent.practice.app:app', host=args.host, port=args.port)
elif args.command == 'ingest':
    from xfagent.practice.vector import BasicVectorRAG, read_document
    print({'chunks': BasicVectorRAG().ingest(read_document(args.path), args.title, args.source_url)})
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
