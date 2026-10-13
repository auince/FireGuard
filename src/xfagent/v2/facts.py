"""Immutable legal snapshots. Source text is always refilled from MongoDB."""
import json,re
from pathlib import Path
from .config import ROOT,now,today
from .store import digest
from .version_metadata import validate_versions

def eligible(doc,as_of,jurisdiction):
    return (doc.get('ready') is True and doc.get('status')=='source_verified'
        and doc.get('lifecycle','active') in {'active','archived'}
        and (doc.get('lifecycle')!='archived' or bool(doc.get('effective_until')))
        and doc.get('kind') in {'law','regulation','standard','local_regulation'}
        and doc.get('jurisdiction','全国') in {'全国',jurisdiction}
        and (not doc.get('effective_from') or doc['effective_from']<=as_of)
        and (not doc.get('effective_until') or as_of<doc['effective_until']))

def source_integrity(doc):
    p=ROOT/doc['raw_path']
    return p.exists() and digest(p.read_bytes())==doc['sha256']

def prepare_snapshot(store):
    from xfagent.ingest import structure
    manifest=json.loads((ROOT/'data/legal/manifest.json').read_text())
    originals=[];evidence=[]
    for d in manifest:
        if d.get('status')!='source_verified' or d.get('kind') not in {'law','regulation','standard','local_regulation'}:continue
        if not source_integrity(d):raise ValueError('原文件哈希不匹配: '+d['id'])
        text=(ROOT/d['markdown_path']).read_text()
        doc={**d,'doc_id':d['id'],'ready':True,'jurisdiction':d.get('jurisdiction','全国'),
             'body_hash':digest(text.encode()),'full_text':text,
             'version_id':d.get('version_id',d['id']+':'+d['sha256'][:16]),
             'lifecycle':d.get('lifecycle','active'),
             'logical_document_id':d.get('logical_document_id',d['id']),
             'previous_version_id':d.get('previous_version_id'),
             'conditions':d.get('conditions',{'highrise':True} if '高层民用建筑' in d['title'] else {})}
        originals.append(doc)
        parents,children=structure(text,d['title'],d['id']);pm={p['id']:p for p in parents}
        for c in children:
            quote=c['text'];offset=text.find(quote)
            # Some legacy chunks normalize whitespace; retain an explicit unmapped marker.
            article=c.get('article') or c.get('article_number') or ''
            eid=digest([doc['version_id'],article,quote])
            evidence.append({**c,'evidence_id':eid,'legacy_id':c['id'],'doc_id':d['id'],
                'version_id':doc['version_id'],'source_hash':d['sha256'],'quote_hash':digest(quote.encode()),
                'conditions':d.get('clause_conditions',{}).get(article,{}),
                'parent_text':pm[c['parent_id']]['text'],'location':{'article':article,'char_start':offset,
                'char_end':offset+len(quote) if offset>=0 else None},'document_title':d['title']})
    validate_versions(originals)
    sid='kb-'+digest([(d['doc_id'],d['sha256'],d.get('effective_from'),d.get('effective_until'),d['body_hash'],d['conditions'],d.get('clause_conditions',{}),d['lifecycle'],
        d['version_id'],d['logical_document_id'],d['previous_version_id']) for d in originals])[:20]
    existing=store.db.snapshots.find_one({'_id':sid,'state':'published'})
    if existing:return sid
    store.db.snapshots.update_one({'_id':sid},{'$setOnInsert':{'state':'pending','created_at':now(),
        'document_count':len(originals),'evidence_count':len(evidence),'embedding_model':'bge-m3'}},upsert=True)
    for doc in originals:
        doc.update(snapshot_id=sid);doc['_id']=sid+':'+doc['doc_id'];doc.pop('id',None)
        store.db.documents.replace_one({'_id':doc['_id']},doc,upsert=True)
    for e in evidence:
        e.update(snapshot_id=sid);e['_id']=sid+':'+e['evidence_id'];e.pop('id',None)
        # Duplicate text within a document shares a stable ID; legacy aliases are retained.
        store.db.evidence.update_one({'_id':e['_id']},{'$set':e,'$addToSet':{'legacy_aliases':e['legacy_id']}},upsert=True)
    store.db.snapshots.update_one({'_id':sid},{'$set':{'evidence_count':store.db.evidence.count_documents({'snapshot_id':sid})}})
    return sid

def publish_snapshot(store,sid,expected_active=None):
    snap=store.db.snapshots.find_one({'_id':sid})
    if not snap or not snap.get('index_ready'):raise ValueError('索引尚未就绪')
    if store.db.documents.count_documents({'snapshot_id':sid})!=snap['document_count']:raise ValueError('文档数量不匹配')
    with store.client.start_session() as s:
        with s.start_transaction():
            store.db.snapshots.update_one({'_id':sid},{'$set':{'state':'published','published_at':now()}},session=s)
            selector={'_id':'active_snapshot'}
            if expected_active is not None:selector['value']=expected_active
            changed=store.db.settings.update_one(selector,{'$set':{'value':sid}},upsert=expected_active is None,session=s)
            if expected_active is not None and not changed.matched_count:raise ValueError('活动快照已变化')
    store.audit(sid,'published','snapshot_published')

def fetch_evidence(store,sid,eid,as_of,jurisdiction):
    e=store.db.evidence.find_one({'snapshot_id':sid,'evidence_id':eid})
    if not e:return None
    d=store.db.documents.find_one({'snapshot_id':sid,'doc_id':e['doc_id']})
    if not d or not eligible(d,as_of,jurisdiction):return None
    if e.get('version_id')!=d.get('version_id'):return None
    if e['source_hash']!=d['sha256'] or digest(e['text'].encode())!=e['quote_hash']:return None
    if d.get('full_text') is not None:
        body=d['full_text']
        if digest(body.encode())!=d.get('body_hash'):return None
        normalized=lambda text:re.sub(r'\s+','',text)
        if normalized(e['text']) not in normalized(body):return None
        if e.get('parent_text') and normalized(e['parent_text']) not in normalized(body):return None
    out={k:v for k,v in e.items() if k!='_id'}
    mapping=store.db.evidence_locations.find_one({'_id':sid+':'+eid,'body_hash':d.get('body_hash')})
    if mapping:out['location']=mapping['location']
    out.update(source_url=d['url'],effective_from=d.get('effective_from'),effective_until=d.get('effective_until'),
               jurisdiction=d['jurisdiction'],status=d['status'],lifecycle=d.get('lifecycle','active'))
    conditions=dict(d.get('conditions',{}))
    for field,value in e.get('conditions',{}).items():
        conditions[field]={'all':[conditions[field],value]} if field in conditions and conditions[field]!=value else value
    out['conditions']=conditions
    return out
