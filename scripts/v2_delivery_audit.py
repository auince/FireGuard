"""Read-only final deployment evidence; never include credentials or tokens."""
import hashlib,json,subprocess,argparse
from pathlib import Path
import requests
from xfagent.v2.config import ROOT,now
from xfagent.v2.store import Store

parser=argparse.ArgumentParser();parser.add_argument('--gpu-released',action='store_true');args=parser.parse_args()
store=Store()
def command(args):
    return subprocess.check_output(args,text=True,cwd=ROOT).strip()
services=[json.loads(x) for x in command(['docker','compose','-f','deploy/v2/compose.yaml','ps','--format','json']).splitlines()]
services=[{k:s.get(k) for k in ['Name','Service','State','Health','Image','Networks','Publishers']} for s in services]
checks={}
health={}
for name,url in {
    'api':'http://127.0.0.1:8080/api/health',
    'model':'http://127.0.0.1:8000/health',
    'reranker':'http://127.0.0.1:8005/health',
    'tools':'http://127.0.0.1:8007/health',
    'prometheus':'http://127.0.0.1:9090/-/ready',
    'preserved_model':'http://127.0.0.1:8000/v1/models',
}.items():
    try:
        r=requests.get(url,timeout=15);r.raise_for_status()
        health[name]={'status':r.status_code}
        if name=='api':health[name]['details']=r.json()
        checks[name]=True
    except Exception as e:
        health[name]={'error':type(e).__name__+': '+str(e)[:200]};checks[name]=False
if args.gpu_released:
    checks['model_intentionally_stopped']=not checks.pop('model');checks['reranker_intentionally_stopped']=not checks.pop('reranker')
# The pre-existing service may be stopped by its owner; never restart it as an audit side effect.
checks.pop('preserved_model',None)
checks['four_workers']=sum(s['Service']=='worker' and s['State']=='running' for s in services)==4
milvus=next(s for s in services if s['Service']=='milvus')
checks['milvus_loopback_only']=milvus['Networks']!='host' and all(p['URL']=='127.0.0.1' for p in milvus['Publishers']) and any(p['PublishedPort']==19530 for p in milvus['Publishers'])
api=requests.get('http://127.0.0.1:8080/openapi.json',timeout=10).json()
checks['incident_api_loaded']='/api/reports/{identifier}/incidents' in api['paths']
summary=json.loads((ROOT/'reports/v2/system/all-summary.json').read_text())
checks['300_executions']=summary['cases']==300 and summary['execution_errors']==0
load=json.loads((ROOT/'reports/v2/performance/load-workers-4.json').read_text())
checks['all_load_levels_measured']=[x['concurrency'] for x in load['levels']]==[1,2,4,8]
checks['http_acceptance']=json.loads((ROOT/'reports/v2/http_acceptance.json').read_text())['passed']
reconcile=json.loads((ROOT/'reports/v2/reconciliation.json').read_text())
checks['facts_index_reconciled']=reconcile['index_counts_match'] and reconcile['mismatched_quotes']==0
files={}
for pattern in ['src/xfagent/v2/*.py','scripts/v2_*.py','apps/v2/*','deploy/v2/*','tests/v2/*.py','requirements-v2.lock']:
    for p in sorted(ROOT.glob(pattern)):
        if p.is_file():files[str(p.relative_to(ROOT))]=hashlib.sha256(p.read_bytes()).hexdigest()
out=ROOT/'reports/v2'
(out/'final-code-manifest.json').write_text(json.dumps({'created_at':now().isoformat(),'files':files},indent=2))
report={'created_at':now().isoformat(),'checks':checks,'passed':all(checks.values()),'services':services,'health':health,
    'snapshot':store.active_snapshot(),'job_states':{s:store.db.jobs.count_documents({'status':s}) for s in ['queued','running','awaiting_review','awaiting_information','complete','failed']},
    'gpu_snapshot':command(['nvidia-smi','--query-gpu=index,name,memory.used,memory.total,utilization.gpu','--format=csv,noheader']),
    'inference_suspended_by_user_request':args.gpu_released,
    'scope':'Engineering deployment evidence; 300-case numbers are the preserved v2.0 baseline, not new v2.1 expert accuracy.'}
(out/'delivery-audit.json').write_text(json.dumps(report,ensure_ascii=False,indent=2))
print(json.dumps({'checks':checks,'passed':report['passed']},ensure_ascii=False))
assert report['passed']
