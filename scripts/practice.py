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
args = parser.parse_args()
if args.command == 'serve':
    import uvicorn
    uvicorn.run('xfagent.practice.app:app', host=args.host, port=args.port)
else:
    from xfagent.practice.vector import BasicVectorRAG, read_document
    print({'chunks': BasicVectorRAG().ingest(read_document(args.path), args.title, args.source_url)})
