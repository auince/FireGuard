"""CPU-only PDF transcription retaining coordinates; OCR is not automatic law publication."""
import os
os.environ['CUDA_VISIBLE_DEVICES']=''
import argparse,hashlib,json,subprocess
from pathlib import Path
from rapidocr_onnxruntime import RapidOCR
p=argparse.ArgumentParser();p.add_argument('pdf',type=Path);p.add_argument('--pages',type=int,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args();a.output.mkdir(parents=True,exist_ok=True)
engine=RapidOCR(intra_op_num_threads=4,inter_op_num_threads=2);source_hash=hashlib.sha256(a.pdf.read_bytes()).hexdigest();pages=[]
for n in range(1,a.pages+1):
 f=a.output/f'page-{n:02d}.json';img=a.output/f'page-{n:02d}.png'
 if f.exists():
  record=json.loads(f.read_text());assert record['source_hash']==source_hash
 else:
  subprocess.run(['pdftoppm','-f',str(n),'-l',str(n),'-scale-to','2200','-png','-singlefile',str(a.pdf),str(img.with_suffix(''))],check=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
  lines,elapsed=engine(str(img));record={'page':n,'source_hash':source_hash,'engine':'RapidOCR/ONNX CPU','lines':lines,'elapsed':elapsed};f.write_text(json.dumps(record,ensure_ascii=False,indent=2))
 pages.append(record);print(json.dumps({'page':n,'lines':len(record['lines'] or [])}),flush=True)
(a.output/'transcription.md').write_text('\n\n'.join('## PDF page '+str(r['page'])+'\n\n'+'\n'.join(line[1] for line in r['lines'] or []) for r in pages))
(a.output/'manifest.json').write_text(json.dumps({'source_hash':source_hash,'pages':len(pages),'engine':'RapidOCR/ONNX CPU','publication_status':'transcription_only_not_authoritative_index','note':'Retain normative text and commentary separately before any future ingestion; full OCR is not a correctness certificate'},ensure_ascii=False,indent=2))
