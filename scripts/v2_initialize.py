"""Initialize a fresh local deployment; never reset existing users or secrets."""
import hashlib,json,os,secrets
from xfagent.v2.config import ROOT,now
from xfagent.v2.store import Store

def private_create(path,text):
    try:
        fd=os.open(path,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600)
    except FileExistsError:return False
    with os.fdopen(fd,'w') as f:f.write(text)
    return True

def main():
    folder=ROOT/'runtime/v2';folder.mkdir(parents=True,exist_ok=True)
    env=folder/'service.env'
    private_create(env,'XF_V2_JWT_SECRET='+secrets.token_urlsafe(48)+'\nXF_MODEL_URL=http://127.0.0.1:8000/v1\n')
    store=Store();store.setup();path=folder/'credentials.json'
    if not path.exists():
        existing=store.db.users.count_documents({'_id':{'$in':['admin','reviewer','inspector']}})
        if existing:raise RuntimeError('已有账号但初始凭据文件不存在；保留已有账号，请管理员使用既有凭据。')
        accounts=[{'username':role,'password':secrets.token_urlsafe(24)} for role in ['admin','reviewer','inspector']]
        private_create(path,json.dumps(accounts,ensure_ascii=False,indent=2)+'\n')
    accounts=json.loads(path.read_text())
    for a in accounts:
        username=a['username']
        if username not in ['admin','reviewer','inspector']:continue
        salt=secrets.token_hex(16)
        hashed=hashlib.scrypt(a['password'].encode(),salt=bytes.fromhex(salt),n=16384,r=8,p=1).hex()
        store.db.users.update_one({'_id':username},{'$setOnInsert':{'role':username,'projects':['default'],
            'salt':salt,'password_hash':hashed,'created_at':now()}},upsert=True)
    for file in [env,path]:os.chmod(file,0o600)
    print('初始化完成；已有账号与密钥保持不变。凭据位于 runtime/v2/credentials.json（600），不会输出到日志。')

if __name__=='__main__':main()
