"""Collect bounded official sources; inaccessible or scan-only texts remain unverified."""
import json,re,time
from urllib.parse import urljoin,urlparse
from urllib.robotparser import RobotFileParser
import requests
from bs4 import BeautifulSoup
from xfagent.config import ROOT,read_json,write_json
from xfagent.ingest import convert,sha256
from xfagent.v2.config import now

SOURCES=[
 {'title':'四川省物业管理条例（2022）','url':'https://abazhou.gov.cn/abazhou/c109474/202110/7f298133f605419692bb89d580799d1f.shtml','kind':'local_regulation','jurisdiction':'四川','effective_from':'2022-05-01','conditions':{'property_management':True}},
 {'title':'四川省消防条例（2011）','url':'https://luojiang.gov.cn/gk/cdgk/jczwgkbzml/lybl/aqsc/zcwj/bmhdfgz/1542254.htm','kind':'local_regulation','jurisdiction':'四川','effective_from':'2011-08-01','effective_until':'2024-11-01'},
 {'title':'四川省消防条例（2024）发布公告','url':'https://www.scspc.gov.cn/cwhgg/202407/23251.html','kind':'announcement','jurisdiction':'四川','effective_from':'2024-11-01'},
 {'title':'消防设施通用规范 GB55036-2022','url':'https://snamr.shaanxi.gov.cn/sy/ztzl/sbgxhxfpyjhx/bzcx/gjbz/202410/t20241015_3438898.html','kind':'standard','jurisdiction':'全国','effective_from':'2023-03-01','attachments':True},
 {'title':'消防设施通用规范 GB55036-2022','url':'https://wsjkw.nx.gov.cn/ztzl/aqscgz/zhgl/202510/t20251029_5068142.html','kind':'standard','jurisdiction':'全国','effective_from':'2023-03-01','attachments':True},
 {'title':'消防设施通用规范 GB55036-2022','url':'https://wlt.fujian.gov.cn/zwgk/zcfg/zxwj/202604/t20260424_7130967.htm','kind':'standard','jurisdiction':'全国','effective_from':'2023-03-01','attachments':True,'attachment_match':'55036'},
]
session=requests.Session();session.headers['User-Agent']='XFAgentResearch/2.0'
robots={};log=[];manifest=read_json(ROOT/'data/legal/manifest.json',[])
by_url={d['url']:d for d in manifest}
def official(u):return (urlparse(u).hostname or '').endswith('.gov.cn')
def fetch(u):
 if not official(u):raise ValueError('not an official government domain')
 host=urlparse(u).netloc
 if host not in robots:
  rr=session.get(urljoin(u,'/robots.txt'),timeout=12)
  if rr.status_code in [401,403]:raise ValueError('robots unavailable with access denial')
  rp=RobotFileParser();rp.parse(rr.text.splitlines() if rr.status_code==200 else []);robots[host]=rp if rr.status_code==200 else None
 if robots[host] and not robots[host].can_fetch('XFAgentResearch',u):raise ValueError('robots disallow')
 for _ in range(5):
  if not official(u):raise ValueError('redirect leaves official sources')
  r=session.get(u,timeout=(5,35),allow_redirects=False)
  if r.is_redirect:u=urljoin(u,r.headers['Location']);continue
  r.raise_for_status()
  if len(r.content)>35000000:raise ValueError('oversized source')
  return r
 raise ValueError('redirect limit')

for src in SOURCES:
 try:
  r=fetch(src['url']);original=src['url']
  if src.get('attachments'):
   r.encoding=r.apparent_encoding;soup=BeautifulSoup(r.text,'html.parser')
   links=[a for a in soup.find_all('a',href=True) if '.pdf' in a['href'].lower() and src.get('attachment_match','') in a.get_text()]
   if not links:
    links=[a for a in soup.find_all('iframe',src=True) if '.pdf' in a['src'].lower()]
   if not links:raise ValueError('no matching PDF attachment')
   target=urljoin(r.url,links[0].get('href') or links[0]['src']);r=fetch(target)
  raw=r.content;suffix='.pdf' if raw.startswith(b'%PDF') else '.html'
  if suffix=='.html':r.encoding=r.apparent_encoding;raw=r.text.encode('utf-8')
  h=sha256(raw);identifier=sha256(r.url.encode())[:16]
  p=ROOT/'data/legal/raw'/f'{identifier}-{h[:12]}{suffix}';p.write_bytes(raw)
  try:body=convert(p)
  except ValueError:
   by_url[r.url]={**src,'url':r.url,'discovered_from':original,'id':identifier,'sha256':h,'raw_path':str(p.relative_to(ROOT)),
    'status':'ocr_pending','fetched_at':now().isoformat(),'verification_method':'scanned_official_file_requires_ocr_and_human_review'}
   log.append({'url':r.url,'ok':True,'status':'ocr_pending'});continue
  han=len(re.findall(r'[\u4e00-\u9fff]',body))
  status='source_verified' if han>3500 and ('第一条' in body or '3.0.' in body or '3.0.1' in body.replace(' ','')) else 'unverified'
  if src['kind']=='announcement':status='source_verified' if '2024' in body and '消防条例' in body else 'unverified'
  if '2011' in src['title'] and '2024年7月29日' in body:raise ValueError('historical source contains newer version')
  md=ROOT/'data/legal/markdown'/f'{identifier}.md';md.write_text(body)
  by_url[r.url]={**src,'url':r.url,'discovered_from':original,'resolved_url':r.url,'id':identifier,'sha256':h,
    'raw_path':str(p.relative_to(ROOT)),'markdown_path':str(md.relative_to(ROOT)),'characters':len(body),
    'status':status,'fetched_at':now().isoformat(),'verification_method':'official_body_text_extraction' if status=='source_verified' else 'body_or_ocr_review_pending'}
  log.append({'url':r.url,'ok':True,'status':status,'characters':len(body),'han':han})
 except Exception as exc:log.append({'url':src['url'],'ok':False,'error':str(exc)[:250]})
 print(json.dumps(log[-1],ensure_ascii=False),flush=True);time.sleep(.6)
write_json(ROOT/'data/legal/manifest.json',list(by_url.values()))
write_json(ROOT/'reports/v2_legal_collection.json',log)
