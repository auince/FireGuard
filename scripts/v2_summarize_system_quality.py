"""Separate executable constraints, model judgments and unavailable expert judgments."""
import json,hashlib
from collections import Counter
from xfagent.v2.config import ROOT
from xfagent.v2.store import Store
from xfagent.v2.facts import fetch_evidence
path=ROOT/'reports/v2/system/all.jsonl';rows=[json.loads(x) for x in path.read_text().splitlines()]
store=Store();canonical_cache={}
cases={c['id']:c for c in map(json.loads,(ROOT/'benchmarks/inspection_scenarios/v2/cases.jsonl').read_text().splitlines())}
def canonical(row,eid):
 req=cases[row['case_id']]['input'];key=(row['snapshot_id'],eid,req['as_of'],req['jurisdiction'])
 if key not in canonical_cache:canonical_cache[key]=fetch_evidence(store,*key)
 return canonical_cache[key]
def summarize(selected):
 errors=Counter(e['code'] for x in selected for e in x.get('hard_verification',{}).get('errors',[]) if e['code']!='semantic_unsupported')
 references=0;existent=0;quotes=0;consistent=0;model=Counter()
 for x in selected:
  report=x.get('report',{});evidence={e['evidence_id']:e for e in report.get('evidence',[])}
  model[x.get('model_semantic_review') or 'not_performed']+=1
  for eid,e in evidence.items():
   original=canonical(x,eid)
   quotes+=1;consistent+=bool(original and original['text']==e['text'] and original['quote_hash']==e['quote_hash']
     and hashlib.sha256(e['text'].encode()).hexdigest()==e['quote_hash'])
  for c in report.get('conclusions',[]):
   for ref in c.get('evidence_ids',[]):references+=1;existent+=bool(ref in evidence and canonical(x,ref))
 return {'cases':len(selected),'execution_errors':sum('error' in x for x in selected),
  'drafts':sum(x.get('report',{}).get('status')=='draft' for x in selected),
  'deterministic_claim_verification_pass':sum(x.get('report',{}).get('status')=='draft' and not any(e['code']!='semantic_unsupported' for e in x.get('hard_verification',{}).get('errors',[])) for x in selected),
  'citation_references':references,'references_exist':existent,'citation_existence_rate':existent/references if references else None,
  'retrieved_quotes':quotes,'quote_hashes_match':consistent,'quote_consistency_rate':consistent/quotes if quotes else None,
  'program_errors_in_drafts':dict(errors),'model_semantic_judgments':dict(model),
  'expert_conclusion_support_accuracy':None,'expert_referral_correctness':None,'expert_critical_point_completeness':None}
report={'all':summarize(rows),'facilities':{f:summarize([x for x in rows if x['facility']==f]) for f in sorted({x['facility'] for x in rows})},
 'splits':{f:summarize([x for x in rows if x['split']==f]) for f in sorted({x['split'] for x in rows})},
 'expert_review_status':'pending','definitions':{'citation_existence':'emitted references exist in the report and authoritative Mongo snapshot, passing date, jurisdiction and source checks; zero references is undefined, not 100%',
 'quote_consistency':'report text and quote SHA256 match canonical Mongo evidence for the frozen snapshot; legal semantic support evaluated separately',
 'model_semantic_judgments':'auxiliary model result, never human accuracy','program_errors_in_drafts':'unresolved deterministic draft defects, excluding semantic_unsupported; no automated finalization',
 'deterministic_claim_verification_pass':'draft exists and has no deterministic claim-verification errors; independent of model semantic judgment',
 'legacy_all_summary_hard_verification_pass':'historical key name includes model semantic rejection; use this report to separate the two'}}
(ROOT/'reports/v2/system/quality-summary.json').write_text(json.dumps(report,ensure_ascii=False,indent=2));print('Saved separated system-quality metrics')
