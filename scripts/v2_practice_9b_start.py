"""Launch the installed 9B server only if a GPU has sufficient free memory."""
import argparse,json,os,socket,subprocess,time
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]

def main():
 parser=argparse.ArgumentParser();parser.add_argument('--gpu',default='auto');args=parser.parse_args()
 with socket.socket() as probe:
  if probe.connect_ex(('127.0.0.1',8000))==0:
   print(json.dumps({'status':'endpoint_already_running','url':'http://127.0.0.1:8000/v1'}));return
 rows=subprocess.check_output(['nvidia-smi','--query-gpu=index,memory.free','--format=csv,noheader,nounits'],text=True).splitlines()
 candidates=[int(row.split(',')[0]) for row in rows if int(row.split(',')[1])>=30000]
 if args.gpu!='auto':candidates=[gpu for gpu in candidates if gpu==int(args.gpu)]
 if not candidates:
  print(json.dumps({'status':'blocked','reason':'9B requires an available GPU; other project processes were preserved'}));return
 model=Path('/opt/models/Qwen3.5_9B')
 if not model.exists():model=Path('/opt/models/Qwen3.5-9B')
 if not model.exists():raise FileNotFoundError('installed 9B weights missing')
 command=[str(ROOT/'.venv-model/bin/python'),'scripts/model_server.py','--model',str(model),
          '--name','xf-qwen3.5-9b','--port','8000']
 gpu=candidates[0];log=ROOT/'runtime/logs/practice_9b.log'
 with log.open('ab') as output:
  process=subprocess.Popen(command,cwd=ROOT,stdout=output,stderr=subprocess.STDOUT,
      start_new_session=True,env={**os.environ,'CUDA_VISIBLE_DEVICES':str(gpu)})
 record={'status':'starting','pid':process.pid,'gpu':gpu,'model':'xf-qwen3.5-9b',
         'command':command,'started':time.time(),'log':str(log)}
 (ROOT/'runtime/services/practice9b.json').write_text(json.dumps(record,indent=2))
 print(json.dumps(record))

if __name__=='__main__':main()
