import argparse,base64,io,json,threading,os
from pathlib import Path
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from PIL import Image

def main():
    p=argparse.ArgumentParser();p.add_argument('--model',default='/opt/models/clip-vit-large-patch14');p.add_argument('--port',type=int,default=8002);a=p.parse_args()
    import torch
    from transformers import CLIPModel,CLIPProcessor
    torch.set_num_threads(3)
    model=CLIPModel.from_pretrained(a.model,local_files_only=True).eval()
    processor=CLIPProcessor.from_pretrained(a.model,local_files_only=True);lock=threading.Lock()
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200);self.end_headers();self.wfile.write(json.dumps({'model':a.model,'device':'cpu'}).encode())
        def do_POST(self):
            try:
                length=int(self.headers.get('Content-Length',0))
                if length>25_000_000:raise ValueError('request too large')
                data=json.loads(self.rfile.read(length));items=data['items'];kind=data['kind']
                if len(items)>32:raise ValueError('batch too large')
                with lock,torch.inference_mode():
                    if kind=='text':
                        inputs=processor(text=items,return_tensors='pt',padding=True,truncation=True,max_length=77)
                        vectors=model.get_text_features(**inputs)
                    else:
                        images=[]
                        for item in items:
                            if kind=='image_data':im=Image.open(io.BytesIO(base64.b64decode(item.split(',',1)[1])))
                            elif kind=='image_path':
                                path=Path(item).resolve()
                                if not any(path.is_relative_to(Path(root)) for root in ['/opt/datasets/fire-inspection','/opt/xfagent']):raise ValueError('image outside approved roots')
                                im=Image.open(path)
                            else:raise ValueError('invalid input kind')
                            images.append(im.convert('RGB'))
                        inputs=processor(images=images,return_tensors='pt');vectors=model.get_image_features(**inputs)
                    if not isinstance(vectors,torch.Tensor):vectors=vectors.pooler_output
                    vectors=torch.nn.functional.normalize(vectors,dim=-1)
                self.send_response(200);self.send_header('Content-Type','application/json');self.end_headers();self.wfile.write(json.dumps({'vectors':vectors.tolist(),'encoder_id':os.getenv('XF_MULTIMODAL_MODEL_ID','clip-vit-large-patch14')}).encode())
            except Exception as e:
                self.send_response(400);self.end_headers();self.wfile.write(str(e).encode())
    ThreadingHTTPServer(('127.0.0.1',a.port),Handler).serve_forever()
if __name__=='__main__':main()
