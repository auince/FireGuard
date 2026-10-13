"""Register an operator-selected local model directory's SHA256 manifest.

Run in a maintenance window, with API/worker on the same model configuration.
Existing replay gates intentionally stop matching after weights change.
"""
import argparse
import hashlib
import os
from pathlib import Path

os.environ.setdefault('XF_V2_DB','xfagent_production')
from xfagent.v2.store import Store,digest
from xfagent.v2.config import now
from xfagent.v2.model_routes import manifest

parser=argparse.ArgumentParser()
parser.add_argument('model_directory',type=Path)
args=parser.parse_args()
root=args.model_directory.resolve()
files=sorted(p for p in root.rglob('*') if p.is_file() and p.suffix in {'.safetensors','.bin','.json'})
if not any(p.suffix in {'.safetensors','.bin'} for p in files):raise SystemExit('No model weights found')
entries=[]
for path in files:
    h=hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda:stream.read(8*1024*1024),b''):h.update(chunk)
    entries.append({'file':str(path.relative_to(root)),'sha256':h.hexdigest()})
fingerprint=digest(entries);store=Store()
store.db.settings.update_one({'_id':'generator_fingerprint'},{'$set':{'value':fingerprint,'manifest':entries,
    'registered_at':now(),'model_routes_hash':digest(manifest()),'source':'operator_selected_model_directory'}},upsert=True)
store.audit('model-registry',fingerprint,'model_fingerprint_registered',fingerprint=fingerprint)
print('Registered model fingerprint:',fingerprint)
