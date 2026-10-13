"""Import immutable model references; never write professional replay_gold."""
import argparse,json
from pathlib import Path
from xfagent.v2.store import Store,digest
from xfagent.v2.facts import fetch_evidence
p=argparse.ArgumentParser();p.add_argument('references',type=Path);a=p.parse_args();rows=list(map(json.loads,a.references.read_text().splitlines()));s=Store();count=0
assert len(rows)==300 and len({r['case_id'] for r in rows})==300,'full cohort required'
for r in rows:
 assert r['annotation_source']=='model_assisted' and r['human_verified'] is False and r['verified'] is False
 assert r['requested_model']==r['returned_model']=='gpt-6-astra'
 for e in r['reference_aliases'].values():
  original=fetch_evidence(s,r['snapshot_id'],e['evidence_id'],r['original_input']['as_of'],r['original_input']['jurisdiction'])
  if not original or original['text']!=e['text'] or original['source_hash']!=e['source_hash'] or original['location']!=e['location']:raise ValueError('canonical evidence mismatch: '+r['case_id'])
 identifier=digest([r['case_id'],r['protocol_hash'],r['packet_hash']]);old=s.db.reference_annotations.find_one({'_id':identifier});record={**r,'project_id':'default','_id':identifier,'record_hash':digest(r)}
 if old and old['record_hash']!=record['record_hash']:raise ValueError('immutable reference changed')
 s.db.reference_annotations.update_one({'_id':identifier},{'$setOnInsert':record},upsert=True);count+=1
s.db.reference_annotations.create_index([('project_id',1),('snapshot_id',1),('protocol_hash',1),('case_id',1)])
print(json.dumps({'imported':count,'collection':'reference_annotations','expert_gold_written':0,'replay_gold_unchanged':True}))
