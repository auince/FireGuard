"""Final validation, then unconditionally release this task's GPU services."""
import json,os,subprocess,hashlib,time
from xfagent.v2.config import ROOT,now
from xfagent.v2.store import Store
from xfagent.v2.observability import TraceAggregator
os.chdir(ROOT);out=ROOT/'reports/v2/optimization-20261004';env=os.environ.copy();env['PYTHONPATH']='src';env['XF_MODEL_URL']='http://127.0.0.1:8000/v1'
compose=['docker','compose','-f','deploy/v2/compose.yaml'];result={'started_at':now().isoformat(),'checks':{}}
def run(name,args):
    with (out/(name+'.log')).open('w') as f:
        subprocess.run(args,env=env,stdout=f,stderr=f,check=True)
    result['checks'][name]=True;print(name,'passed',flush=True)
try:
    run('restart',compose+['restart','api','worker'])
    run('tests-final',['.venv-v2/bin/pytest','-q','tests/v2'])
    run('live-final',['.venv-v2/bin/python','scripts/v2_live_acceptance.py'])
    (out/'live-final.json').write_bytes((ROOT/'reports/v2/live/results.json').read_bytes())
    run('http-final',['.venv-v2/bin/python','scripts/v2_http_acceptance.py'])
    (out/'http-final.json').write_bytes((ROOT/'reports/v2/http_acceptance.json').read_bytes())
    run('policy-final',['.venv-v2/bin/python','scripts/v2_optimization_eval.py','replay'])
    run('reconcile-final',['.venv-v2/bin/python','scripts/v2_reconcile.py'])
    before=json.loads((out/'core-before-idempotency.json').read_text())
    changed=[p for p,h in before.items() if hashlib.sha256((ROOT/p).read_bytes()).hexdigest()!=h]
    (out/'post-system-diff.json').write_text(json.dumps({'changed_after_18_case_run':changed,'purpose':'Only request idempotency compatibility changed; tested separately via unit and HTTP tests.'},indent=2))
    (out/'trace-stats.json').write_text(json.dumps(TraceAggregator(Store()).recent('default'),ensure_ascii=False,indent=2))
    run('audit-online',['.venv-v2/bin/python','scripts/v2_delivery_audit.py'])
    (out/'audit-online.json').write_bytes((ROOT/'reports/v2/delivery-audit.json').read_bytes())
except Exception as exc:
    result['error']=type(exc).__name__+':'+str(exc)
    raise
finally:
    result['model_stop_returncode']=subprocess.run(compose+['stop','model']).returncode
    result['reranker_stop_returncode']=subprocess.run(['.venv-v2/bin/python','scripts/v2_adapters.py','stop','reranker']).returncode
    time.sleep(3)
    result['gpu_after']=subprocess.check_output(['nvidia-smi','--query-gpu=index,name,memory.used,memory.total','--format=csv,noheader'],text=True)
    result['finished_at']=now().isoformat()
    (out/'final-validation-and-gpu-release.json').write_text(json.dumps(result,ensure_ascii=False,indent=2))
    print('GPU services released:',result['gpu_after'],flush=True)
