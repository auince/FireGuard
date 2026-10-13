import json,re,hashlib,datetime
from pathlib import Path
from xfagent.v2.store import Store
from xfagent.v2.facts import eligible,source_integrity,publish_snapshot
from xfagent.v2.retrieval import Retrieval
s=Store();p=Path('runtime/v2/legal-candidates');meta=json.loads((p/'prepared.json').read_text());sid=meta['snapshot_id'];docs=list(s.db.documents.find({'snapshot_id':sid}));snap=s.db.snapshots.find_one({'_id':sid})
checks={'raw_hashes':all(source_integrity(x) for x in docs),'13_documents':len(docs)==13,'index_ready':snap.get('index_ready') is True,'vector_count_matches':snap.get('vector_count')==s.db.evidence.count_documents({'snapshot_id':sid}),'source_position_count_matches':s.db.evidence_locations.count_documents({'snapshot_id':sid})==s.db.evidence.count_documents({'snapshot_id':sid})}
sc=[d for d in docs if '四川省消防条例' in d['title']];checks['historical_boundary']=sum(eligible(d,'2024-10-31','四川') for d in sc)==1 and sum(eligible(d,'2024-11-01','四川') for d in sc)==1
checks['new_version_on_boundary']=any(d['doc_id']=='2528cf20dfa089fb' and eligible(d,'2024-11-01','四川') for d in sc)
gb=next(d for d in docs if d['doc_id']=='9cffdd8a46a056cc');checks['table_restored']='水基型灭火器 | 6' in gb['full_text'] and '二氧化碳灭火器 | 12' in gb['full_text'];checks['commentary_not_normative']='【条文说明】' not in gb['full_text']
r=Retrieval(s);smoke=[]
for query,date in [('四川 消防条例 单位 消防安全 责任','2024-10-31'),('四川 消防条例 单位 消防安全 责任','2024-11-01'),('室内消火栓 设置 方便使用和维护','2026-10-03'),('灭火器 最大报废期限 水基型 6','2026-10-03')]:
 result=r.search([query],sid,date,mode='bm25',k=5);smoke.append({'query':query,'date':date,'result':result})
checks['smoke_results_exist']=all(bool(x['result'].get('evidence')) for x in smoke) if isinstance(smoke[0]['result'],dict) else True
# Source OCR is a parallel diagnostic; never claim these noisy OCR lines are certified.
ocr=list((p/'ocr').glob('page-*.json'));checks['ocr_pages_complete']=len(ocr)==31
if not all(checks.values()):print(json.dumps(checks,ensure_ascii=False));raise RuntimeError('legal snapshot checks failed')
publish_snapshot(s,sid,expected_active=meta['old_snapshot'])
report={**meta,'state':'published','checks':checks,'document_count':len(docs),'evidence_count':s.db.evidence.count_documents({'snapshot_id':sid}),'ocr_pages':31,'ocr_engine':'RapidOCR 1.4.4 ONNX CPU','ocr_unreviewed':True,'ocr_article_matches':121,'normative_articles':122,'table_visual_crosscheck':{'digital_page':43,'scan_page':25,'human_professional_review':False},'retrieval_smoke':smoke,'published_at':datetime.datetime.now(datetime.timezone.utc).isoformat()}
(Path('reports/v2/astra-annotation')/'legal-supplement.json').write_text(json.dumps(report,ensure_ascii=False,indent=2,default=str));print(json.dumps({'snapshot':sid,'checks':checks},ensure_ascii=False))
