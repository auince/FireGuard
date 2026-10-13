"""Masked local defect generation. Outside-mask pixels are restored exactly."""
import argparse,json,hashlib
from pathlib import Path
from PIL import Image

def main():
    p=argparse.ArgumentParser();p.add_argument('--image',required=True);p.add_argument('--mask',required=True);p.add_argument('--prompt',required=True);p.add_argument('--output',required=True);p.add_argument('--seed',type=int,default=42);p.add_argument('--model',default='/opt/models/stable-diffusion-xl-base-1.0');p.add_argument('--device',default='cuda');a=p.parse_args()
    import torch
    from diffusers import AutoPipelineForInpainting
    image=Image.open(a.image).convert('RGB');mask=Image.open(a.mask).convert('L')
    if image.size!=mask.size:raise ValueError('mask dimensions must equal image dimensions')
    if mask.getextrema()==(0,0):raise ValueError('empty mask')
    pipe=AutoPipelineForInpainting.from_pretrained(a.model,torch_dtype=torch.float16,local_files_only=True).to(a.device)
    generated=pipe(prompt=a.prompt,image=image,mask_image=mask,num_inference_steps=30,generator=torch.Generator(a.device).manual_seed(a.seed)).images[0].resize(image.size)
    result=Image.composite(generated,image,mask)
    target=Path(a.output);target.parent.mkdir(parents=True,exist_ok=True);result.save(target)
    target.with_suffix('.provenance.json').write_text(json.dumps({'source_image':a.image,'source_sha256':hashlib.sha256(Path(a.image).read_bytes()).hexdigest(),'mask':a.mask,'prompt':a.prompt,'model':a.model,'seed':a.seed,'synthetic':True,'review_status':'pending_human_review'},ensure_ascii=False,indent=2))
if __name__=='__main__':main()
