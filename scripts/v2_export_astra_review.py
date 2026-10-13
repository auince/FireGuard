"""Export source-aware, adjudicated model gold without a human labeling gate."""
import argparse,collections,json
from pathlib import Path
from v2_astra_review import validate,PROMPT,PROTOCOL
from v2_astra_annotate import sha

def export(root,allow_partial=False):
 out=root/'review-export';out.mkdir(exist_ok=True);rows=[];failures=[];usage=collections.Counter();dispositions=collections.Counter();changes=collections.Counter();requests=0
 for pf in sorted((root/'review-packets').glob('*.json')):
  p=json.loads(pf.read_text());rf=root/'review-results'/pf.name
  if not rf.exists():failures.append(p['family_id']);continue
  record=json.loads(rf.read_text());errors=validate(record['output'],p)
  if record['protocol_hash']!=sha(PROMPT) or record['packet_hash']!=sha(p):errors.append('provenance mismatch')
  if errors:raise ValueError(str(errors))
  if record['returned_model']!='gpt-6-astra':raise ValueError('wrong model')
  for h in record['history']:
   requests+=1
   for k in ['prompt_tokens','completion_tokens','total_tokens']:usage[k]+=(h.get('usage') or {}).get(k,0)
  by_id={r['case_id']:r for r in record['output']['reviews']};cases={c['case_id']:c for c in p['cases']};old={a['case_id']:a for a in p['first_pass_annotations']}
  for a in record['output']['annotations']:
   cid=a['case_id'];r=by_id[cid];c=cases[cid];aliases={k:p['evidence_aliases'][k] for k in a['required_evidence_ids']};req=[]
   for q in a['evidence_requirements']:
    req.append({**q,'any_of':[aliases[k]['evidence_id'] for k in q['any_of']],'quotes':[{**x,'packet_alias':x['evidence_id'],'evidence_id':aliases[x['evidence_id']]['evidence_id']} for x in q['quotes']]})
   changed=[k for k,v in r['patch'].items() if old[cid].get(k)!=v];changes.update(changed);dispositions.update(i['disposition'] for i in r['issue_resolutions'])
   active=r['evaluation']['status']!='not_evaluable';in_index=all(e.get('indexed_in_snapshot',True) for e in aliases.values())
   masks={'behavior':active,'visual_binary':active and bool(c['image_present']) and a['visual_decision'] in ['normal','abnormal'],'visual_uncertainty':active and bool(c['image_present']),'retrieval_on_frozen_snapshot':active and bool(req) and in_index,'reference_answer':active}
   row={**a,'required_evidence_ids':[aliases[k]['evidence_id'] for k in a['required_evidence_ids']],'evidence_requirements':req,'reference_aliases':aliases,'original_input':c['input'],'execution_context':c['execution_context'],'image_sha256':c.get('image_sha256'),'family_id':p['family_id'],'split':p['split'],'snapshot_id':p['snapshot_id'],'protocol':PROTOCOL,'protocol_hash':record['protocol_hash'],'packet_hash':record['packet_hash'],'first_pass_record_hash':p['first_pass_record_hash'],'annotation_source':'astra_reviewed_model_gold','requested_model':record['requested_model'],'returned_model':record['returned_model'],'provider':record['provider'],'human_verified':False,'label_review_status':'completed','label_requires_human_review':False,'evaluation_approved':active,'evaluation_mask':masks,'review_decision':r['decision'],'review':r,'changed_fields':changed,'first_pass_visual_decision':old[cid]['visual_decision'],'first_pass_scenario_issues':old[cid]['scenario_issues'],'first_pass_annotation':old[cid],'reviewed_at':record['created_at'],'automated_validation':'passed','context_selection':p['context_selection'],'report_requires_human_signoff':a['needs_human_review']}
   # Legacy field referred to operational report approval, not dataset annotation.
   del row['needs_human_review']
   rows.append(row)
 if failures and not allow_partial:raise ValueError('unfinished families: '+','.join(failures))
 rows.sort(key=lambda x:x['case_id'])
 (out/'astra-reviewed-gold.jsonl').write_text(''.join(json.dumps(r,ensure_ascii=False)+'\n' for r in rows))
 summary={'completed_cases':len(rows),'expected_cases':300,'completed_families':len({r['family_id'] for r in rows}),'pending_families':failures,'label_human_pending':0,'model':'gpt-6-astra','protocol':PROTOCOL,'protocol_hash':sha(PROMPT),'by_facility':dict(collections.Counter(r['facility'] for r in rows)),'by_split':dict(collections.Counter(r['split'] for r in rows)),'review_decisions':dict(collections.Counter(r['review_decision'] for r in rows)),'evaluation_status':dict(collections.Counter(r['review']['evaluation']['status'] for r in rows)),'with_images':sum(bool(r['image_sha256']) for r in rows),'visual_decisions':dict(collections.Counter(r['visual_decision'] for r in rows)),'visual_decision_changed':sum(r['visual_decision']!=r['first_pass_visual_decision'] for r in rows),'changed_fields':dict(changes),'original_issue_cases':sum(bool(r['first_pass_scenario_issues']) for r in rows),'original_issues_adjudicated':sum(len(r['review']['issue_resolutions']) for r in rows),'issue_dispositions':dict(dispositions),'remaining_uncertainty_cases':sum(bool(r['review']['evaluation']['uncertainties']) for r in rows),'evaluation_mask_counts':{k:sum(r['evaluation_mask'][k] for r in rows) for k in ['behavior','visual_binary','visual_uncertainty','retrieval_on_frozen_snapshot','reference_answer']},'with_supplemental_evidence':sum(any(not e.get('indexed_in_snapshot',True) for e in r['reference_aliases'].values()) for r in rows),'case_evidence_references':sum(len(r['reference_aliases']) for r in rows),'provider_reported_usage_including_successful_family_retries':dict(usage),'request_attempts_in_completed_families':requests,'usage_note':'Retained successful records and their recorded retries only; interrupted or overlapping calls are excluded. Not full invoiced usage.','not_accuracy_note':'accept/correct counts measure annotation changes, not model quality or independently calibrated accuracy','snapshot_ids':sorted({r['snapshot_id'] for r in rows})}
 (out/'review-summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2))
 (out/'adjudication-log.jsonl').write_text(''.join(json.dumps({'case_id':r['case_id'],'review':r['review'],'changed_fields':r['changed_fields']},ensure_ascii=False)+'\n' for r in rows))
 if not failures:
  originals={c['id']:c for c in map(json.loads,(root/'cases.jsonl').read_text().splitlines())};enriched=[]
  for r in rows:
   c=originals[r['case_id']];c['review_status']='astra_reviewed';c['gold_reference']={'file':'astra-reviewed-gold.jsonl','case_id':r['case_id'],'protocol_hash':r['protocol_hash'],'packet_hash':r['packet_hash'],'evaluation_mask':r['evaluation_mask']};c['expected']['visual_gold_status']='astra_reviewed' if r['image_sha256'] else 'not_applicable';enriched.append(c)
  (out/'cases.jsonl').write_text(''.join(json.dumps(c,ensure_ascii=False)+'\n' for c in enriched))
  (out/'reference-set.json').write_text(json.dumps({'reference_set_id':'astra-review-'+sha(PROMPT)[:16],'protocol':PROTOCOL,'gold_source':'model','reviewer':'gpt-6-astra','label_review_complete':True,'human_labeling_required':False,'gold_file':'astra-reviewed-gold.jsonl','gold_sha256':sha((out/'astra-reviewed-gold.jsonl').read_bytes()),'cases_file':'cases.jsonl','cases_sha256':sha((out/'cases.jsonl').read_bytes()),'split_policy':'original family split retained; review protocol frozen before calls; holdout labels not for policy tuning','retrieval_policy':'Use evaluation_mask.retrieval_on_frozen_snapshot; supplemental evidence is not in the frozen production index. Report excluded denominators.','uncertainty_policy':'uncertain is a valid abstention target, never turn into a normal label; visual binary metrics exclude it and report coverage'},ensure_ascii=False,indent=2))
 print(json.dumps(summary,ensure_ascii=False));return rows,summary
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('root',type=Path);p.add_argument('--allow-partial',action='store_true');a=p.parse_args();export(a.root,a.allow_partial)
