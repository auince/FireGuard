"""Explicit synthetic model injection, real durable workflow and isolated database.

For local UI acceptance only; never run this entry point for production.
"""
import hashlib
import os
import secrets
import threading
from pathlib import Path

root=Path(__file__).resolve().parents[1]
os.environ['XF_HARNESS_VERSION']='8'
os.environ['XFAGENT_ROOT']=str(root)
os.environ['XF_V2_DB']='xfagent_console_fixture'
os.environ['XF_V2_REDIS']='redis://127.0.0.1:6379/3'
os.environ['XF_INFERENCE_MODE']='injected_fixture'
os.environ['XF_MODEL_NAME']='injected-ui-fixture-not-real-9b'
os.environ['XF_COOKIE_SECURE']='false'
os.environ['XF_COOKIE_NAME']='xf_fixture_session'
os.environ.setdefault('XF_V2_JWT_SECRET',secrets.token_hex(32))
from xfagent.v2 import graphs
from xfagent.v2 import feedback
from xfagent.v2.store import Store,digest
from xfagent.v2.policy import Policies
from xfagent.evidence_vision import VisionEvidence

store=Store();store.setup();Policies(store).seed()
sid='synthetic-console-fixture'
store.db.settings.update_one({'_id':'active_snapshot'},{'$set':{'value':sid}},upsert=True)
text='UI 仿真条款（非法律依据）：消防设施前方保持畅通，便于取用。'
store.db.documents.update_one({'_id':'fixture-doc'},{'$set':{'doc_id':'fixture-doc','snapshot_id':sid,'title':'仿真条款（非法律依据）','full_text':text,'body_hash':digest(text.encode()),'sha256':'fixture','ready':True,'status':'source_verified','kind':'law','jurisdiction':'全国','effective_from':'2020-01-01','url':'','conditions':{}}},upsert=True)
store.db.evidence.update_one({'_id':'fixture-e'},{'$set':{'evidence_id':'fixture-e','legacy_id':'fixture-e','snapshot_id':sid,'doc_id':'fixture-doc','text':text,'quote_hash':digest(text.encode()),'source_hash':'fixture'}},upsert=True)
for role in ['inspector','reviewer','admin']:
    salt=secrets.token_bytes(16)
    store.db.users.update_one({'_id':role},{'$setOnInsert':{'salt':salt.hex(),'password_hash':hashlib.scrypt(b'ui-fixture-only',salt=salt,n=16384,r=8,p=1).hex(),'role':role,'projects':['default']}},upsert=True)
def search(self,queries,snapshot,as_of,jurisdiction,**kwargs):
    from xfagent.v2.facts import fetch_evidence
    return {'evidence':[fetch_evidence(store,sid,'fixture-e',as_of,jurisdiction)],'queries':queries,'warnings':['synthetic_fixture']}
def model(state,instruction,payload,image=None,role='answer'):
    state['calls']=state.get('calls',0)+1
    if role=='intent':return {'facility':'indoor_hydrant'}
    if role=='rewrite':return {'queries':['消火栓取用空间']}
    if role=='verify':return {'supported':True,'issues':[]}
    if role=='vision':
        if 'corrections' in instruction:return {'corrections':[]}
        return {'observations':[{'status':'uncertain','description':'仿真观察：照片中目标周边空间需现场核实。','detector_id':'d1','labels':['待核实']}]}
    if role=='adapt':return {'trigger_terms':['消火栓'],'expand_terms':['消火栓','取用空间'],'parent_expand':False}
    if role=='reflect':return {'category':'retrieval','expand_terms':['消火栓','取用空间'],'reason':'synthetic_fixture'}
    return {'conclusions':[{'claim_id':'c1','text':'仿真结论：请现场确认消火栓前是否存在遮挡。','recommendation':'核实后清理影响取用的物品。','kind':'information_request','observation_ids':[],'evidence_ids':[],'missing_fields':[]}]}
def vision(self,request,facility,deadline=None):
    return {'detector':{'enabled':True,'status':'completed','model_scope':'synthetic_fixture','detections':[{'detector_id':'d1','label':'仿真目标框','confidence':.91,'bboxNorm':[.2,.15,.8,.85]}]},'similar_cases':[{'case_id':'fixture-case','description':'仿真历史案例：清理遮挡物后复查取用空间。','authority':'historical_case_not_current_fact','review_status':'synthetic_fixture','usable_as_legal_evidence':False}],'warnings':['synthetic_fixture']}
graphs.Retrieval.search=search;graphs.complete=model;feedback.complete=model;VisionEvidence.analyze=vision
from xfagent.v2.worker import main
threading.Thread(target=main,daemon=True).start()
from xfagent.server.app import create_app
import uvicorn
uvicorn.run(create_app(store),host='127.0.0.1',port=8081)
