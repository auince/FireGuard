"""Own-service pause/restore and two bounded, monitored training subprocesses."""
import subprocess,sys,json,time,os,signal,hashlib
from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo
ROOT=Path(__file__).resolve().parents[1]
def write(p,x):p.write_text(json.dumps(x,ensure_ascii=False,indent=2)+'\n')
def service(action):return subprocess.run([str(ROOT/'.venv/bin/python'),'scripts/services.py',action,'model'],cwd=ROOT,check=True,capture_output=True,text=True).stdout

def main():
 import requests
 from xfagent.data import rows,text_of
 from xfagent.rewards import parse_answer
 run=ROOT/'runtime/experiments'/('grpo_capacity_'+datetime.now(ZoneInfo('Asia/Shanghai')).strftime('%Y%m%d_%H%M%S'));run.mkdir(parents=True,exist_ok=False)
 selected=[];counts={}
 for row in rows(ROOT/'data/training/train.jsonl'):
  key=parse_answer(text_of(row,'assistant'))['verdict']
  if counts.get(key,0)>=4:continue
  selected.append(row);counts[key]=counts.get(key,0)+1
 data=run/'probe_train.jsonl';data.write_text(''.join(json.dumps(r,ensure_ascii=False)+'\n' for r in selected))
 summary={'run':str(run),'status':'preflight','samples':len(selected),'verdict_counts':counts,'started_at':datetime.now(ZoneInfo('Asia/Shanghai')).isoformat(),'runs':[],
  'training_source_sha256':hashlib.sha256((ROOT/'data/training/train.jsonl').read_bytes()).hexdigest()}
 summary['gpu_before']=subprocess.check_output(['nvidia-smi','--query-gpu=index,name,memory.total,memory.used,memory.free,utilization.gpu','--format=csv'],text=True)
 write(run/'summary.json',summary);print('RUN_DIR',run,flush=True)
 active=None;paused=False
 def interrupt(sig,frame):raise KeyboardInterrupt()
 signal.signal(signal.SIGTERM,interrupt);signal.signal(signal.SIGINT,interrupt)
 try:
  response=requests.get('http://127.0.0.1:8000/health',timeout=5);response.raise_for_status();summary['inference_before']=response.json()
  if response.json().get('base')!='/opt/models/Qwen3.5_9B' or response.json().get('adapter') is not None:raise RuntimeError('Unexpected inference model; do not alter service')
  paused=True;summary['pause_result']=service('stop')
  for _ in range(60):
   mem=int(subprocess.check_output(['nvidia-smi','-i','0','--query-gpu=memory.used','--format=csv,noheader,nounits'],text=True).strip())
   if mem<1024:break
   time.sleep(1)
  else:raise RuntimeError('GPU 0 was not released; abort instead of competing with another workload')
  summary['status']='probing';write(run/'summary.json',summary)
  trials=[('small_g2',2,2,256,False),('practical_g4',4,4,768,False)]
  for name,g,acc,pixels,checkpoint in trials:
   output=run/name;log=run/(name+'.log');gpu_log=run/(name+'_gpu.jsonl')
   command=[str(ROOT/'.venv-model/bin/python'),'scripts/probe_grpo_capacity.py','--output',str(output),'--data',str(data),'--generations',str(g),'--accumulation',str(acc),'--image-tokens-cap',str(pixels),'--steps','2']
   if checkpoint:command.append('--checkpointing')
   print('START',name,flush=True);t=time.time();peak=0
   with log.open('w') as f:
    active=subprocess.Popen(command,cwd=ROOT,env={**os.environ,'CUDA_VISIBLE_DEVICES':'0','HF_HUB_OFFLINE':'1','TOKENIZERS_PARALLELISM':'false','PYTHONUNBUFFERED':'1'},stdout=f,stderr=subprocess.STDOUT,start_new_session=True)
    while active.poll() is None:
     raw=subprocess.check_output(['nvidia-smi','-i','0','--query-gpu=memory.used,utilization.gpu','--format=csv,noheader,nounits'],text=True).strip();mem,util=[int(x.strip()) for x in raw.split(',')];peak=max(peak,mem)
     with gpu_log.open('a') as gf:gf.write(json.dumps({'elapsed_seconds':time.time()-t,'memory_mib':mem,'utilization_percent':util})+'\n')
     if time.time()-t>1200:
      os.killpg(active.pid,signal.SIGTERM)
      try:active.wait(timeout=30)
      except subprocess.TimeoutExpired:os.killpg(active.pid,signal.SIGKILL);active.wait()
      break
     time.sleep(1)
    code=active.wait();active=None
   result={'name':name,'returncode':code,'peak_nvidia_smi_mib':peak,'wall_seconds':time.time()-t,'command':command}
   if (output/'capacity.json').exists():result['capacity']=json.loads((output/'capacity.json').read_text())
   summary['runs'].append(result);write(run/'summary.json',summary);print('FINISH',name,code,'PEAK_MIB',peak,flush=True)
   if code and name=='practical_g4' and 'out of memory' in log.read_text().lower():trials.append(('practical_g4_checkpointed',4,4,768,True))
  summary['status']='complete'
 except BaseException as e:
  summary.update(status='interrupted_or_failed',error=repr(e))
 finally:
  if active is not None and active.poll() is None:
   os.killpg(active.pid,signal.SIGTERM)
   try:active.wait(timeout=30)
   except subprocess.TimeoutExpired:os.killpg(active.pid,signal.SIGKILL);active.wait()
  if paused:
   try:
    summary['restore_result']=service('start')
    for _ in range(120):
     try:
      r=requests.get('http://127.0.0.1:8000/health',timeout=2)
      if r.ok:summary['inference_restored']=r.json();break
     except requests.RequestException:pass
     time.sleep(1)
    else:summary['restore_error']='Model did not become healthy within 120 seconds'
   except Exception as e:summary['restore_error']=repr(e)
  summary['finished_at']=datetime.now(ZoneInfo('Asia/Shanghai')).isoformat();write(run/'summary.json',summary);print('DONE',run,'RESTORED',bool(summary.get('inference_restored')),flush=True)
if __name__=='__main__':main()
