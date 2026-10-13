"""Read-only final audit of reviewed gold, frozen inputs, sources and publication."""
import argparse,collections,json,subprocess
from pathlib import Path
from v2_astra_review import validate,PROMPT
from v2_astra_annotate import sha
from xfagent.v2.store import Store,digest

def audit(root):
 gold=list(map(json.loads,(root/'export/astra-reviewed-gold.jsonl').read_text().splitlines()));cases={c['id']:c for c in map(json.loads,Path('benchmarks/inspection_scenarios/v2/cases.jsonl').read_text().splitlines())};manifest=json.loads((root/'export/reference-set.json').read_text());images=0;resolutions=0;raw_responses=0
 assert len(gold)==300 and {r['case_id'] for r in gold}==set(cases)
 for pf in (root/'packets').glob('*.json'):
  packet=json.loads(pf.read_text());result=json.loads((root/'responses'/pf.name).read_text())
  assert not validate(result['output'],packet)
  assert result['packet_hash']==sha(packet) and result['protocol_hash']==sha(PROMPT)
  history=result['history'];success=history[-1];raw=json.loads((root/'responses/raw'/f"{packet['family_id']}-attempt{success['attempt']}.json").read_text())
  assert raw['model']=='gpt-6-astra' and raw['choices'][0]['finish_reason']=='stop'
  obj=json.loads(raw['choices'][0]['message']['content']);assert not validate(obj,packet);assert obj==result['output'];raw_responses+=1
 for r in gold:
  c=cases[r['case_id']];assert r['split']==c['split'] and r['family_id']==c['family_id'] and r['image_sha256']==c.get('image_sha256')
  assert r['original_input']=={k:v for k,v in c['input'].items() if k in ['query','facility','jurisdiction','as_of','scene','mode']}
  assert r['label_review_status']=='completed' and r['label_requires_human_review'] is False
  assert r['annotation_source']=='astra_reviewed_model_gold' and r['human_verified'] is False
  assert len(r['review']['issue_resolutions'])==len(r['first_pass_scenario_issues']);resolutions+=len(r['review']['issue_resolutions'])
  if r['image_sha256']:
   assert sha(Path(c['image_path']).read_bytes())==r['image_sha256'];images+=1
  if r['visual_decision'] in ['uncertain','not_applicable']:assert not r['evaluation_mask']['visual_binary']
  if any(not e.get('indexed_in_snapshot',True) for e in r['reference_aliases'].values()):assert not r['evaluation_mask']['retrieval_on_frozen_snapshot']
 s=Store();setid=manifest['reference_set_id'];assert s.db.astra_reviewed_gold.count_documents({'reference_set_id':setid})==300
 assert s.db.evaluation_reference_active.find_one({'_id':'default'})['reference_set_id']==setid
 for r in gold:assert s.db.astra_reviewed_gold.find_one({'reference_set_id':setid,'case_id':r['case_id']})['record_hash']==digest(r)
 gpu=subprocess.check_output(['nvidia-smi','--query-gpu=index,memory.used,utilization.gpu','--format=csv,noheader,nounits'],text=True).strip().splitlines()
 result={'status':'passed','cases':len(gold),'original_images_hash_verified':images,'families_original_responses_verified':raw_responses,'original_issues_adjudicated':resolutions,'by_split':dict(collections.Counter(r['split'] for r in gold)),'mongo_records':300,'label_human_pending':0,'active_reference_set':setid,'gpus':gpu,'gpu_check':'observed, no GPU models started by review','legacy_reference_records':s.db.reference_annotations.count_documents({}),'strategy_replay_gold_records':s.db.replay_gold.count_documents({})}
 (root/'final-audit.json').write_text(json.dumps(result,ensure_ascii=False,indent=2));print(json.dumps(result,ensure_ascii=False))
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('root',type=Path);a=p.parse_args();audit(a.root)
