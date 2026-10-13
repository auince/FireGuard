"""Create one unreviewed local-rust augmentation to validate masked compositing."""
import json,subprocess,sys
from pathlib import Path
from PIL import Image,ImageDraw
ROOT=Path(__file__).resolve().parents[1];out=ROOT/'runtime/synthesis-smoke';out.mkdir(parents=True,exist_ok=True)
row=json.loads((ROOT/'data/training/validation.jsonl').read_text().splitlines()[0]);source=row['images'][0]
im=Image.open(source).convert('RGB');w,h=im.size;mask=Image.new('L',im.size,0);ImageDraw.Draw(mask).rectangle((int(w*.25),int(h*.55),int(w*.4),int(h*.7)),fill=255);mask.save(out/'mask.png')
subprocess.run([sys.executable,str(ROOT/'scripts/synthesize_defect.py'),'--image',source,'--mask',str(out/'mask.png'),'--prompt','A small localized patch of rusty corroded metal on the fire hydrant cabinet, realistic photograph, preserve geometry','--output',str(out/'synthetic.png')],check=True)
import numpy as np
original=np.array(im);result=np.array(Image.open(out/'synthetic.png'));outside=np.array(mask)==0
report={'outside_mask_exactly_preserved':bool(np.array_equal(original[outside],result[outside])),'source':source,'review_status':'pending_human_review','not_in_training':True};(out/'validation.json').write_text(json.dumps(report));print(report)
