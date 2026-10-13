"""Finish deployment checks only after the frozen 300-case run has ended."""
import json,os,subprocess,time
from pathlib import Path
from xfagent.v2.config import ROOT,MILVUS
from xfagent.v2.store import Store
from xfagent.v2.retrieval import collection
from pymilvus import MilvusClient

os.chdir(ROOT)
summary=ROOT/'reports/v2/system/all-summary.json'
while not summary.exists():time.sleep(15)
if json.loads(summary.read_text())['cases']!=300:raise RuntimeError('完整300例尚未结束')
compose=['docker','compose','-f','deploy/v2/compose.yaml']
# Host-network Milvus listens on wildcard sockets regardless of proxy.ip.
# Bridge networking with an explicit loopback mapping contains all other ports.
subprocess.run(compose+['up','-d','milvus'],check=True)
store=Store();sid=store.active_snapshot();expected=store.db.evidence.count_documents({'snapshot_id':sid})
deadline=time.monotonic()+180
while True:
    try:
        client=MilvusClient(uri=MILVUS,timeout=5)
        if int(client.get_collection_stats(collection(sid))['row_count'])!=expected:raise RuntimeError('索引数量未恢复')
        break
    except Exception:
        if time.monotonic()>deadline:raise
        time.sleep(3)
subprocess.run(compose+['up','-d','--scale','worker=4','worker'],check=True)
subprocess.run(compose+['restart','api','worker'],check=True)
time.sleep(4)
env=os.environ.copy();env['PYTHONPATH']='src'
for script,args,log in [('v2_live_acceptance.py',[],'live-complete'),('v2_load_test.py',['--worker-count','4'],'load-workers-4')]:
    with (ROOT/'runtime/v2'/f'{log}.log').open('w') as f:
        subprocess.run(['.venv-v2/bin/python','scripts/'+script]+args,env=env,stdout=f,stderr=f,check=True)
print('Final live workflow and four-worker load measurements completed',flush=True)
