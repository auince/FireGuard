"""Single-worker local OpenAI-compatible multimodal inference, no remote downloads."""
import os,json,base64,io,time,threading,argparse
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from PIL import Image

def main():
    p=argparse.ArgumentParser();p.add_argument('--model',default='/opt/models/Qwen3.5_9B');p.add_argument('--adapter');p.add_argument('--port',type=int,default=8000);p.add_argument('--name',default='xf-qwen3.5-9b');a=p.parse_args()
    import torch
    from transformers import AutoProcessor,AutoModelForImageTextToText
    torch.set_num_threads(4)
    processor=AutoProcessor.from_pretrained(a.model,local_files_only=True,min_pixels=256*28*28,max_pixels=768*28*28)
    if not torch.cuda.is_available():raise RuntimeError('A free CUDA device is required for the interactive model service')
    model=AutoModelForImageTextToText.from_pretrained(a.model,local_files_only=True,dtype=torch.bfloat16,device_map={'':0},attn_implementation='sdpa')
    if a.adapter:
        from peft import PeftModel
        model=PeftModel.from_pretrained(model,a.adapter,is_trainable=False)
    model.eval();lock=threading.Lock()
    class Handler(BaseHTTPRequestHandler):
        def send(self,status,obj):
            raw=json.dumps(obj,ensure_ascii=False).encode();self.send_response(status);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(raw)));self.end_headers();self.wfile.write(raw)
        def do_GET(self):
            if self.path in ['/v1/models','/health']:self.send(200,{'object':'list','data':[{'id':a.name,'object':'model'}],'base':a.model,'adapter':a.adapter})
            else:self.send(404,{'error':'not found'})
        def do_POST(self):
            if self.path!='/v1/chat/completions':return self.send(404,{'error':'not found'})
            try:
                size=int(self.headers.get('Content-Length','0'))
                if size>22_000_000:raise ValueError('request too large')
                obj=json.loads(self.rfile.read(size));messages=[]
                if obj.get('stream'):raise ValueError('streaming is not enabled')
                for m in obj['messages']:
                    content=m['content'];parts=[{'type':'text','text':content}] if isinstance(content,str) else content
                    converted=[]
                    for part in parts:
                        if part.get('type')=='text':converted.append(part)
                        elif part.get('type')=='image_url':
                            url=part['image_url']['url']
                            if not url.startswith('data:image/'):raise ValueError('only inline images supported')
                            im=Image.open(io.BytesIO(base64.b64decode(url.split(',',1)[1],validate=True))).convert('RGB');im.thumbnail((1344,1344))
                            converted.append({'type':'image','image':im})
                    messages.append({'role':m['role'],'content':converted})
                with lock,torch.inference_mode():
                    inputs=processor.apply_chat_template(messages,tokenize=True,add_generation_prompt=True,return_dict=True,return_tensors='pt',enable_thinking=False).to(model.device)
                    if inputs['input_ids'].shape[1]>14000:raise ValueError('input exceeds 14000 tokens')
                    out=model.generate(**inputs,max_new_tokens=min(int(obj.get('max_tokens',1024)),1800),do_sample=False)
                    text=processor.batch_decode(out[:,inputs['input_ids'].shape[1]:],skip_special_tokens=True)[0]
                self.send(200,{'id':str(time.time_ns()),'object':'chat.completion','created':int(time.time()),'model':a.name,'choices':[{'index':0,'message':{'role':'assistant','content':text},'finish_reason':'stop'}],'usage':{'prompt_tokens':inputs['input_ids'].shape[1],'completion_tokens':out.shape[1]-inputs['input_ids'].shape[1],'total_tokens':out.shape[1]}})
            except Exception as e:
                print(type(e).__name__,str(e)[:500],flush=True)
                self.send(400,{'error':{'message':str(e),'type':type(e).__name__}})
            finally:
                if torch.cuda.is_available():torch.cuda.empty_cache()
    print('ready',a.name,flush=True);ThreadingHTTPServer(('127.0.0.1',a.port),Handler).serve_forever()
if __name__=='__main__':main()
