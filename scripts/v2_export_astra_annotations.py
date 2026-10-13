"""Validate and flatten Astra annotations with source and image provenance."""
import argparse,collections,json,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).parent))
from v2_astra_annotate import validate,sha,PROMPT

def export(results,packets,output,locations=None):
 output.mkdir(parents=True,exist_ok=True);rows=[];failures=[];usage=collections.Counter();histories=0
 for pf in sorted(packets.glob('*.json')):
  packet=json.loads(pf.read_text());f=results/pf.name
  if not f.exists():failures.append({'family_id':packet['family_id'],'status':'not_completed'});continue
  record=json.loads(f.read_text());errors=validate(record['output'],packet)
  if record.get('protocol_hash')!=sha(PROMPT) or record.get('packet_hash')!=sha(packet):errors.append('provenance mismatch')
  if errors:failures.append({'family_id':packet['family_id'],'errors':errors});continue
  for h in record['history']:
   histories+=1
   for k in ['prompt_tokens','completion_tokens','total_tokens']:usage[k]+=h.get('usage',{}).get(k,0)
  cases={c['case_id']:c for c in packet['cases']}
  for a in record['output']['annotations']:
   aliases={k:dict(packet['evidence_aliases'][k]) for k in a['required_evidence_ids']};req=[]
   if locations:
    assert locations['snapshot_id']==packet['snapshot_id']
    for e in aliases.values():
     e['packet_location']=e['location'];e['location']=locations['locations'][e['evidence_id']]
     assert e['location']['char_start']>=0
     e['location_provenance']='MongoDB canonical evidence_locations; metadata refill after independent annotation'
   for x in a['evidence_requirements']:
    req.append({**x,'any_of':[aliases[k]['evidence_id'] for k in x['any_of']],'quotes':[{**q,'evidence_id':aliases[q['evidence_id']]['evidence_id'],'packet_alias':q['evidence_id']} for q in x['quotes']]})
   rows.append({**a,'required_evidence_ids':[aliases[k]['evidence_id'] for k in a['required_evidence_ids']],'evidence_requirements':req,'reference_aliases':aliases,'original_input':cases[a['case_id']]['input'],'image_sha256':cases[a['case_id']].get('image_sha256'),'family_id':packet['family_id'],'split':packet['split'],'snapshot_id':packet['snapshot_id'],'protocol':record['protocol'],'protocol_hash':record['protocol_hash'],'packet_hash':record['packet_hash'],'annotation_source':'model_assisted','requested_model':record['requested_model'],'returned_model':record['returned_model'],'provider':record['provider'],'human_verified':False,'expert_review_status':'pending','verified':False,'created_at':record['created_at'],'automated_validation':'passed','validation_scope':'format, source identity, verbatim quotes, date, region, declared applicability fields; not proof of semantic correctness','context_selection':packet['context_selection']})
 rows.sort(key=lambda x:x['case_id']);(output/'model-reference.jsonl').write_text(''.join(json.dumps(x,ensure_ascii=False)+'\n' for x in rows))
 summary={'completed_cases':len(rows),'expected_cases':300,'completed_families':len(set(r['family_id'] for r in rows)),'pending_or_failed_families':failures,'by_facility':dict(collections.Counter(r['facility'] for r in rows)),'by_split':dict(collections.Counter(r['split'] for r in rows)),'with_images':sum(bool(r['image_sha256']) for r in rows),'visual_decisions':dict(collections.Counter(r['visual_decision'] for r in rows)),'with_scenario_issues':sum(bool(r['scenario_issues']) for r in rows),'with_knowledge_gaps':sum(bool(r['knowledge_gaps']) for r in rows),'needs_additional_info':sum(r['needs_additional_info'] for r in rows),'confidence':dict(collections.Counter(r['confidence'] for r in rows)),'expert_verified_cases':0,'model':'gpt-6-astra','protocol_hash':sha(PROMPT),'snapshot_ids':sorted(set(r['snapshot_id'] for r in rows)),'provider_reported_usage_completed_families_including_retries':dict(usage),'requests_in_completed_families':histories,'usage_note':'Third-party provider reported tokens may include provider overhead; not audited billing. Probe and aborted pilot are excluded.'}
 (output/'annotation-summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2))
 (output/'scenario-issues.jsonl').write_text(''.join(json.dumps({k:r[k] for k in ['case_id','split','facility','image_sha256','scenario_issues']},ensure_ascii=False)+'\n' for r in rows if r['scenario_issues']))
 print(json.dumps({k:summary[k] for k in ['completed_cases','completed_families','with_images','with_scenario_issues','expert_verified_cases']},ensure_ascii=False));return rows,summary
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--results',type=Path,required=True);p.add_argument('--packets',type=Path,required=True);p.add_argument('--output',type=Path,required=True);p.add_argument('--locations',type=Path);a=p.parse_args();export(a.results,a.packets,a.output,json.loads(a.locations.read_text()) if a.locations else None)
