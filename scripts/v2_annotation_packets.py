import json,re,collections,math,hashlib
from pathlib import Path
from xfagent.v2.store import Store
from xfagent.v2.facts import eligible
from xfagent.v2.structure import materialize_structure
from xfagent.retrieval import tokens
s=Store();p=Path('runtime/v2/legal-candidates');sid=json.loads((p/'prepared.json').read_text())['snapshot_id'];materialize_structure(s,sid)
docs={d['doc_id']:d for d in s.db.documents.find({'snapshot_id':sid})};ev=list(s.db.evidence.find({'snapshot_id':sid}));cases=list(map(json.loads,Path('benchmarks/inspection_scenarios/v2/cases.jsonl').read_text().splitlines()));families=collections.defaultdict(list)
for c in cases:families[c['family_id']].append(c)
units=collections.defaultdict(list)
for e in ev:units[(e['doc_id'],e.get('article') or e['evidence_id'])].append(e)
sections=[]
for key,es in units.items():
 es.sort(key=lambda e:int(e['legacy_id'].split(':c')[-1]));d=docs[key[0]]
 sections.append({'doc':d,'article':es[0].get('article',''),'es':es,'text':'\n'.join(e['text'] for e in es)})
out=Path('reports/v2/astra-annotation');(out/'packets').mkdir(parents=True,exist_ok=True)
for fid,cs in families.items():
 terms=collections.Counter(tokens(' '.join(c['input']['query'] for c in cs)));rank=[]
 for sec in sections:
  d=sec['doc'];text=sec['text'];valid=any(eligible(d,c['input']['as_of'],c['input']['jurisdiction']) for c in cs)
  if not valid:continue
  tf=collections.Counter(tokens(text));score=sum(min(tf[t],3)*min(n,2) for t,n in terms.items())/max(1,len(text))**.45
  essential=(d['doc_id']=='9cffdd8a46a056cc' and sec['article'].startswith(('1.','2.','3.','10.'))) or ('消防法（2021' in d['title'] and sec['article'] in ['第二条','第十六条','第十八条','第二十八条','第六十条'])
  if essential:score+=1000
  rank.append((score,sec))
 rank.sort(key=lambda x:-x[0]);chosen=[];chars=0
 for score,sec in rank[:85]:
  if chars+len(sec['text'])>65000:continue
  chosen.append(sec);chars+=len(sec['text'])
 chosen.sort(key=lambda x:(x['doc']['title'],x['es'][0]['legacy_id']))
 context=[];alias={};idx=0
 for sec in chosen:
  d=sec['doc'];sn=[]
  for e in sec['es']:
   idx+=1;k=f'E{idx:03d}';alias[k]={'evidence_id':e['evidence_id'],'doc_id':e['doc_id'],'article':e.get('article'),'text':e['text'],'source_hash':e['source_hash'],'location':e.get('location'),'version_id':e['version_id'],'source_url':d['url'],'title':d['title'],'effective_from':d.get('effective_from'),'effective_until':d.get('effective_until'),'jurisdiction':d.get('jurisdiction'),'conditions':d.get('conditions',{})};sn.append({'id':k,'text':e['text']})
  context.append({'document':d['title'],'version':d['version_id'],'valid_from':d.get('effective_from'),'valid_until_exclusive':d.get('effective_until'),'jurisdiction':d.get('jurisdiction'),'conditions':d.get('conditions',{}),'article':sec['article'],'source_url':d['url'],'fragments':sn})
 safe=[]
 for c in cs:
  # Hide path names and previous model outputs / authored expectations to avoid label leakage.
  safe.append({'case_id':c['id'],'facility':c['facility'],'input':{k:v for k,v in c['input'].items() if k in ['query','facility','jurisdiction','as_of','scene','mode']},'image_sha256':c.get('image_sha256'),'image_present':bool(c.get('image_path'))})
 packet={'family_id':fid,'split':cs[0]['split'],'snapshot_id':sid,'cases':safe,'legal_context':context,'evidence_aliases':alias,'context_selection':{'method':'independent_broad_lexical_plus_core_articles_and_sibling_fragments','production_outputs_used':False,'section_count':len(chosen),'fragment_count':len(alias),'characters':chars,'not_exhaustive':True}}
 (out/'packets'/f'{fid}.json').write_text(json.dumps(packet,ensure_ascii=False,indent=2))
print(json.dumps({'snapshot_id':sid,'families':len(families),'documents':len(docs),'evidence':len(ev)},ensure_ascii=False))
