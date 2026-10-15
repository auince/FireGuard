import json,math,time
from collections import Counter,OrderedDict
import numpy as np
import requests
from pymilvus import MilvusClient
from xfagent.retrieval import tokens,rrf
from .config import MILVUS,EMBED_URL,RERANK_URL
from .facts import eligible,fetch_evidence

def embed(texts,timeout=30):
    r=requests.post(EMBED_URL,json={'texts':texts},timeout=(3,timeout));r.raise_for_status()
    a=np.array(r.json()['vectors'],dtype='float32')
    if a.ndim!=2 or len(a)!=len(texts) or not np.isfinite(a).all() or (np.linalg.norm(a,axis=1)==0).any():raise ValueError('invalid embedding output')
    return a/np.maximum(np.linalg.norm(a,axis=1,keepdims=True),1e-12)

def collection(sid):return 'xfv2_'+sid.replace('-','_')

def index_snapshot(store,sid):
    """Build a new physical index, then publish its pointer after count validation.

    Never overwrite a published snapshot or depend on legacy local NumPy files.
    """
    from pymilvus import DataType
    from uuid import uuid4
    snapshot = store.db.snapshots.find_one({'_id':sid})
    if not snapshot:
        raise ValueError('unknown snapshot')
    if snapshot.get('state') == 'published':
        if snapshot.get('index_schema') == 'title-body-v1' and snapshot.get('index_ready'):
            return snapshot['vector_count']
        raise ValueError('prepare a new heading-path snapshot before rebuilding a published index')
    rows = list(store.db.evidence.find({'snapshot_id':sid}))
    if not rows:
        raise ValueError('empty evidence snapshot')
    client = MilvusClient(uri=MILVUS,timeout=20)
    name = collection(sid) + '_dual_' + uuid4().hex[:12]
    created = False
    try:
        dimension = None
        for start in range(0,len(rows),24):
            batch = rows[start:start+24]
            bodies = embed([e['text'] for e in batch],timeout=120)
            titles = embed([e.get('title') or e.get('document_title') or e['text'] for e in batch],timeout=120)
            if bodies.shape != titles.shape:
                raise ValueError('title/body embedding dimensions differ')
            if dimension is None:
                dimension = bodies.shape[1]
                schema = client.create_schema(auto_id=False,enable_dynamic_field=False)
                schema.add_field('id',DataType.VARCHAR,is_primary=True,max_length=64)
                schema.add_field('doc_id',DataType.VARCHAR,max_length=512)
                for field in ('body_vector','title_vector'):
                    schema.add_field(field,DataType.FLOAT_VECTOR,dim=dimension)
                params = client.prepare_index_params()
                for field in ('body_vector','title_vector'):
                    params.add_index(field_name=field,index_type='AUTOINDEX',metric_type='COSINE')
                client.create_collection(name,schema=schema,index_params=params,consistency_level='Strong')
                created = True
            if bodies.shape[1] != dimension:
                raise ValueError('embedding dimension changed during build')
            client.upsert(name,[{'id':e['evidence_id'],'doc_id':e['doc_id'],
                'body_vector':body.tolist(),'title_vector':title.tolist()}
                for e,body,title in zip(batch,bodies,titles)])
        client.flush(name)
        count = client.query(name,filter='',output_fields=['count(*)'])[0]['count(*)']
        if count != len(rows):
            raise ValueError('Milvus count mismatch')
        changed = store.db.snapshots.update_one({'_id':sid,'state':{'$ne':'published'}},{'$set':{
            'index_ready':True,'collection':name,'vector_count':len(rows),
            'index_schema':'title-body-v1','vector_dimension':dimension,
            'vector_fields':['body_vector','title_vector']}})
        if not changed.matched_count:
            raise ValueError('snapshot published during rebuild')
    except Exception:
        if created:
            client.drop_collection(name)
        raise
    finally:
        if hasattr(client,'close'):client.close()
    return len(rows)

