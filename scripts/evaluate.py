"""Frozen-set evaluation: persist every answer, model identity and dataset hash."""
import sys,json,argparse,base64,hashlib,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'src'))
from xfagent.data import rows,text_of
from xfagent.models import complete,health
from xfagent.rewards import parse_answer,ALL_LABELS

def metrics(pairs):
    tp=fp=fn=correct=positive=detected=invalid=0;per={l:[0,0,0] for l in ALL_LABELS};scope=0
    for gold,pred in pairs:
        g=parse_answer(gold);p=parse_answer(pred);a=g['labels'];b=p['labels']
        tp+=len(a&b);fp+=len(b-a);fn+=len(a-b);correct+=g['verdict']==p['verdict'];scope+=g['scope']==p['scope']
        positive+=g['verdict']=='不合规';detected+=g['verdict']=='不合规' and p['verdict']=='不合规';invalid+=p['verdict']=='unknown'
        for l in per:
            per[l][0]+=l in a&b;per[l][1]+=l in b-a;per[l][2]+=l in a-b
    n=len(pairs)
    def div(a,b):return a/b if b else None
    return {'n':n,'verdict_accuracy':div(correct,n),'abnormal_recall':div(detected,positive),'label_micro_precision':div(tp,tp+fp),'label_micro_recall':div(tp,tp+fn),'label_micro_f1':div(2*tp,2*tp+fp+fn),'scope_accuracy':div(scope,n),'invalid_answers':invalid,'per_label':{l:{'tp':v[0],'fp':v[1],'fn':v[2],'f1':div(2*v[0],2*v[0]+v[1]+v[2])} for l,v in per.items()}}

def main():
    p=argparse.ArgumentParser();p.add_argument('data');p.add_argument('--output',required=True);p.add_argument('--limit',type=int,default=0);p.add_argument('--prompt',choices=['long','short'],default='long');a=p.parse_args()
    data=list(rows(a.data));data=data[:a.limit] if a.limit else data;out=Path(a.output);out.mkdir(parents=True,exist_ok=True)
    if (out/'predictions.jsonl').exists():raise ValueError('Use a fresh output folder')
    short=(ROOT/'configs/prompt-short.txt').read_text();pairs=[];started=time.time()
    with (out/'predictions.jsonl').open('w') as f:
        for row in data:
            raw=Path(row['images'][0]).read_bytes();image='data:image/jpeg;base64,'+base64.b64encode(raw).decode()
            pred=complete(short if a.prompt=='short' else text_of(row,'user'),image=image);gold=text_of(row,'assistant');pairs.append((gold,pred))
            f.write(json.dumps({'id':row.get('id'),'gold':gold,'prediction':pred},ensure_ascii=False)+'\n');f.flush()
    report={'model':health(),'dataset':a.data,'dataset_sha256':hashlib.sha256(Path(a.data).read_bytes()).hexdigest(),'prompt':a.prompt,'limited_smoke':bool(a.limit),'seconds':time.time()-started,'metrics':metrics(pairs)}
    (out/'metrics.json').write_text(json.dumps(report,ensure_ascii=False,indent=2));print(json.dumps(report,ensure_ascii=False))
if __name__=='__main__':main()
