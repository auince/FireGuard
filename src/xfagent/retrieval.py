"""Hierarchy-aware dense + BM25 retrieval, explicit ablations and RRF fusion."""
import json
import math
import os
import re
from collections import Counter
from datetime import date
from pathlib import Path
import numpy as np
import requests
from .config import ROOT, read_json, write_json
from .ingest import structure, sha256

def tokens(text):
    text = text.lower()
    latin = re.findall(r'[a-z0-9]+(?:[.-][a-z0-9]+)*', text)
    han = re.findall(r'[\u4e00-\u9fff]+', text)
    return latin + [s[i:i+2] for s in han for i in range(max(1, len(s)-1))]

def embed(texts):
    url = os.environ.get('XF_EMBEDDING_URL', 'http://127.0.0.1:8001/embed')
    r = requests.post(url, json={'texts': texts}, timeout=(5, 300))
    r.raise_for_status()
    a = np.asarray(r.json()['vectors'], dtype=np.float32)
    return a / np.maximum(np.linalg.norm(a, axis=1, keepdims=True), 1e-12)

def rrf(rankings, k=60):
    scores = {}
    for ranking in rankings:
        for rank, idx in enumerate(ranking, 1):
            scores[idx] = scores.get(idx, 0.) + 1 / (k + rank)
    return sorted(scores, key=lambda x: (-scores[x], str(x))), scores

def build_index(dense=True):
    docs = read_json(ROOT/'data/legal/manifest.json', [])
    parents, children = [], []
    seen = set()
    enrichment=read_json(ROOT/'data/legal/enrichment.json',{})
    for d in docs:
        if d.get('kind') == 'catalog' or d['sha256'] in seen:
            continue
        seen.add(d['sha256'])
        pp, cc = structure((ROOT/d['markdown_path']).read_text(), d['title'], d['id'])
        extra=enrichment.get(d['id'],{})
        if extra.get('source_sha256')==d['sha256']:
            suggested=extra.get('suggested',{})
            aids=' '.join(str(x) for x in suggested.get('keywords',[])[:30])
            for child in cc:child['index_title']=child['title']+' '+aids
        parents.extend(pp)
        children.extend(cc)
    if not children:
        raise ValueError('知识库为空，请先采集法规')
    out = ROOT/'data/index';out.mkdir(parents=True, exist_ok=True)
    write_json(out/'corpus.json', {'documents': docs, 'parents': parents, 'children': children})
    if dense:
        for field in ['title', 'text']:
            batches = []
            for start in range(0, len(children), 24):
                batches.append(embed([c.get('index_title',c['title']) if field=='title' else c[field] for c in children[start:start+24]]))
            np.save(out/f'{field}.npy', np.concatenate(batches))
    else:
        # Explicit sparse-only mode; do not keep stale dense arrays after rebuilding.
        for field in ['title', 'text']:
            (out/f'{field}.npy').unlink(missing_ok=True)
    meta = {'documents': len(seen), 'parents': len(parents), 'children': len(children),
            'dense': dense, 'embedding_model': os.getenv('XF_EMBEDDING_MODEL','bge-m3'),
            'corpus_sha256': sha256((out/'corpus.json').read_bytes())}
    write_json(out/'metadata.json', meta)
    return meta

