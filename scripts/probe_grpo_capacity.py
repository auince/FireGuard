"""Real single-GPU LoRA GRPO capacity probe; isolated output and measured updates."""
import argparse,json,time,hashlib,traceback,platform,importlib.metadata,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"src"))

def write(path,obj):path.write_text(json.dumps(obj,ensure_ascii=False,indent=2)+'\n')
def main():
 p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True);p.add_argument('--data',type=Path,required=True)
 p.add_argument('--adapter',type=Path,default=ROOT/'runtime/models/sft-smoke');p.add_argument('--generations',type=int,default=4)
 p.add_argument('--accumulation',type=int,default=4);p.add_argument('--image-tokens-cap',type=int,default=768)
 p.add_argument('--completion',type=int,default=512);p.add_argument('--steps',type=int,default=2);p.add_argument('--checkpointing',action='store_true');a=p.parse_args()
 if a.output.exists():raise ValueError('Choose a fresh output directory')
 a.output.mkdir(parents=True);started=time.time()
 report={'status':'starting','config':{'base_model':'/opt/models/Qwen3.5_9B','sft_adapter':str(a.adapter),
  'dtype':'bfloat16','quantization':None,'lora_r':8,'lora_alpha':32,'target_modules':'all-linear',
  'per_device_train_batch_size':1,'gradient_accumulation_steps':a.accumulation,'num_generations':a.generations,
  'generation_batch_size':a.accumulation,'max_completion_length':a.completion,'max_pixels':a.image_tokens_cap*28*28,
  'gradient_checkpointing':a.checkpointing,'use_vllm':False,'beta':.04,'reward_weights':[.2,.5,.3],'max_steps':a.steps,'learning_rate':5e-6},
  'source':str(a.data),'source_sha256':hashlib.sha256(a.data.read_bytes()).hexdigest(),
  'initial_adapter_sha256':hashlib.sha256((a.adapter/'adapter_model.safetensors').read_bytes()).hexdigest(),
  'caveat':'Capacity and update verification only. Initial adapter is a one-step SFT smoke artifact, not a converged domain model.'}
 write(a.output/'capacity.json',report)
 try:
  import torch
  from transformers import AutoProcessor,AutoModelForImageTextToText,TrainerCallback,set_seed
  from peft import PeftModel
  from datasets import Dataset,Image as DatasetImage
  from trl import GRPOTrainer,GRPOConfig
  from xfagent.data import rows,text_of
  from xfagent.rewards import parse_answer,REWARD_FUNCTIONS,REWARD_WEIGHTS
  from PIL import Image
  torch.set_num_threads(4);set_seed(20261003)
  if not torch.cuda.is_available():raise RuntimeError('CUDA unavailable')
  torch.cuda.reset_peak_memory_stats()
  report['device']={'name':torch.cuda.get_device_name(0),'total_bytes':torch.cuda.get_device_properties(0).total_memory}
  report['versions']={k:importlib.metadata.version(k) for k in ['torch','transformers','peft','trl','accelerate']}
  processor=AutoProcessor.from_pretrained(report['config']['base_model'],local_files_only=True,min_pixels=128*28*28,max_pixels=a.image_tokens_cap*28*28)
  model=AutoModelForImageTextToText.from_pretrained(report['config']['base_model'],local_files_only=True,dtype=torch.bfloat16,attn_implementation='sdpa')
  model=PeftModel.from_pretrained(model,str(a.adapter),is_trainable=True);model.config.use_cache=True
  before={n:p.detach().float().cpu().clone() for n,p in model.named_parameters() if p.requires_grad}
  report['parameters']={'total':sum(p.numel() for p in model.parameters()),'trainable':sum(p.numel() for p in model.parameters() if p.requires_grad)}
  data=[];input_sizes=[]
  for row in rows(a.data):
   parsed=parse_answer(text_of(row,'assistant'));prompt=text_of(row,'user')
   data.append({'prompt':[{'role':'user','content':prompt}],'image':row['images'][0],
    'gold_labels':sorted(parsed['labels']),'gold_verdict':parsed['verdict'],'gold_scope':parsed['scope']})
   with Image.open(row['images'][0]) as image:
    im=image.convert('RGB');original=list(im.size)
    tok=processor.apply_chat_template([{'role':'user','content':[{'type':'image','image':im},{'type':'text','text':prompt}]}],tokenize=True,return_dict=True,return_tensors='pt',add_generation_prompt=True,enable_thinking=False)
    input_sizes.append({'original_image_size':original,'prompt_tokens':int(tok['input_ids'].shape[-1]),'image_grid_thw':tok.get('image_grid_thw').tolist()})
  report['samples']=len(data);report['input_sizes']=input_sizes
  dataset=Dataset.from_list(data).cast_column('image',DatasetImage())
  events=[]
  class Monitor(TrainerCallback):
   def on_log(self,args,state,control,logs=None,**kwargs):
    if logs:
     item={'step':state.global_step,'elapsed_seconds':time.time()-started,**logs,
       'cuda_allocated_bytes':torch.cuda.memory_allocated(),'cuda_peak_allocated_bytes':torch.cuda.max_memory_allocated(),
       'cuda_reserved_bytes':torch.cuda.memory_reserved(),'cuda_peak_reserved_bytes':torch.cuda.max_memory_reserved()}
     events.append(item)
     with (a.output/'steps.jsonl').open('a') as f:f.write(json.dumps(item,ensure_ascii=False)+'\n')
  config=GRPOConfig(output_dir=str(a.output/'adapter'),max_steps=a.steps,learning_rate=5e-6,per_device_train_batch_size=1,
   gradient_accumulation_steps=a.accumulation,num_generations=a.generations,generation_batch_size=a.accumulation,
   bf16=True,logging_steps=1,report_to='none',remove_unused_columns=False,seed=20261003,save_strategy='no',dataloader_num_workers=0,
   max_completion_length=a.completion,beta=.04,temperature=.8,use_vllm=False,reward_weights=REWARD_WEIGHTS,
   gradient_checkpointing=a.checkpointing,gradient_checkpointing_kwargs={'use_reentrant':False},loss_type='grpo',
   chat_template_kwargs={'enable_thinking':False},mask_truncated_completions=False)
  trainer=GRPOTrainer(model=model,args=config,reward_funcs=REWARD_FUNCTIONS,train_dataset=dataset,processing_class=processor,callbacks=[Monitor()])
  report['status']='training';write(a.output/'capacity.json',report)
  result=trainer.train()
  changed=0;delta=0.;max_delta=0.;finite=True
  for n,p in model.named_parameters():
   if n not in before:continue
   current=p.detach().float().cpu();diff=current-before[n];changed+=int(not torch.equal(current,before[n]));finite=finite and bool(torch.isfinite(current).all());delta+=float(torch.sum(diff.double()**2));max_delta=max(max_delta,float(diff.abs().max()))
  report['update_verification']={'global_steps':trainer.state.global_step,'trainable_tensors':len(before),'changed_tensors':changed,'delta_l2':delta**.5,'max_abs_delta':max_delta,'all_finite':finite}
  if trainer.state.global_step!=a.steps or not changed or not finite:raise RuntimeError('Training did not produce the required finite weight updates')
  trainer.save_model(str(a.output/'adapter'));processor.save_pretrained(str(a.output/'adapter'))
  report.update(status='complete',metrics=result.metrics,step_logs=events)
 except Exception as e:
  report.update(status='failed',error_type=type(e).__name__,error=str(e),traceback=traceback.format_exc())
  traceback.print_exc()
 finally:
  report['wall_seconds']=time.time()-started
  try:
   import torch
   if torch.cuda.is_available():report['memory']={'peak_allocated_bytes':torch.cuda.max_memory_allocated(),'peak_reserved_bytes':torch.cuda.max_memory_reserved()}
  except Exception:pass
  write(a.output/'capacity.json',report);print(json.dumps({k:report.get(k) for k in ['status','metrics','update_verification','memory','wall_seconds','error']},ensure_ascii=False),flush=True)
 if report['status']!='complete':raise SystemExit(1)
if __name__=='__main__':main()
