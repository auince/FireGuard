"""Multimodal image/text dual index in one shared CLIP embedding space."""
import numpy as np
import requests
from .config import ROOT,read_json,write_json
from .retrieval import rrf

def encode_cases(items,kind):
    import os
    url=os.getenv('XF_MULTIMODAL_URL','http://127.0.0.1:8002/embed')
    r=requests.post(url,json={'kind':kind,'items':items},timeout=(5,300));r.raise_for_status()
    a=np.asarray(r.json()['vectors'],dtype=np.float32)
    return a/np.maximum(np.linalg.norm(a,axis=1,keepdims=True),1e-12)

def build_cases(source,limit=200):
    from .data import rows,text_of
    selected=[];seen=set()
    for r in rows(source):
        image=r['images'][0]
        if image in seen:continue
        seen.add(image)
        selected.append({'id':r.get('id',str(len(selected))),'image':image,'description':text_of(r,'assistant'),
                         'description_source':r.get('description_model','existing_domain_annotation'),'human_reviewed':r.get('human_reviewed',True),'split':'training'})
        if len(selected)>=limit:break
    out=ROOT/'data/cases';out.mkdir(parents=True,exist_ok=True)
    for field,kind in [('image','image_path'),('description','text')]:
        batches=[encode_cases([x[field] for x in selected[i:i+16]],kind) for i in range(0,len(selected),16)]
        np.save(out/f'{field}.npy',np.concatenate(batches))
    write_json(out/'records.json',selected)
    return {'indexed':len(selected),'encoder':'CLIP','source':str(source)}

def search_cases(query,kind='text',mode='rrf',k=5,alpha=.5):
    if mode not in ['rrf','weighted','image_only']:raise ValueError('invalid fusion mode')
    if not 0<=alpha<=1:raise ValueError('alpha must be 0..1')
    records=read_json(ROOT/'data/cases/records.json',[])
    if not records:raise ValueError('案例索引尚未建立')
    q=encode_cases([query],kind)[0]
    image=np.load(ROOT/'data/cases/image.npy')@q
    text=np.load(ROOT/'data/cases/description.npy')@q
    ir=np.argsort(-image).tolist();tr=np.argsort(-text).tolist()
    if mode=='rrf':ranking,scores=rrf([ir,tr])
    else:
        score=image if mode=='image_only' else alpha*image+(1-alpha)*text
        ranking=np.argsort(-score).tolist();scores={i:float(score[i]) for i in ranking}
    return [{**records[i],'score':float(scores[i]),'image_score':float(image[i]),'text_score':float(text[i])} for i in ranking[:k]]
