"""Refresh only enriched title rows, preserving body vectors and raw citations."""
import sys,json,hashlib
from pathlib import Path
import numpy as np
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'src'))
from xfagent.config import read_json,write_json
from xfagent.retrieval import embed
index=ROOT/'data/index';corpus=read_json(index/'corpus.json');extra=read_json(ROOT/'data/legal/enrichment.json',{});docs={d['id']:d for d in corpus['documents']};vectors=np.load(index/'title.npy');changed=[]
for i,child in enumerate(corpus['children']):
 e=extra.get(child['doc_id'],{})
 if e.get('source_sha256')==docs[child['doc_id']]['sha256']:
  child['index_title']=child['title']+' '+' '.join(str(x) for x in e.get('suggested',{}).get('keywords',[])[:30]);changed.append(i)
for start in range(0,len(changed),24):
 ids=changed[start:start+24];vectors[ids]=embed([corpus['children'][i]['index_title'] for i in ids])
np.save(index/'title.next.npy',vectors);(index/'title.next.npy').replace(index/'title.npy');write_json(index/'corpus.json',corpus)
meta=read_json(index/'metadata.json');meta.update(enriched_title_rows=len(changed),corpus_sha256=hashlib.sha256((index/'corpus.json').read_bytes()).hexdigest());write_json(index/'metadata.json',meta);print({'updated_title_rows':len(changed)})
