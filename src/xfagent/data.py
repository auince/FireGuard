"""Image-hash deduplication, frozen-test exclusion and reviewed-data export."""
import hashlib,json,random,sqlite3,time,uuid
from pathlib import Path
from PIL import Image
from .config import ROOT,directory,write_json

def image_hash(path):
    h=hashlib.sha256()
    with open(path,'rb') as f:
        for block in iter(lambda:f.read(1024*1024),b''):h.update(block)
    return h.hexdigest()

def rows(path):
    with open(path) as f:
        for line in f:
            if line.strip():yield json.loads(line)

def text_of(row,role):
    for msg in row.get('messages',[]):
        if msg['role']==role:
            c=msg['content']
            return c if isinstance(c,str) else '\n'.join(x.get('text','') for x in c if x.get('type')=='text')
    return ''

def curate(source,frozen,output,seed=20261002,val_ratio=.1):
    if not 0<val_ratio<1:raise ValueError('val_ratio must be between 0 and 1')
    output=Path(output);output.mkdir(parents=True,exist_ok=True)
    cache={}
    def digest(p):
        if p not in cache:cache[p]=image_hash(p)
        return cache[p]
    frozen_hashes={digest(r['images'][0]) for r in rows(frozen)}
    unique={};conflicts=set();rejected=[]
    for r in rows(source):
        try:
            p=r['images'][0]
            with Image.open(p) as im:im.verify()
            h=digest(p)
            if h in frozen_hashes:
                rejected.append({'id':r.get('id'),'reason':'frozen_overlap'});continue
            if h in unique:
                if text_of(unique[h],'assistant')!=text_of(r,'assistant'):conflicts.add(h)
                else:rejected.append({'id':r.get('id'),'reason':'duplicate'})
                continue
            unique[h]={**r,'image_sha256':h}
        except (OSError,KeyError,ValueError) as e:rejected.append({'id':r.get('id'),'reason':type(e).__name__})
    clean=[r for h,r in unique.items() if h not in conflicts]
    random.Random(seed).shuffle(clean)
    split=max(1,round(len(clean)*val_ratio))
    val,train=clean[:split],clean[split:]
    for name,data in [('train',train),('validation',val)]:
        (output/f'{name}.jsonl').write_text(''.join(json.dumps(x,ensure_ascii=False)+'\n' for x in data))
    audit={'source':str(source),'frozen':str(frozen),'seed':seed,'train':len(train),'validation':len(val),
           'frozen_unique_images':len(frozen_hashes),'conflicting_images':len(conflicts),'excluded':rejected,
           'train_validation_overlap':len({r['image_sha256'] for r in train}&{r['image_sha256'] for r in val}),
           'frozen_overlap':len({r['image_sha256'] for r in clean}&frozen_hashes)}
    write_json(output/'audit.json',audit)
    return {k:v for k,v in audit.items() if k!='excluded'}

class Store:
    def __init__(self,path=None):
        self.path=str(path or directory('runtime')/'app.sqlite')
        with self.connect() as db:
            db.execute('CREATE TABLE IF NOT EXISTS records (id TEXT, kind TEXT, payload TEXT, created REAL, PRIMARY KEY(id,kind))')
    def connect(self):
        db=sqlite3.connect(self.path);db.execute('PRAGMA journal_mode=WAL');return db
    def put(self,kind,payload,identifier=None):
        identifier=identifier or str(uuid.uuid4())
        with self.connect() as db:db.execute('INSERT OR REPLACE INTO records VALUES (?,?,?,?)',(identifier,kind,json.dumps(payload,ensure_ascii=False),time.time()))
        return identifier
    def get(self,identifier,kind='job'):
        with self.connect() as db:r=db.execute('SELECT id,kind,payload,created FROM records WHERE id=? AND kind=?',(identifier,kind)).fetchone()
        return dict(id=r[0],kind=r[1],payload=json.loads(r[2]),created=r[3]) if r else None
    def list(self,kind,limit=100):
        with self.connect() as db:r=db.execute('SELECT id,payload,created FROM records WHERE kind=? ORDER BY created DESC LIMIT ?',(kind,limit)).fetchall()
        return [dict(id=x[0],payload=json.loads(x[1]),created=x[2]) for x in r]

def export_reviewed(store,output,frozen_hashes):
    approved=[]
    for r in store.list('annotation',100000):
        p=r['payload'];a=p.get('approved') or {}
        if not a.get('accepted') or not a.get('reviewer') or p.get('image_sha256') in frozen_hashes:continue
        answer='检查范围：'+a.get('scope','无法确定')+'\n结论：'+a.get('verdict','无法判断')+'\n隐患标签：'+('；'.join(a.get('labels',[])) or '无')+'\n可见证据：'+a.get('evidence','')
        approved.append({'id':r['id'],'images':[p['image_path']],'image_sha256':p['image_sha256'],
                         'messages':[{'role':'user','content':p['prompt']},{'role':'assistant','content':answer}],
                         'meta':{'reviewer':a['reviewer'],'provenance':'human_approved','synthetic':p.get('synthetic',False)}})
    Path(output).write_text(''.join(json.dumps(x,ensure_ascii=False)+'\n' for x in approved))
    return {'exported':len(approved),'output':str(output)}