class Retrieval:
    def __init__(self,store):
        self.store=store;self.cache=OrderedDict();self.vector=None;self.embeddings=OrderedDict()

    def corpus(self,sid):
        if sid not in self.cache:
            rows=list(self.store.db.evidence.find({'snapshot_id':sid}))
            tf=[Counter(tokens(e.get('title','')+' '+e['text'])) for e in rows]
            lengths=[sum(x.values()) for x in tf]
            self.cache[sid]=(rows,tf,Counter(t for x in tf for t in x),sum(lengths)/max(1,len(tf)),lengths)
            while len(self.cache)>3:self.cache.popitem(last=False)
        self.cache.move_to_end(sid)
        return self.cache[sid]

    def query_vectors(self,texts,sid,timeout):
        snapshot=self.store.db.snapshots.find_one({'_id':sid}) or {}
        namespace=(sid,EMBED_URL,snapshot.get('embedding_revision',snapshot.get('embedding_model','bge-m3')))
        vectors={};missing=[];hits=0
        for text in dict.fromkeys(texts):
            key=namespace+(text,);value=self.embeddings.get(key)
            if value and time.monotonic()-value[0]<300:
                vectors[text]=value[1];self.embeddings.move_to_end(key);hits+=1
            else:missing.append(text)
        if missing:
            for text,vector in zip(missing,embed(missing,timeout=timeout)):
                vectors[text]=vector;self.embeddings[namespace+(text,)]=(time.monotonic(),vector)
                self.embeddings.move_to_end(namespace+(text,))
            while len(self.embeddings)>512:self.embeddings.popitem(last=False)
        return [vectors[t] for t in texts],{'hits':hits,'misses':len(missing),'http_batches':int(bool(missing))}

    def search(self,queries,sid,as_of,jurisdiction='四川',mode='rerank',k=5,parent_expand=False,deadline=None,dense_hint=None,linked_evidence_ids=None):
        if mode not in {'bm25','dense','rrf','rerank','hyde'}:raise ValueError('unknown retrieval mode')
        if not 1<=k<=8:raise ValueError('evidence limit must be 1..8')
        queries=list(dict.fromkeys(q for q in queries if isinstance(q,str) and q.strip()))[:3]
        if not queries:raise ValueError('at least one non-empty query is required')
        started=time.monotonic();timings={};cache_stats={'hits':0,'misses':0,'http_batches':0};warnings=[]
        def remaining(cap):
            value=min(cap,deadline-time.monotonic()) if deadline else cap
            if value<=0:raise TimeoutError('retrieval deadline exhausted')
            return value
        rows,tf,df,avg,lengths=self.corpus(sid)
        # Fresh Mongo filtering preserves revocations; no stale cached eligibility.
        filt={'snapshot_id':sid,'ready':True,'status':'source_verified',
              'kind':{'$in':['law','regulation','standard','local_regulation']},
              'jurisdiction':{'$in':['全国',jurisdiction]},'$and':[
              {'$or':[{'effective_from':{'$lte':as_of}},{'effective_from':None}]},
              {'$or':[{'effective_until':{'$gt':as_of}},{'effective_until':None}]}]}
        docs={d['doc_id']:d for d in self.store.db.documents.find(filt) if eligible(d,as_of,jurisdiction)}
        timings['corpus_and_filter']=time.monotonic()-started
        rankings=[];sparse_lists=[];n=len(rows);t=time.monotonic()
        for query in queries:
            if deadline and time.monotonic()>deadline:warnings.append('retrieval_budget_exhausted');break
            scores={};terms=set(tokens(query))
            for i,e in enumerate(rows):
                if e['doc_id'] not in docs:continue
                score=0;denom=1.5*(.25+.75*lengths[i]/max(avg,1))
                for term in terms:
                    f=tf[i].get(term,0)
                    if f:score+=math.log(1+(n-df[term]+.5)/(df[term]+.5))*f*2.5/(f+denom)
                if score>0:scores[e['evidence_id']]=score
            sparse_lists.append(sorted(scores,key=lambda x:(-scores[x],x))[:20])
        timings['bm25']=time.monotonic()-t
        dense_lists=[];title_lists=[];dense_fields=[]
        snapshot=self.store.db.snapshots.find_one({'_id':sid}) or {}
        dual=snapshot.get('index_schema')=='title-body-v1'
        if mode!='bm25' and docs and sparse_lists:
            try:
                texts=queries[:len(sparse_lists)]
                if mode=='hyde' and dense_hint:texts=[dense_hint]+texts[1:]
                elif mode=='hyde':warnings.append('hyde_hint_missing_fallback_rrf')
                t=time.monotonic();vectors,cache_stats=self.query_vectors(texts,sid,remaining(20))
                timings['embedding']=time.monotonic()-t
                if self.vector is None:self.vector=MilvusClient(uri=MILVUS,timeout=min(5,remaining(5)))
                fields=['body_vector','title_vector'] if dual else ['vector']
                for field in fields:
                    try:
                        t=time.monotonic()
                        hits=self.vector.search(snapshot.get('collection') or collection(sid),
                            data=[q.tolist() for q in vectors],anns_field=field,limit=40,
                            filter='doc_id in '+json.dumps(list(docs)),output_fields=['doc_id'],timeout=remaining(20))
                        if len(hits)!=len(texts):raise ValueError('vector result count mismatch')
                        values=[[str(h['id']) for h in group] for group in hits]
                        if field=='title_vector':title_lists=values
                        else:dense_lists=values
                        dense_fields.append(field);timings[field]=time.monotonic()-t
                    except Exception as exc:
                        warnings.append(field+'_unavailable:'+type(exc).__name__)
            except Exception as exc:warnings.append('dense_unavailable:'+type(exc).__name__)
        for i,sparse in enumerate(sparse_lists):
            if mode!='dense' or not (dense_lists or title_lists):rankings.append(sparse)
            if i<len(dense_lists):rankings.append(dense_lists[i])
            if i<len(title_lists):rankings.append(title_lists[i])
        # Case associations are candidate hints only; canonical refilling below is mandatory.
        links=list(dict.fromkeys(linked_evidence_ids or []))[:10]
        if links:rankings.append(links)
        ids,scores=rrf(rankings);ids=ids[:60];t=time.monotonic()
        candidates=[fetch_evidence(self.store,sid,eid,as_of,jurisdiction) for eid in ids]
        candidates=[c for c in candidates if c];timings['canonical_refill']=time.monotonic()-t
        if mode=='rerank' and candidates:
            try:
                t=time.monotonic()
                r=requests.post(RERANK_URL,json={'query':'\n'.join(queries),'texts':[' / '.join(c.get('heading_path',[]))+'\n'+c['text'] for c in candidates]},timeout=(3,remaining(40)));r.raise_for_status()
                values=r.json()['scores']
                if len(values)!=len(candidates) or not all(math.isfinite(float(v)) for v in values):raise ValueError('reranker scores')
                for c,v in zip(candidates,values):c['rerank_score']=float(v)
                candidates.sort(key=lambda c:(-c['rerank_score'],c['evidence_id']))
                timings['reranking']=time.monotonic()-t
            except Exception as exc:warnings.append('reranker_unavailable:'+type(exc).__name__)
        threshold=self.store.db.settings.find_one({'_id':'rerank_threshold:'+sid})
        if threshold and not any(w.startswith('reranker_unavailable') for w in warnings) and mode=='rerank':
            candidates=[c for c in candidates if c.get('rerank_score',float('-inf'))>=threshold['value']]
        output=[];seen=set()
        for c in candidates:
            key=(c['doc_id'],tuple(c.get('heading_path',[])),c.get('article'),c['quote_hash'])
            if key in seen:continue
            seen.add(key);c['rrf_score']=scores.get(c['evidence_id'],0)
            if not parent_expand:c.pop('parent_text',None)
            output.append(c)
            if len(output)>=k:break
        timings['total']=time.monotonic()-started
        return {'evidence':output,'warnings':warnings,'candidate_count':len(ids),'queries':queries,
                'telemetry':{'seconds':timings,'embedding_cache':cache_stats,'dense_queries':max(len(dense_lists),len(title_lists)),
                             'vector_fields':dense_fields,'index_schema':snapshot.get('index_schema','legacy-body'),
                             'title_candidates':sum(map(len,title_lists)),'linked_candidates':len(links),
                             'hypothesis_used_for_embedding_only':bool(mode=='hyde' and dense_hint and dense_lists)}}
