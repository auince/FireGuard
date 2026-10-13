"""Manage only processes started by this project, with command-line identity checks."""
import argparse,subprocess,os,json,signal,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
SERVICES={
 'model4b':('.venv-model/bin/python',['scripts/model_server.py','--model','/opt/models/qwen3-vl-4b','--adapter','/opt/xfagent/artifacts/trl/qwen3vl4b_hydrant_sft_grpo_v41_full_20260717/grpo_model/checkpoint-200','--port','8003','--name','xf-qwen3vl4b-grpo200'],{'CUDA_VISIBLE_DEVICES':'2','HF_HUB_OFFLINE':'1'}),
 'model':('.venv-model/bin/python',['scripts/model_server.py'],{'CUDA_VISIBLE_DEVICES':'0','HF_HUB_OFFLINE':'1'}),
 'embedding':('/opt/conda/envs/embedding/bin/python',['scripts/embedding_server.py'],{'HF_HUB_OFFLINE':'1'}),
 'multimodal':('.venv-model/bin/python',['scripts/multimodal_server.py'],{'CUDA_VISIBLE_DEVICES':'','HF_HUB_OFFLINE':'1'}),
 'web':('.venv/bin/python',['-m','xfagent.cli','serve'],{}),
}
def main():
 p=argparse.ArgumentParser();p.add_argument('action',choices=['start','stop','status']);p.add_argument('names',nargs='*');a=p.parse_args()
 run=ROOT/'runtime/services';run.mkdir(parents=True,exist_ok=True);logs=ROOT/'runtime/logs';logs.mkdir(exist_ok=True)
 for name in a.names or ['model','embedding','multimodal','web']:
  py,args,env=SERVICES[name];pidfile=run/(name+'.json');old=json.loads(pidfile.read_text()) if pidfile.exists() else {};pid=old.get('pid',0)
  cmdline=Path(f'/proc/{pid}/cmdline');alive=cmdline.exists() and all(x.encode() in cmdline.read_bytes() for x in old.get('identity',[]))
  if a.action=='status':print(name,pid,'running' if alive else 'stopped');continue
  if a.action=='stop':
   if alive:
    os.kill(pid,signal.SIGTERM)
    for _ in range(100):
     if not Path(f'/proc/{pid}/cmdline').exists():break
     time.sleep(.1)
   print(name,'stop requested' if alive else 'stopped');continue
  if alive:print(name,'already running',pid);continue
  log=(logs/(name+'.log')).open('ab');command=[str(ROOT/py) if not py.startswith('/') else py,*args]
  proc=subprocess.Popen(command,cwd=ROOT,env={**os.environ,**env},stdin=subprocess.DEVNULL,stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
  pidfile.write_text(json.dumps({'pid':proc.pid,'identity':args,'command':command,'started':time.time()}));print(name,proc.pid)
if __name__=='__main__':main()
