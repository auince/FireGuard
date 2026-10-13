"""Create expert-review queue without filling any expert judgments automatically."""
import json
from xfagent.v2.config import ROOT
from xfagent.v2.store import Store
from xfagent.v2.graphs import inspection_graph
graph=inspection_graph(Store())
cases={c['id']:c for c in map(json.loads,(ROOT/'benchmarks/inspection_scenarios/v2/cases.jsonl').read_text().splitlines())}
results=ROOT/'reports/v2/system/all.jsonl';output=ROOT/'reports/v2/system/expert_review_queue.jsonl'
with output.open('w') as f:
 for result in map(json.loads,results.read_text().splitlines()):
  case=cases[result['case_id']];report=result.get('report',{})
  state=graph.get_state({'configurable':{'thread_id':result['run_id']}}).values if result.get('run_id') else {}
  row={'case_id':case['id'],'family_id':case['family_id'],'split':case['split'],'facility':case['facility'],
   'image_path':case.get('image_path'),'original_input':case['input'],'expected_behavior':case['expected'],
   'executed_input':state.get('request'),'frozen_memory':state.get('frozen_memory'),'fault_injection':result.get('fault_injection',[]),
   'program_checks':result.get('program_checks',{}),'hard_verification':result.get('hard_verification',{}),
   'model_observations':report.get('observations',[]),'model_conclusions':report.get('conclusions',[]),
   'retrieved_evidence':report.get('evidence',[]),'snapshot_id':result.get('snapshot_id'),'model_fingerprint':result.get('model_fingerprint'),
   'reviewer':None,'reviewed_at':None,'review_status':'pending','gold_observations':None,'required_evidence_ids':None,
   'citation_support_correct':None,'applicability_correct':None,'human_referral_correct':None,'critical_points_complete':None,'notes':None}
  f.write(json.dumps(row,ensure_ascii=False)+'\n')
print('Exported unfilled expert review queue')
