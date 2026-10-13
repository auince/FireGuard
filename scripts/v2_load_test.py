"""Real API queue/load measurement; one worker, same 9B weights. Not a capacity claim."""
import concurrent.futures,json,time,uuid,subprocess,argparse
import numpy as np,requests
from xfagent.v2.config import ROOT
from xfagent.v2.store import Store
parser=argparse.ArgumentParser();parser.add_argument('--worker-count',type=int,default=1);args=parser.parse_args()
s=Store();base='http://127.0.0.1:8080';out=ROOT/'reports/v2/performance';out.mkdir(parents=True,exist_ok=True)
account=next(x for x in json.loads((ROOT/'runtime/v2/credentials.json').read_text()) if x['username']=='admin')
r=requests.post(base+'/api/auth/login',json=account);r.raise_for_status();headers={'Authorization':'Bearer '+r.json()['access_token']}
def one(i):
 started=time.monotonic();r=requests.post(base+'/api/retrieve',headers=headers,json={'query':'室内消火栓被杂物遮挡，哪些原文条款可以作为核查参考？','facility':'indoor_hydrant','session_id':'load-'+uuid.uuid4().hex});r.raise_for_status();identifier=r.json()['id']
 while time.monotonic()-started<2400:
  j=requests.get(base+'/api/jobs/'+identifier,headers=headers).json()
  if j['status'] not in ['running','queued']:break
  time.sleep(1)
 doc=s.db.jobs.find_one({'_id':identifier});queue=(doc['started_at']-doc['created_at']).total_seconds()
 return {'run_id':identifier,'elapsed':time.monotonic()-started,'queue_seconds':queue,'status':j['status'],'calls':j.get('result',{}).get('calls',0),'active_seconds':j.get('result',{}).get('active_seconds',0)}
report={'worker_count':args.worker_count,'model':'same_Qwen3.5_9B_vLLM_GPU3','workload':'text_law_query_with_generation_and_verification','samples_per_level':'one burst; engineering smoke, insufficient for stable P95','levels':[]}
for n in [1,2,4,8]:
 t=time.monotonic()
 with concurrent.futures.ThreadPoolExecutor(max_workers=n) as pool:rows=list(pool.map(one,range(n)))
 elapsed=time.monotonic()-t;values=[x['elapsed'] for x in rows]
 level={'concurrency':n,'n':len(rows),'throughput_per_minute':len(rows)/elapsed*60,'p50_seconds':float(np.percentile(values,50)),'p95_seconds':float(np.percentile(values,95)),'max_queue_seconds':max(x['queue_seconds'] for x in rows),'runs':rows,
 'gpu_snapshot':subprocess.check_output(['nvidia-smi','--query-gpu=index,memory.used,memory.total,utilization.gpu','--format=csv,noheader'],text=True)}
 report['levels'].append(level);(out/('load.json' if args.worker_count==1 else 'load-workers-'+str(args.worker_count)+'.json')).write_text(json.dumps(report,ensure_ascii=False,indent=2));print(n,level['p50_seconds'],level['p95_seconds'],flush=True)
