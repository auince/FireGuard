"""Stable article/paragraph/table provenance, independent of legacy vector positions."""
import re
from .store import digest

ARTICLE=re.compile(r'(?m)^\s*(第[一二三四五六七八九十百零〇\d]+条|\d+\.\d+\.\d+)(?=\s|[^\d.])')
def source_units(text,version):
    matches=list(ARTICLE.finditer(text));starts=[0]+[m.start() for m in matches if m.start()>0]+[len(text)]
    starts=sorted(set(starts));out=[]
    for left,right in zip(starts,starts[1:]):
        body=text[left:right];m=ARTICLE.match(body);article=m.group(1) if m else ''
        parent=digest([version,'article',article,body])
        out.append({'unit_id':parent,'unit_type':'article' if article else 'preamble','article':article,'text':body,'char_start':left,'char_end':right})
        # Preserve Markdown/tabular blocks as a whole; plain PDF text remains an unverified layout.
        cursor=left
        for block in re.finditer(r'[^\n]+(?:\n(?!\s*\n)[^\n]+)*',body):
            raw=block.group();is_table=('|' in raw or '\t' in raw) and len(raw.splitlines())>1
            unit={'unit_id':digest([version,article,'table' if is_table else 'paragraph',raw]),'parent_unit_id':parent,
             'unit_type':'table' if is_table else 'paragraph','article':article,'text':raw,
             'char_start':left+block.start(),'char_end':left+block.end(),'layout_verified':False if is_table else None}
            out.append(unit)
    return out

def materialize_structure(store,sid):
    counts={'documents':0,'units':0,'mapped_fragments':0,'unmapped_fragments':0}
    for doc in store.db.documents.find({'snapshot_id':sid}):
        text=doc['full_text'];units=source_units(text,doc['version_id']);counts['documents']+=1
        for u in units:
            store.db.source_units.update_one({'_id':sid+':'+u['unit_id']},{'$setOnInsert':{**u,'doc_id':doc['doc_id'],'snapshot_id':sid,'body_hash':doc['body_hash']}},upsert=True)
        counts['units']+=len(units)
        positions=[i for i,c in enumerate(text) if not c.isspace()];compact=''.join(text[i] for i in positions)
        for e in store.db.evidence.find({'snapshot_id':sid,'doc_id':doc['doc_id']}):
            quote=''.join(c for c in e['text'] if not c.isspace());start=compact.find(quote)
            if start<0 or not quote:counts['unmapped_fragments']+=1;continue
            left,right=positions[start],positions[start+len(quote)-1]+1
            linked=[u['unit_id'] for u in units if u['unit_type'] in ['article','preamble'] and u['char_start']<right and u['char_end']>left]
            location={'article':e.get('article',''),'char_start':left,'char_end':right,'coordinate_system':'canonical_markdown_unicode',
                      'normalization':'whitespace_only','source_unit_ids':linked}
            store.db.evidence_locations.update_one({'_id':sid+':'+e['evidence_id']},{'$setOnInsert':{
              'snapshot_id':sid,'evidence_id':e['evidence_id'],'body_hash':doc['body_hash'],'location':location}},upsert=True)
            counts['mapped_fragments']+=1
    return counts
