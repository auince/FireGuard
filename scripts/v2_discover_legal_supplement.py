import httpx,json,concurrent.futures
from bs4 import BeautifulSoup
from urllib.parse import urljoin
from pathlib import Path
urls=[
'https://zjj.sm.gov.cn/ztzl/xfzt/202401/t20240111_1993451.htm',
'https://wglj.gz.gov.cn/ztmb/pagzjs/content/post_8986976.html',
'https://zjj.sm.gov.cn/xxgk/fgwj/jsbz/202209/t20220909_1827380.htm',
'https://ha.119.gov.cn/2025/04-16/3491625.html',
'https://www.scspc.gov.cn/',
'https://sc.119.gov.cn/scxfjyzd/zcwj/common_list.shtml',
'https://www.thepaper.cn/newsDetail_forward_28581170']
p=Path('runtime/v2/legal-candidates');p.mkdir(exist_ok=True,parents=True)
def fetch(u):
 try:
  r=httpx.get(u,timeout=20,follow_redirects=True);s=BeautifulSoup(r.content,'html.parser')
  result={'url':u,'status':r.status_code,'length':len(r.content),'links':[(a.get_text(' ',strip=True),urljoin(str(r.url),a['href'])) for a in s.select('a[href]') if any(k in (a.get_text()+a['href']) for k in ['.pdf','消防条例','公报','cwgb'])]}
  if r.status_code==200:(p/(str(urls.index(u))+'.html')).write_bytes(r.content)
  return result
 except Exception as e:return {'url':u,'error':type(e).__name__}
res=list(concurrent.futures.ThreadPoolExecutor(5).map(fetch,urls));(p/'discovery.json').write_text(json.dumps(res,ensure_ascii=False,indent=2));print(json.dumps(res,ensure_ascii=False,indent=2))
