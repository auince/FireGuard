"""Publish a complete, immutable Astra-reviewed evaluation reference set."""
import argparse,json,hashlib
from pathlib import Path
from xfagent.v2.store import Store,digest
from xfagent.v2.facts import fetch_evidence
from v2_astra_review import PROMPT,PROTOCOL
from v2_astra_annotate import sha,norm

def publish(root):
 rows=list(map(json.loads,(root/'astra-reviewed-gold.jsonl').read_text().splitlines()));manifest=json.loads((root/'reference-set.json').read_text());supp=json.loads((root.parent/'background/supplemental-evidence.json').read_text());supp_by_id={e['evidence_id']:e for e in supp.values()}
 assert len(rows)==300 and len({r['case_id'] for r in rows})==300
 assert manifest['gold_sha256']==sha((root/'astra-reviewed-gold.jsonl').read_bytes())
 assert manifest['cases_sha256']==sha((root/'cases.jsonl').read_bytes())
 assert manifest['label_review_complete'] is True and manifest['human_labeling_required'] is False
 assert sha((root.parent/'background/GB50444-2008.pdf').read_bytes())==next(iter(supp.values()))['source_hash']
 s=Store();setid=manifest['reference_set_id'];citations=0
 # Validate the entire cohort before the first database mutation.
 for r in rows:
  assert r['label_review_status']=='completed' and r['label_requires_human_review'] is False and r['human_verified'] is False
  assert r['annotation_source']=='astra_reviewed_model_gold' and r['protocol']==PROTOCOL and r['protocol_hash']==sha(PROMPT)
  assert r['requested_model']==r['returned_model']=='gpt-6-astra'
  assert r['review']['label_review_complete'] is True
  for e in r['reference_aliases'].values():
   if e.get('indexed_in_snapshot',True):
    original=fetch_evidence(s,r['snapshot_id'],e['evidence_id'],r['original_input']['as_of'],r['original_input']['jurisdiction'])
    assert original and all(original[k]==e[k] for k in ['text','source_hash','location']),'canonical mismatch '+r['case_id']
   else:assert e==supp_by_id[e['evidence_id']],'supplement source mismatch'
   citations+=1
  by_id={e['evidence_id']:e for e in r['reference_aliases'].values()}
  for req in r['evidence_requirements']:
   for q in req['quotes']:assert norm(q['quote']) in norm(by_id[q['evidence_id']]['text'])
  if any(not e.get('indexed_in_snapshot',True) for e in by_id.values()):assert r['evaluation_mask']['retrieval_on_frozen_snapshot'] is False
 old=s.db.evaluation_reference_sets.find_one({'_id':setid})
 if old:assert old['manifest_hash']==digest(manifest),'immutable manifest conflict'
 with s.client.start_session() as session:
  with session.start_transaction():
   for r in rows:
    identifier=digest([setid,r['case_id']]);record={**r,'_id':identifier,'project_id':'default','reference_set_id':setid,'record_hash':digest(r)}
    existing=s.db.astra_reviewed_gold.find_one({'_id':identifier},session=session)
    if existing:assert existing['record_hash']==record['record_hash'],'immutable gold conflict'
    s.db.astra_reviewed_gold.update_one({'_id':identifier},{'$setOnInsert':record},upsert=True,session=session)
   s.db.evaluation_reference_sets.update_one({'_id':setid},{'$setOnInsert':{**manifest,'manifest_hash':digest(manifest),'project_id':'default','case_count':len(rows),'source':'model_adjudicated','supplemental_evidence':supp}},upsert=True,session=session)
   s.db.evaluation_reference_active.update_one({'_id':'default'},{'$set':{'reference_set_id':setid,'gold_sha256':manifest['gold_sha256'],'protocol':PROTOCOL}},upsert=True,session=session)
 s.db.astra_reviewed_gold.create_index([('project_id',1),('reference_set_id',1),('case_id',1)],unique=True)
 print(json.dumps({'imported':len(rows),'case_evidence_references_validated':citations,'reference_set_id':setid,'collection':'astra_reviewed_gold','human_label_pending':0,'active_reference_published':True,'holdout_not_added_to_strategy_replay':True}))
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('root',type=Path);a=p.parse_args();publish(a.root)
