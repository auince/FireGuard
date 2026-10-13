"""Three explicit source-article regression cases, NOT an independent retrieval benchmark."""
import json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'src'))
from xfagent.retrieval import SearchIndex,retrieval_metrics
idx=SearchIndex();queries=[]
for title,article,query in [('中华人民共和国消防法','第二十八条','禁止遮挡消火栓的规定'),('机关团体企业事业单位','第三十一条','消火栓被遮挡单位应责成有关人员当场改正'),('高层民用建筑','第二十八条','高层建筑禁止在消火栓箱内堆放杂物')]:
 ids=[c['id'] for c in idx.children if idx.docs[c['doc_id']]['title'].startswith(title) and c['article']==article]
 if not ids:raise ValueError('Expected authoritative clause not extracted: '+title+article)
 queries.append({'query':query,'gold_ids':ids})
out=ROOT/'runtime/validation';out.mkdir(exist_ok=True);(out/'retrieval-regression-gold.json').write_text(json.dumps(queries,ensure_ascii=False,indent=2))
result={'purpose':'handpicked engineering regression; not held-out effectiveness evidence','modes':{m:retrieval_metrics(queries,idx,m) for m in ['bm25','dense','hierarchical','weighted','hybrid']}}
(out/'retrieval-regression.json').write_text(json.dumps(result,ensure_ascii=False,indent=2));print({m:{k:v for k,v in metrics.items() if k!='results'} for m,metrics in result['modes'].items()})
