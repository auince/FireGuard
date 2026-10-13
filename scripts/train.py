"""Qwen3.5-9B all-linear LoRA SFT → GRPO with rule-verifiable rewards."""
import argparse,json,sys,hashlib,os
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'src'))
from xfagent.data import rows,text_of
from xfagent.rewards import parse_answer,REWARD_FUNCTIONS,REWARD_WEIGHTS

def main():
    p=argparse.ArgumentParser();p.add_argument('stage',choices=['sft','grpo']);p.add_argument('--config',default=str(ROOT/'configs/training.json'));p.add_argument('--data');p.add_argument('--output');p.add_argument('--sft-adapter');p.add_argument('--max-steps',type=int);p.add_argument('--limit',type=int,default=0);p.add_argument('--smoke',action='store_true');a=p.parse_args()
    cfg=json.loads(Path(a.config).read_text());source=Path(a.data or ROOT/'data/training/train.jsonl');output=Path(a.output or ROOT/'runtime/models'/a.stage)
    if (output/'adapter_config.json').exists():raise ValueError('Output already contains a model; choose a fresh run directory')
    if a.stage=='grpo' and not a.sft_adapter:raise ValueError('GRPO requires --sft-adapter from the completed SFT stage')
    import torch
    from transformers import AutoProcessor,AutoModelForImageTextToText,Trainer,TrainingArguments
    from peft import LoraConfig,get_peft_model,PeftModel
    from datasets import Dataset,Image as DatasetImage
    from PIL import Image
    torch.set_num_threads(4)
    processor=AutoProcessor.from_pretrained(cfg['base_model'],local_files_only=True,min_pixels=128*28*28,max_pixels=256*28*28 if a.smoke else cfg.get("max_pixels",768*28*28))
    model=AutoModelForImageTextToText.from_pretrained(cfg['base_model'],local_files_only=True,dtype=torch.bfloat16,attn_implementation='sdpa')
    model.config.use_cache=False
    if a.sft_adapter:model=PeftModel.from_pretrained(model,a.sft_adapter,is_trainable=True)
    else:model=get_peft_model(model,LoraConfig(r=cfg['lora_r'],lora_alpha=cfg['lora_alpha'],target_modules='all-linear',lora_dropout=.05,bias='none',task_type='CAUSAL_LM'))
    records=list(rows(source));records=records[:a.limit] if a.limit else records
    if not records:raise ValueError('empty training split')
    common=dict(output_dir=str(output),max_steps=a.max_steps or cfg[a.stage]['max_steps'],learning_rate=cfg[a.stage]['learning_rate'],per_device_train_batch_size=1,gradient_accumulation_steps=1 if a.smoke else cfg['gradient_accumulation_steps'],bf16=True,logging_steps=1,report_to='none',remove_unused_columns=False,seed=cfg['seed'],save_strategy='no',dataloader_num_workers=0)
    if a.stage=='sft':
        # Prompt and image tokens are masked; image tokens are never truncated.
        def collate(batch):
            if len(batch)!=1:raise ValueError('collator expects document batch size 1')
            row=batch[0]
            with Image.open(row['images'][0]) as im:image=im.convert('RGB')
            prompt=[{'role':'user','content':[{'type':'image','image':image},{'type':'text','text':text_of(row,'user')}]}]
            full=prompt+[{'role':'assistant','content':[{'type':'text','text':text_of(row,'assistant')}]}]
            inputs=processor.apply_chat_template(full,tokenize=True,return_dict=True,return_tensors='pt',enable_thinking=False)
            prefix=processor.apply_chat_template(prompt,tokenize=True,return_dict=True,return_tensors='pt',enable_thinking=False,add_generation_prompt=True)
            n=prefix['input_ids'].shape[1];labels=inputs['input_ids'].clone();labels[:,:n]=-100;labels[inputs['attention_mask']==0]=-100
            if (labels!=-100).sum()==0:raise ValueError('No assistant tokens in sample')
            inputs['labels']=labels;return inputs
        trainer=Trainer(model=model,args=TrainingArguments(**common,gradient_checkpointing=True,gradient_checkpointing_kwargs={'use_reentrant':False}),train_dataset=records,data_collator=collate)
    else:
        from trl import GRPOTrainer,GRPOConfig
        data=[]
        for row in records:
            parsed=parse_answer(text_of(row,'assistant'))
            data.append({'prompt':[{'role':'user','content':text_of(row,'user')}],'image':row['images'][0],'gold_labels':sorted(parsed['labels']),'gold_verdict':parsed['verdict'],'gold_scope':parsed['scope']})
        dataset=Dataset.from_list(data).cast_column('image',DatasetImage())
        common['gradient_accumulation_steps']=max(2,common['gradient_accumulation_steps'])
        model.config.use_cache=True
        grpo=GRPOConfig(**common,num_generations=2 if a.smoke else cfg['grpo'].get('num_generations',4),generation_batch_size=2 if a.smoke else cfg['grpo'].get('generation_batch_size'),max_completion_length=cfg['grpo'].get('max_completion_length',512),beta=.04,temperature=.8,use_vllm=False,reward_weights=REWARD_WEIGHTS,gradient_checkpointing=cfg['grpo'].get('gradient_checkpointing',False),gradient_checkpointing_kwargs={'use_reentrant':False},loss_type='grpo',chat_template_kwargs={'enable_thinking':False},mask_truncated_completions=False)
        trainer=GRPOTrainer(model=model,args=grpo,reward_funcs=REWARD_FUNCTIONS,train_dataset=dataset,processing_class=processor)
    output.mkdir(parents=True,exist_ok=True)
    manifest={'stage':a.stage,'config':cfg,'source':str(source),'source_sha256':hashlib.sha256(source.read_bytes()).hexdigest(),'sft_adapter':a.sft_adapter,'samples':len(records),'smoke':a.smoke,'max_steps':common['max_steps'],'status':'running'}
    (output/'run.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2))
    result=trainer.train();trainer.save_model(str(output));processor.save_pretrained(str(output))
    manifest.update(status='complete',metrics=result.metrics);(output/'run.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2))
if __name__=='__main__':main()
