import json,re,hashlib,shutil,datetime
from pathlib import Path
from xfagent.v2.store import Store
from xfagent.v2.facts import prepare_snapshot
root=Path.cwd();p=root/'runtime/v2/legal-candidates';manifest=root/'data/legal/manifest.json';rows=json.loads(manifest.read_text());backup=p/'manifest-before-astra.json'
if not backup.exists():shutil.copy2(manifest,backup)
def add(name,title,url,kind,start,region,text,method,**extra):
 raw=p/name;sha=hashlib.sha256(raw.read_bytes()).hexdigest();did=hashlib.sha256(url.encode()).hexdigest()[:16];dest=Path('data/legal/raw')/(did+'-'+sha[:12]+raw.suffix);shutil.copy2(raw,root/dest)
 md=Path('data/legal/markdown')/(did+'.md');(root/md).write_text(text)
 d=dict(id=did,title=title,url=url,resolved_url=url,kind=kind,effective_from=start,effective_until=None,jurisdiction=region,status='source_verified',sha256=sha,raw_path=str(dest),markdown_path=str(md),characters=len(text),fetched_at=datetime.datetime.now(datetime.timezone.utc).isoformat(),verification_method=method,**extra)
 rows[:]=[x for x in rows if x['id']!=did];rows.append(d);return d
sc=(p/'sc2024.md').read_text();sc=sc[sc.index('（ 1999'):sc.index('[责任编辑:')].strip()
sc='# 四川省消防条例（2024年修订）\n\n'+sc
articles=re.findall(r'(?m)^第[一二三四五六七八九十百]+条',sc);assert len(articles)==len(set(articles))==76
assert '2024年11月1日' in sc
new=[]
new.append(add('sc2024.html','四川省消防条例（2024年修订）','https://sc.119.gov.cn/scxfjyzd/zcwj/2024/9/3/dfeb6b6eacba472ca3f4f9a6c6c5e915.shtml','local_regulation','2024-11-01','四川',sc,'official_fire_authority_fulltext_76_unique_articles',supersedes_title='四川省消防条例（2011修订）'))
# Reproduction is hosted on the official fire authority's linked attachment CDN.
# Preserve the PDF, extracted text, page map and commentary separately; index only normative articles.
s=(p/'gb-henan.txt').read_text();clean=[]
for n,t in enumerate(s.split('\f'),1):
 t='\n'.join(l.rstrip() for l in t.splitlines() if not any(k in l for k in ['消防资源网','消防规范网','消防大讲堂','消防经典汇编']))
 clean.append(f'<!-- page:{n} -->\n'+t)
full='\n'.join(clean); (p/'gb55036-full-with-commentary.md').write_text(full)
matches=list(re.finditer(r'(?m)^\s*(\d{1,2}\.\d+\.\d+)\s+(?!条|（)',full));units=[]
for i,m in enumerate(matches):
 if int(m.group(1).split('.')[0])>12:continue
 end=matches[i+1].start() if i+1<len(matches) else len(full)
 body=full[m.start():end].strip();body=body.split('【条文说明】')[0].strip()
 body=re.sub(r'<!-- page:\d+ -->','',body).strip()
 # Remove following chapter headings / running page furniture without rewriting clauses.
 pages=[int(x) for x in re.findall(r'<!-- page:(\d+) -->',full[:m.start()])]; page=pages[-1] if pages else 1
 units.append({'article':m.group(1),'text':body,'pdf_page_start':page})
assert len({x['article'] for x in units})==len(units)
assert all(x in {u['article'] for u in units} for x in ['1.0.1','3.0.5','10.0.8','12.0.16'])
for u in units:
 if u['article']=='10.0.8':
  u['text']+='\n\n表10.0.8 灭火器的最大报废期限\n灭火器形式 | 灭火器类型 | 报废期限（年）\n手提式、推车式 | 水基型灭火器 | 6\n手提式、推车式 | 干粉灭火器 | 10\n手提式、推车式 | 洁净气体灭火器 | 10\n手提式、推车式 | 二氧化碳灭火器 | 12'
  u['table_provenance']={'digital_pdf_page':43,'official_scan_page':25,'verification':'visual_crosscheck_by_assistant_not_expert'}
body='# 消防设施通用规范 GB55036-2022（正文）\n\n'+'\n\n'.join(x['text'] for x in units)
(p/'gb55036-article-pages.json').write_text(json.dumps(units,ensure_ascii=False,indent=2))
new.append(add('gb-henan.pdf','消防设施通用规范 GB55036-2022','https://oss.dahe.cn/bdtypt/sbgt-wztipt/typtfile/20250416/0b4e7424190d4e17acb87a1a74e93f63.pdf','standard','2023-03-01','全国',body,'official_fire_authority_linked_pdf_text_layer_normative_articles_excluding_commentary',discovered_from='https://ha.119.gov.cn/2025/04-16/3491625.html',source_form='official_hosted_reproduction',article_page_map='runtime/v2/legal-candidates/gb55036-article-pages.json',ocr_crosscheck='runtime/v2/legal-candidates/ocr',professional_review='pending'))
manifest.write_text(json.dumps(rows,ensure_ascii=False,indent=2)+'\n');s=Store();sid=prepare_snapshot(s)
r={'snapshot_id':sid,'state':'prepared_not_published','new_documents':[{k:d[k] for k in ['id','title','url','characters','sha256']} for d in new],'gb_article_count':len(units),'sichuan_article_count':76,'old_snapshot':s.db.settings.find_one({'_id':'active_snapshot'})['value']}
(p/'prepared.json').write_text(json.dumps(r,ensure_ascii=False,indent=2)); print(json.dumps(r,ensure_ascii=False,indent=2))
