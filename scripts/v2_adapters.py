"""Manage only v2 host adapters; verify process identity and GPU availability first."""
import argparse,json,os,signal,subprocess,time
from pathlib import Path
import requests
ROOT=Path(__file__).resolve().parents[1];RUNTIME=ROOT/'runtime/v2';RUNTIME.mkdir(exist_ok=True,parents=True)
SERVICES={'tools':{'script':'v2_tool_server.py','python':'.venv-v2/bin/python','url':'http://127.0.0.1:8007/'},
 'reranker':{'script':'v2_reranker_server.py','python':'.venv-model/bin/python','url':'http://127.0.0.1:8005/','gpu':'2'}}
def healthy(c):
 try:return requests.get(c['url'],timeout=2).status_code==200
 except requests.RequestException:return False
p=argparse.ArgumentParser();p.add_argument('action',choices=['start','status','stop']);p.add_argument('services',nargs='*',default=list(SERVICES));a=p.parse_args()
for name in a.services:
 c=SERVICES[name];pidfile=RUNTIME/(name+'.managed.pid')
 if a.action=='status':print(name,'ready' if healthy(c) else 'unavailable');continue
 if a.action=='start':
  if healthy(c):print(name,'already ready; preserved');continue
  env=os.environ.copy()
  if c.get('gpu'):
   free=int(subprocess.check_output(['nvidia-smi','-i',c['gpu'],'--query-gpu=memory.free','--format=csv,noheader,nounits'],text=True).strip())
   if free<14000:raise RuntimeError('GPU '+c['gpu']+' has insufficient free memory; no existing process stopped')
   env['CUDA_VISIBLE_DEVICES']=c['gpu']
  with (RUNTIME/(name+'.managed.log')).open('ab') as log:
   proc=subprocess.Popen([str(ROOT/c['python']),str(ROOT/'scripts'/c['script'])],cwd=ROOT,env=env,stdin=subprocess.DEVNULL,stdout=log,stderr=log,start_new_session=True)
  pidfile.write_text(str(proc.pid));print(name,'starting',proc.pid)
 else:
  if not pidfile.exists():raise RuntimeError('No managed PID; refusing to stop an unrelated service')
  pid=int(pidfile.read_text());cmd=Path('/proc')/str(pid)/'cmdline'
  if cmd.exists():
   text=cmd.read_bytes().decode().replace('\0',' ')
   if str(ROOT/'scripts'/c['script']) not in text:raise RuntimeError('Process identity mismatch')
   os.kill(pid,signal.SIGTERM)
  pidfile.unlink();print(name,'stopped managed process')
