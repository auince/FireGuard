"""Production entry point. Configure environment before importing execution modules."""
import argparse
import os
from pathlib import Path

os.environ.setdefault('XFAGENT_ROOT', str(Path(__file__).resolve().parents[1]))
os.environ.setdefault('XF_V2_DB', 'xfagent_production')
os.environ.setdefault('XF_V2_REDIS', 'redis://127.0.0.1:6379/2')

parser = argparse.ArgumentParser()
parser.add_argument('command', choices=['serve', 'worker'])
parser.add_argument('--host', default='127.0.0.1')
parser.add_argument('--port', type=int, default=8080)
args = parser.parse_args()
if args.command == 'worker':
    from xfagent.v2.worker import main
    main()
else:
    import uvicorn
    uvicorn.run('xfagent.server.app:create_app', factory=True, host=args.host, port=args.port,
                proxy_headers=False, timeout_graceful_shutdown=30)
