import json,math,time
from collections import Counter,OrderedDict
import numpy as np
import requests
from pymilvus import MilvusClient
from xfagent.retrieval import tokens,rrf
from .config import ROOT,MILVUS,EMBED_URL,RERANK_URL
from .facts import eligible,fetch_evidence

def embed(texts,timeout=30):
    r=requests.post(EMBED_URL,json={'texts':texts},timeout=(3,timeout));r.raise_for_status()
    a=np.array(r.json()['vectors'],dtype='float32')
    if a.ndim!=2 or len(a)!=len(texts) or not np.isfinite(a).all() or (np.linalg.norm(a,axis=1)==0).any():raise ValueError('invalid embedding output')
    return a/np.maximum(np.linalg.norm(a,axis=1,keepdims=True),1e-12)

def collection(sid):return 'xfv2_'+sid.replace('-','_')

def index_snapshot(store,sid):
    client=MilvusClient(uri=MILVUS,timeout=20);name=collection(sid)
    rows=list(store.db.evidence.find({'snapshot_id':sid}))
    old=json.loads((ROOT/'data/index/corpus.json').read_text())
    old_vectors=np.load(ROOT/'data/index/text.npy')
    old_map={c['id']:(c['text'],old_vectors[i]) for i,c in enumerate(old['children'])}
    missing=[e for e in rows if e['legacy_id'] not in old_map or old_map[e['legacy_id']][0]!=e['text']]
    fresh={}
    for start in range(0,len(missing),24):
        batch=missing[start:start+24]
        for e,v in zip(batch,embed([e['text'] for e in batch],timeout=120)):fresh[e['evidence_id']]=v
    if not client.has_collection(name):
        client.create_collection(name,dimension=int(old_vectors.shape[1]),id_type='string',max_length=64,metric_type='COSINE',consistency_level='Strong')
    for start in range(0,len(rows),100):
        values=[]
        for e in rows[start:start+100]:
            v=fresh.get(e['evidence_id'])
            if v is None:v=old_map[e['legacy_id']][1]
            values.append({'id':e['evidence_id'],'vector':v.tolist(),'doc_id':e['doc_id']})
        client.upsert(name,values)
    client.flush(name)
    result=client.query(name,filter='',output_fields=['count(*)'])
    if result[0]['count(*)']!=len(rows):raise ValueError('Milvus count mismatch')
    store.db.snapshots.update_one({'_id':sid},{'$set':{'index_ready':True,'collection':name,'vector_count':len(rows)}})
    return len(rows)

class Retrieval:
    def __init__(self,store):
        self.store=store;self.cache=OrderedDict();self.vector=None;self.embeddings=OrderedDict()

    def corpus(self,sid):
        if sid not in self.cache:
            rows=list(self.store.db.evidence.find({'snapshot_id':sid}))
            tf=[Counter(tokens(e['text'])) for e in rows]
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

    def search(self,queries,sid,as_of,jurisdiction='四川',mode='rerank',k=5,parent_expand=False,deadline=None,dense_hint=None):
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
        dense_lists=[]
        if mode!='bm25' and docs and sparse_lists:
            try:
                texts=queries[:len(sparse_lists)]
                # HyDE replaces one dense query, retaining the same query/candidate budget.
                if mode=='hyde' and dense_hint:texts=[dense_hint]+texts[1:]
                elif mode=='hyde':warnings.append('hyde_hint_missing_fallback_rrf')
                t=time.monotonic();vectors,cache_stats=self.query_vectors(texts,sid,remaining(20))
                timings['embedding']=time.monotonic()-t
                if self.vector is None:self.vector=MilvusClient(uri=MILVUS,timeout=min(5,remaining(5)))
                t=time.monotonic()
                hits=self.vector.search(collection(sid),data=[q.tolist() for q in vectors],limit=40,
                    filter='doc_id in '+json.dumps(list(docs)),output_fields=['doc_id'],timeout=remaining(20))
                if len(hits)!=len(texts):raise ValueError('vector result count mismatch')
                dense_lists=[[str(h['id']) for h in group] for group in hits]
                timings['vector_search']=time.monotonic()-t
            except Exception as exc:warnings.append('dense_unavailable:'+type(exc).__name__)
        for i,sparse in enumerate(sparse_lists):
            if mode!='dense' or not dense_lists:rankings.append(sparse)
            if i<len(dense_lists):rankings.append(dense_lists[i])
        ids,scores=rrf(rankings);ids=ids[:60];t=time.monotonic()
        candidates=[fetch_evidence(self.store,sid,eid,as_of,jurisdiction) for eid in ids]
        candidates=[c for c in candidates if c];timings['canonical_refill']=time.monotonic()-t
        if mode=='rerank' and candidates:
            try:
                t=time.monotonic()
                r=requests.post(RERANK_URL,json={'query':'\n'.join(queries),'texts':[c['text'] for c in candidates]},timeout=(3,remaining(40)));r.raise_for_status()
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
            key=(c['doc_id'],c['quote_hash'])
            if key in seen:continue
            seen.add(key);c['rrf_score']=scores.get(c['evidence_id'],0)
            if not parent_expand:c.pop('parent_text',None)
            output.append(c)
            if len(output)>=k:break
        timings['total']=time.monotonic()-started
        return {'evidence':output,'warnings':warnings,'candidate_count':len(ids),'queries':queries,
                'telemetry':{'seconds':timings,'embedding_cache':cache_stats,'dense_queries':len(dense_lists),
                             'hypothesis_used_for_embedding_only':bool(mode=='hyde' and dense_hint and dense_lists)}}
