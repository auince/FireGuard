import httpx,json,hashlib,concurrent.futures
from pathlib import Path
from pypdf import PdfReader
from xfagent.ingest import html_markdown
sources=[('gb-sm2024','https://zjj.sm.gov.cn/ztzl/xfzt/202401/P020240111382751447940.pdf'),('gb-sm2022','https://zjj.sm.gov.cn/xxgk/fgwj/jsbz/202209/P020220909629947039317.pdf'),('gb-henan','https://oss.dahe.cn/bdtypt/sbgt-wztipt/typtfile/20250416/0b4e7424190d4e17acb87a1a74e93f63.pdf'),('sc2024','https://sc.119.gov.cn/scxfjyzd/zcwj/2024/9/3/dfeb6b6eacba472ca3f4f9a6c6c5e915.shtml')]
p=Path('runtime/v2/legal-candidates');p.mkdir(exist_ok=True,parents=True)
def fetch(x):
 name,u=x
 try:
  r=httpx.get(u,timeout=40,follow_redirects=True);r.raise_for_status();ext='.pdf' if r.content.startswith(b'%PDF') else '.html';f=p/(name+ext);f.write_bytes(r.content)
  if ext=='.pdf':
   pages=[z.extract_text() or '' for z in PdfReader(f).pages];t='\n\n'.join(f'<!-- page:{i+1} -->\n{z}' for i,z in enumerate(pages));print(name,len(pages),[len(z) for z in pages[:10]],flush=True)
  else:t=html_markdown(r.content)
  (p/(name+'.md')).write_text(t);return {'name':name,'url':u,'resolved_url':str(r.url),'raw_path':str(f),'sha256':hashlib.sha256(r.content).hexdigest(),'chars':len(t),'snippet':t[:350]}
 except Exception as e:return {'name':name,'error':type(e).__name__+':'+str(e)[:100]}
a=list(concurrent.futures.ThreadPoolExecutor(4).map(fetch,sources));(p/'bodies.json').write_text(json.dumps(a,ensure_ascii=False,indent=2));print(json.dumps(a,ensure_ascii=False,indent=2))
