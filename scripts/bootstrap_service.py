"""Initialize an empty business database and copy one published immutable KB.

Never copies jobs, feedback, users, or access grants from the source database.
Existing accounts are preserved. Generated secrets are written with mode 0600.
"""
import argparse
import hashlib
import json
import os
import secrets
from pathlib import Path

os.environ.setdefault('XFAGENT_ROOT', str(Path(__file__).resolve().parents[1]))
os.environ.setdefault('XF_V2_DB', 'xfagent_production')
from xfagent.v2.store import Store
from xfagent.v2.config import now
from xfagent.v2.schema import Strategy

parser=argparse.ArgumentParser()
parser.add_argument('--source-db',required=True)
parser.add_argument('--project',default='default')
parser.add_argument('--credentials',default='runtime/service/accounts.json')
args=parser.parse_args()
target=Store(); source=Store(name=args.source_db)
if source.db.name==target.db.name:raise SystemExit('Source and target must differ')
target.setup()
sid=source.active_snapshot()
if not sid:raise SystemExit('Source has no published KB')
# Mongo transaction makes the visible snapshot switch atomic after all rows copy.
if not target.db.settings.find_one({'_id':'active_snapshot'}):
    for name in ['documents','evidence','evidence_locations','source_units']:
        for row in source.db[name].find({'snapshot_id':sid}):
            target.db[name].replace_one({'_id':row['_id']},row,upsert=True)
    snapshot=source.db.snapshots.find_one({'_id':sid})
    if not snapshot:raise SystemExit('Missing snapshot metadata')
    target.db.snapshots.replace_one({'_id':sid},snapshot,upsert=True)
    target.db.settings.update_one({'_id':'active_snapshot'},{'$setOnInsert':{'value':sid}},upsert=True)
target.db.policies.update_one({'_id':'baseline-v2'},{'$setOnInsert':{'state':'active','project_id':args.project,
    'spec':Strategy(name='基础策略').model_dump(),'version':1,'created_at':now()}},upsert=True)
credentials={}
credential_path=Path(args.credentials)
if credential_path.exists() and any(not target.db.users.find_one({'_id':r}) for r in ['inspector','reviewer','admin']):
    raise SystemExit('Credential file already exists; choose a new --credentials path before creating accounts')
for role in ['inspector','reviewer','admin']:
    if target.db.users.find_one({'_id':role}):continue
    salt=secrets.token_bytes(16);password=secrets.token_urlsafe(24)
    target.db.users.insert_one({'_id':role,'salt':salt.hex(),'password_hash':hashlib.scrypt(password.encode(),salt=salt,n=16384,r=8,p=1).hex(),
                              'role':role,'projects':[args.project],'created_at':now()})
    credentials[role]=password
if credentials:
    path=Path(args.credentials);path.parent.mkdir(parents=True,exist_ok=True)
    with os.fdopen(os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600),'w') as file:
        json.dump(credentials,file)
    print('Generated account credentials:',path)
print('Business database initialized:',target.db.name,'snapshot:',target.active_snapshot())
