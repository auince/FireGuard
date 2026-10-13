import re,json,difflib
from pathlib import Path
p=Path('runtime/v2/legal-candidates');a=json.loads((p/'gb55036-article-pages.json').read_text());pages=[]
for f in sorted((p/'ocr').glob('page-*.json')):
 d=json.loads(f.read_text());pages.append((d['page'],'\n'.join(x[1] for x in d['lines'] or [])))
s='\n'.join(f'<!-- page:{n} -->\n{t}' for n,t in pages);(p/'gb55036-scan-ocr.md').write_text(s)
m=list(re.finditer(r'(?m)^(\d{1,2}\.\d+\.\d+)\s*',s));lookup={}
for i,x in enumerate(m):lookup[x.group(1)]=s[x.start():m[i+1].start() if i+1<len(m) else len(s)]
def norm(t):return re.sub(r'[^\w\u4e00-\u9fff]','',re.sub(r'<!-- page:\d+ -->','',t))
res=[]
for u in a:
 o=lookup.get(u['article'],'');score=difflib.SequenceMatcher(None,norm(u['text']),norm(o),autojunk=False).ratio();res.append({'article':u['article'],'similarity':score,'digital':u['text'],'ocr':o})
(p/'ocr-comparison.json').write_text(json.dumps(res,ensure_ascii=False,indent=2));print('article',len(a),'matched',sum(bool(x['ocr']) for x in res),'minimum',min(x['similarity'] for x in res));print([(x['article'],round(x['similarity'],3)) for x in res if x['similarity']<.95])
for x in res:
 if x['article'].startswith(('1.','2.','3.','10.')) and x['similarity']<.97:print(x['article'],'DIGITAL',x['digital'],'OCR',x['ocr'])