class SearchIndex:
    def __init__(self, path=None):
        self.path = Path(path or ROOT/'data/index')
        c = read_json(self.path/'corpus.json', {'documents': [], 'parents': [], 'children': []})
        self.children = c['children']
        self.parents = {x['id']: x for x in c['parents']}
        self.docs = {x['id']: x for x in c['documents']}
        self.tf = [Counter(tokens(x['text'])) for x in self.children]
        self.df = Counter(t for x in self.tf for t in x)
        self.lengths = [sum(x.values()) for x in self.tf]
        self.avg = sum(self.lengths) / max(1,len(self.lengths))
        self.vectors = {f: np.load(self.path/f'{f}.npy') for f in ['title','text'] if (self.path/f'{f}.npy').exists()}

    def search(self, query, k=5, mode='hybrid', as_of=None, include_unverified=False, title_threshold=.4, query_vector=None, deduplicate_parents=True):
        if mode not in ['bm25','dense','hierarchical','weighted','hybrid','flat_hybrid','title_dense']:
            raise ValueError('unsupported retrieval mode')
        as_of = as_of or date.today().isoformat()
        allowed = []
        for i, c in enumerate(self.children):
            d = self.docs[c['doc_id']]
            if d.get('effective_from') and d['effective_from'] > as_of:continue
            if d.get('effective_until') and d['effective_until'] <= as_of:continue
            if d.get('status') != 'source_verified' and not include_unverified:continue
            if d.get('kind') in ['announcement', 'catalog']:continue
            allowed.append(i)
        if not allowed or not query.strip():return []
        n = len(self.children); bms = np.zeros(n)
        for i in allowed:
            for t in set(tokens(query)):
                f = self.tf[i].get(t, 0)
                if not f:continue
                idf = math.log(1 + (n-self.df[t]+.5)/(self.df[t]+.5))
                bms[i] += idf*f*2.5/(f+1.5*(.25+.75*self.lengths[i]/max(self.avg,1)))
        sparse = sorted((i for i in allowed if bms[i]>0), key=lambda i:-bms[i])[:60]
        if mode == 'bm25':ranking = sparse;scores = {i:float(bms[i]) for i in ranking}
        else:
            if len(self.vectors)!=2:raise ValueError('未建立稠密索引；请明确选择 bm25 或先构建向量索引')
            q = embed([query])[0] if query_vector is None else np.asarray(query_vector, dtype=np.float32)
            if q.ndim != 1 or q.shape[0] != self.vectors['text'].shape[1] or not np.isfinite(q).all() or np.linalg.norm(q) == 0:
                raise ValueError('query_vector must be a finite nonzero vector matching the index dimension')
            q = q / np.linalg.norm(q)
            body = self.vectors['text']@q
            title = self.vectors['title']@q
            if mode in ['dense','flat_hybrid']:candidates=allowed; dense_scores=body
            elif mode == 'title_dense':candidates=allowed; dense_scores=title
            elif mode == 'weighted':candidates=allowed; dense_scores=.8*body+.2*title
            else:
                candidates=[i for i in allowed if title[i]>=title_threshold]
                # No silent all-corpus fallback: keep top chapters if the threshold yields none.
                if not candidates:
                    top_parents={self.children[i]['parent_id'] for i in sorted(allowed,key=lambda i:-title[i])[:5]}
                    candidates=[i for i in allowed if self.children[i]['parent_id'] in top_parents]
                dense_scores=body
            dense_rank=sorted(candidates,key=lambda i:-dense_scores[i])[:60]
            if mode in ['hybrid','flat_hybrid']:ranking,scores=rrf([sparse,dense_rank])
            else:ranking=dense_rank;scores={i:float(dense_scores[i]) for i in ranking}
        results=[];seen=set()
        for i in ranking:
            c=self.children[i];d=self.docs[c['doc_id']]
            if deduplicate_parents and c['parent_id'] in seen:continue
            seen.add(c['parent_id'])
            results.append({**c,'score':float(scores[i]),'parent_text':self.parents[c['parent_id']]['text'],
                            'source_url':d['url'],'document_title':d['title'],'source_sha256':d['sha256'],
                            'effective_from':d.get('effective_from'),'status':d.get('status')})
            if len(results)>=k:break
        return results

def retrieval_metrics(queries, index, mode):
    """Evaluate provided gold document/parent IDs; do not infer labels from retrieval output."""
    values=[]
    for q in queries:
        hits=index.search(q['query'], k=5, mode=mode)
        gold=set(q['gold_ids'])
        rank=next((i for i,h in enumerate(hits,1) if {h['id'],h['parent_id'],h['doc_id']}&gold),None)
        values.append({'query':q['query'],'rank':rank})
    n=max(len(values),1)
    return {'n':len(values),'mode':mode,**{f'top{k}':sum(v['rank'] is not None and v['rank']<=k for v in values)/n for k in [1,3,5]},
            'mrr':sum(1/v['rank'] if v['rank'] else 0 for v in values)/n,'results':values}
