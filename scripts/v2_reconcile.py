"""Read-only cross-store readiness and outbox audit; no cross-database transaction claim."""
import json
from xfagent.v2.config import ROOT,MILVUS
from xfagent.v2.store import Store,digest
from xfagent.v2.retrieval import collection
from pymilvus import MilvusClient
s=Store();sid=s.active_snapshot();snap=s.db.snapshots.find_one({'_id':sid});v=MilvusClient(uri=MILVUS)
report={'snapshot':sid,'mongo_documents':s.db.documents.count_documents({'snapshot_id':sid}),
 'mongo_evidence':s.db.evidence.count_documents({'snapshot_id':sid}),
 'milvus_rows':v.get_collection_stats(collection(sid)).get('row_count'),
 'mapped_evidence':s.db.evidence_locations.count_documents({'snapshot_id':sid}),
 'mismatched_quotes':sum(digest(e['text'].encode())!=e['quote_hash'] for e in s.db.evidence.find({'snapshot_id':sid})),
 'orphan_outbox':sum(s.db.jobs.count_documents({'_id':x['job_id']})==0 for x in s.db.outbox.find({})),
 'unsent_outbox':s.db.outbox.count_documents({'sent':False}),
 'pending_snapshots':[x['_id'] for x in s.db.snapshots.find({'state':'pending'})]}
report['index_counts_match']=report['mongo_evidence']==int(report['milvus_rows'])==snap['evidence_count']
(ROOT/'reports/v2/reconciliation.json').write_text(json.dumps(report,indent=2));print(json.dumps(report))
