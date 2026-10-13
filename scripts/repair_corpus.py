"""Drop rejected binary/html conversions and fetch a verified standard attachment."""
import sys,json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'src'))
from xfagent.config import read_json,write_json
from xfagent.ingest import convert,sha256
import requests
manifest=read_json(ROOT/'data/legal/manifest.json',[])
manifest=[d for d in manifest if not d['url'].split('?')[0].endswith('.doc')]
# Official Jiangsu Fire and Rescue published GB55037 full PDF; upstream seed was already fetched with robots checks.
url='https://js.119.gov.cn/group1/M00/01/D6/rBPe7Wi5YSWATAAkABU9IFBisPA109.pdf?attname=%E3%80%8A%E5%BB%BA%E7%AD%91%E9%98%B2%E7%81%AB%E9%80%9A%E7%94%A8%E8%A7%84%E8%8C%83%E3%80%8B%EF%BC%88GB55037-2022%EF%BC%89.pdf'
r=requests.get(url,timeout=60);r.raise_for_status();raw=r.content;digest=sha256(raw);identifier=sha256(url.encode())[:16]
path=ROOT/f'data/legal/raw/{identifier}-{digest[:12]}.pdf';path.write_bytes(raw);text=convert(path)
if '55037' not in text or len(text)<5000:raise ValueError('standard verification failed')
md=ROOT/f'data/legal/markdown/{identifier}.md';md.write_text(text)
item={'id':identifier,'url':url,'title':'建筑防火通用规范 GB 55037-2022','kind':'standard','status':'source_verified','effective_from':'2023-06-01','sha256':digest,'raw_path':str(path.relative_to(ROOT)),'markdown_path':str(md.relative_to(ROOT)),'characters':len(text),'verified_by':'official_publication_and_standard_number','verification_source':'https://zjj.sm.gov.cn/ztzl/xfzt/202401/t20240111_1993450.htm'}
manifest=[d for d in manifest if d['id']!=identifier]+[item];write_json(ROOT/'data/legal/manifest.json',manifest);print({'documents':len(manifest),'standard_characters':len(text)})
