"""Run with the existing sentence-transformers environment, on CPU by default."""
import argparse,json,threading,os
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
import numpy as np

def main():
    p=argparse.ArgumentParser();p.add_argument('--model',default='/opt/models/bge-m3');p.add_argument('--port',type=int,default=8001);p.add_argument('--device',default='cpu');a=p.parse_args()
    os.environ.setdefault('OMP_NUM_THREADS','4')
    from sentence_transformers import SentenceTransformer
    import torch
    torch.set_num_threads(4)
    model=SentenceTransformer(a.model,device=a.device,local_files_only=True)
    model.max_seq_length=512
    lock=threading.Lock()
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200);self.end_headers();self.wfile.write(json.dumps({'model':a.model,'device':a.device}).encode())
        def do_POST(self):
            try:
                length=int(self.headers.get('Content-Length',0))
                if length>2_000_000:raise ValueError('request too large')
                texts=json.loads(self.rfile.read(length))['texts']
                if not isinstance(texts,list) or not 1<=len(texts)<=64:raise ValueError('invalid batch')
                with lock:vec=model.encode(texts,batch_size=8,normalize_embeddings=True,show_progress_bar=False)
                payload=json.dumps({'vectors':np.asarray(vec).tolist()}).encode()
                self.send_response(200);self.send_header('Content-Type','application/json');self.end_headers();self.wfile.write(payload)
            except Exception as e:
                self.send_response(400);self.end_headers();self.wfile.write(str(e).encode())
    ThreadingHTTPServer(('127.0.0.1',a.port),Handler).serve_forever()
if __name__=='__main__':main()
