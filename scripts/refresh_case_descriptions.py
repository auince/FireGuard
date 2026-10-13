import json,sys
from pathlib import Path
import numpy as np
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'src'))
from xfagent.cases import encode_cases
from xfagent.data import rows,text_of
from xfagent.config import read_json,write_json
folder=ROOT/'data/cases';records=read_json(folder/'records.json');vectors=np.load(folder/'description.npy');generated={r['id']:r for r in rows(folder/'domain_description_smoke.jsonl')};updated=[]
for i,r in enumerate(records):
 if r['id'] not in generated:continue
 g=generated[r['id']];r.update(description=text_of(g,'assistant'),description_source=g['description_model'],human_reviewed=False);vectors[i]=encode_cases([r['description']],'text')[0];updated.append(r['id'])
np.save(folder/'description.npy',vectors);write_json(folder/'records.json',records);write_json(folder/'description_update.json',{'updated_ids':updated,'not_training_labels':True});print({'updated':len(updated)})
