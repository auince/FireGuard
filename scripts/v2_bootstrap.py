import argparse,json,sqlite3,os
from pathlib import Path
from xfagent.v2.config import ROOT
from xfagent.v2.store import Store,digest
from xfagent.v2.facts import prepare_snapshot,publish_snapshot
from xfagent.v2.retrieval import index_snapshot
from xfagent.v2.policy import Policies

p=argparse.ArgumentParser();p.add_argument('--index',action='store_true');args=p.parse_args()
s=Store();s.setup();Policies(s).seed()
legacy=ROOT/'runtime/xfagent.sqlite3'
for candidate in [*(ROOT/'runtime').glob('*.db'),*(ROOT/'runtime').glob('*.sqlite')]:
    try:
        c=sqlite3.connect('file:'+str(candidate)+'?mode=ro',uri=True)
        tables={r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if 'records' not in tables:continue
        for row in c.execute('SELECT * FROM records'):
            record=dict(zip([x[1] for x in c.execute('PRAGMA table_info(records)')],row))
            key=digest([str(candidate),record])
            s.db.legacy_records.update_one({'_id':key},{'$setOnInsert':{'source':str(candidate),'record':record,'sha256':digest(record)}},upsert=True)
    except sqlite3.Error as exc:print('legacy warning',candidate,str(exc))
sid=prepare_snapshot(s)
if args.index:
    from xfagent.v2.structure import materialize_structure
    index_snapshot(s,sid);materialize_structure(s,sid);publish_snapshot(s,sid)
print(json.dumps({'snapshot':sid,'documents':s.db.documents.count_documents({'snapshot_id':sid}),
    'evidence':s.db.evidence.count_documents({'snapshot_id':sid}),'legacy_records':s.db.legacy_records.count_documents({})},ensure_ascii=False))
