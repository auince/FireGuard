import os,json,time,subprocess
os.environ['CUDA_VISIBLE_DEVICES']=''
from pathlib import Path
from rapidocr_onnxruntime import RapidOCR
p=Path('runtime/v2/legal-candidates');o=p/'ocr';o.mkdir(exist_ok=True)
engine=RapidOCR(intra_op_num_threads=4,inter_op_num_threads=2)
for n in range(1,32):
 f=o/f'page-{n:02d}.json'
 if f.exists():continue
 img=o/f'page-{n:02d}.png'
 subprocess.run(['pdftoppm','-f',str(n),'-l',str(n),'-scale-to','2200','-png','-singlefile',str(p/'gb-sm2024.pdf'),str(img.with_suffix(''))],check=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
 r,elapsed=engine(str(img));f.write_text(json.dumps({'page':n,'engine':'RapidOCR/ONNX CPU','lines':r,'elapsed':elapsed},ensure_ascii=False,indent=2));print(n,len(r or []),flush=True)
