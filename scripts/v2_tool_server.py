"""Host-side adapter to existing XFDemo YOLO and CLIP tools, no LLM calls."""
import sys,os,json
from http.server import ThreadingHTTPServer,BaseHTTPRequestHandler
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'src'))
from xfagent.vision import configure_vendor
configure_vendor()
os.environ['YOLO_TIMEOUT']='28'
from backend.infrastructure.vision import yolo_detector
# Keep the virtualenv launcher path: resolving its symlink loses the environment.
yolo_detector.YOLO_PYTHON=ROOT/'.venv-model/bin/python'
run_yolo_detection=yolo_detector.run_yolo_detection
from xfagent.cases import search_cases

class Handler(BaseHTTPRequestHandler):
    def send(self,code,obj):
        data=json.dumps(obj,ensure_ascii=False).encode();self.send_response(code);self.send_header('Content-Type','application/json');self.end_headers();self.wfile.write(data)
    def do_GET(self):self.send(200,{'ready':True,'tools':['yolo','clip_cases']})
    def do_POST(self):
        try:
            length=int(self.headers.get('Content-Length','0'))
            if length>22000000:raise ValueError('image too large')
            obj=json.loads(self.rfile.read(length))
            if self.path=='/detect':
                facility=obj['facility']
                task={'indoor_hydrant':'internal_components','outdoor_hydrant':'outdoor_hydrant','fire_extinguisher':'fire_extinguisher'}[facility]
                self.send(200,run_yolo_detection(obj['image'],task=task))
            elif self.path=='/cases':
                self.send(200,search_cases(obj['query'],obj.get('kind','text'),'rrf'))
            else:self.send(404,{'error':'unknown tool'})
        except Exception as exc:self.send(400,{'error':str(exc)[:300]})

if __name__=='__main__':ThreadingHTTPServer(('127.0.0.1',8007),Handler).serve_forever()
