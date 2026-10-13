import json,hashlib,collections,subprocess
from pathlib import Path
from xfagent.v2.store import Store,digest
from xfagent.v2.facts import fetch_evidence
from xfagent.v2.config import ROOT
out=ROOT/'reports/v2/astra-annotation';rows=list(map(json.loads,(out/'model-reference.jsonl').read_text().splitlines()));cases={r['id']:r for r in map(json.loads,(ROOT/'benchmarks/inspection_scenarios/v2/cases.jsonl').read_text().splitlines())};s=Store();errors=[];image_count=0;references=0
for r in rows:
 c=cases[r['case_id']]
 if c['split']!=r['split'] or c['facility']!=r['facility']:errors.append([r['case_id'],'identity'])
 if r['original_input']!={k:v for k,v in c['input'].items() if k in ['query','facility','jurisdiction','as_of','scene','mode']}:errors.append([r['case_id'],'input changed'])
 if c.get('image_path'):
  image_count+=1
  if hashlib.sha256(Path(c['image_path']).read_bytes()).hexdigest()!=r['image_sha256']:errors.append([r['case_id'],'original image'])
 for alias,e in r['reference_aliases'].items():
  references+=1;original=fetch_evidence(s,r['snapshot_id'],e['evidence_id'],r['original_input']['as_of'],r['original_input']['jurisdiction'])
  if not original or original['text']!=e['text'] or original['location']!=e['location']:errors.append([r['case_id'],alias,'source mismatch'])
  if e['location']['char_start']<0:errors.append([r['case_id'],alias,'unmapped'])
 if r['human_verified'] or r['verified'] or r['annotation_source']!='model_assisted':errors.append([r['case_id'],'false expert claim'])
if len(rows)!=300 or len({r['case_id'] for r in rows})!=300 or image_count!=120:errors.append(['cohort completeness'])
family_splits=collections.defaultdict(set)
for r in rows:family_splits[r['family_id']].add(r['split'])
if any(len(x)!=1 for x in family_splits.values()):errors.append(['split leakage'])
counts=dict(collections.Counter(r['split'] for r in rows))
if counts!={'dev':180,'validation':60,'holdout':60}:errors.append(['split counts'])
imported=s.db.reference_annotations.count_documents({'protocol_hash':rows[0]['protocol_hash'],'snapshot_id':rows[0]['snapshot_id']}) if rows else 0
if imported!=300:errors.append(['Mongo import count',imported])
raw=subprocess.check_output(['nvidia-smi','--query-gpu=index,memory.used,utilization.gpu','--format=csv,noheader,nounits'],text=True);gpu=[dict(zip(['index','memory_used_mib','utilization_percent'],map(int,line.split(',')))) for line in raw.strip().splitlines()]
report={'passed':not errors,'errors':errors,'cases':len(rows),'images':image_count,'quote_references_checked':references,'splits':counts,'families':len(family_splits),'mongo_records':imported,'expert_gold_written':0,'gpu':gpu,'api_health':None}
import requests
report['api_health']=requests.get('http://127.0.0.1:8080/api/health',timeout=10).json()
(out/'final-audit.json').write_text(json.dumps(report,ensure_ascii=False,indent=2));print(json.dumps(report,ensure_ascii=False));assert report['passed']
