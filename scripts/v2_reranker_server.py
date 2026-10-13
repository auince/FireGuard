"""Local BGE Gemma cross encoder, following the model card's Yes-token scoring."""
import json,threading,time,os
from http.server import ThreadingHTTPServer,BaseHTTPRequestHandler
import torch
from transformers import AutoTokenizer,AutoModelForCausalLM
PATH='/opt/models/bge-reranker-v2-gemma'
torch.set_num_threads(4)
tokenizer=AutoTokenizer.from_pretrained(PATH,local_files_only=True,padding_side='left')
model=AutoModelForCausalLM.from_pretrained(PATH,local_files_only=True,dtype=torch.bfloat16,device_map={'':0},attn_implementation='sdpa').eval()
yes=tokenizer('Yes',add_special_tokens=False)['input_ids'][0]
suffix=tokenizer("\nGiven a query A and a passage B, determine whether the passage contains an answer to the query by providing a prediction of either 'Yes' or 'No'.",add_special_tokens=False)['input_ids']
lock=threading.Lock()

def score(query,texts):
    values=[]
    with lock,torch.inference_mode():
        for start in range(0,len(texts),4):
            batch=[]
            for text in texts[start:start+4]:
                qa=tokenizer('A: '+query,add_special_tokens=False,truncation=True,max_length=256)['input_ids']
                body=tokenizer('\nB: '+text,add_special_tokens=False,truncation=True,max_length=768-len(qa))['input_ids']
                ids=[tokenizer.bos_token_id]+qa+body+suffix
                batch.append({'input_ids':ids,'attention_mask':[1]*len(ids)})
            encoded=tokenizer.pad(batch,padding=True,return_tensors='pt').to(model.device)
            out=model(**encoded,use_cache=False,logits_to_keep=1)
            values.extend(out.logits[:,-1,yes].float().cpu().tolist())
    return values

class Handler(BaseHTTPRequestHandler):
    def send(self,code,obj):
        raw=json.dumps(obj).encode();self.send_response(code);self.send_header('Content-Type','application/json');self.end_headers();self.wfile.write(raw)
    def do_GET(self):self.send(200,{'ready':True,'model':PATH,'score':'unnormalized_yes_logit'})
    def do_POST(self):
        try:
            size=int(self.headers.get('Content-Length','0'))
            if size>500000:raise ValueError('request too large')
            data=json.loads(self.rfile.read(size));texts=data['texts']
            if len(texts)>60:raise ValueError('at most 60 candidates')
            t=time.monotonic();values=score(data['query'],texts)
            self.send(200,{'scores':values,'seconds':time.monotonic()-t})
        except Exception as exc:self.send(500,{'error':str(exc)[:300]})

print('reranker ready',flush=True)
ThreadingHTTPServer(('127.0.0.1',8005),Handler).serve_forever()
