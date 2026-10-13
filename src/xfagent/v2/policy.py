import json,uuid
import numpy as np
from .config import now
from .store import digest
from .schema import Strategy
from .model_routes import manifest

SEEDS=[
 {'name':'消防术语扩展','trigger_terms':['消防箱','水枪头','消防栓'],'expand_terms':['消火栓','消防水枪','消防水带']},
 {'name':'同章多条款补取','trigger_terms':['同时','多个','依据','责任'],'parent_expand':True,'evidence_k':8},
 {'name':'补充现场测量','trigger_terms':['宽度','压力','数量','高度'],'template':'measurement_required'},
 {'name':'版本冲突提示','trigger_terms':['旧版','历史','修订','生效'],'template':'version_conflict'},
]

class Policies:
    def __init__(self,store):self.store=store

    def seed(self):
        self.store.db.policies.update_one({'_id':'baseline-v2'},{'$setOnInsert':{
            'state':'active','project_id':'default','spec':Strategy(name='基础策略').model_dump(),
            'version':1,'created_at':now()}},upsert=True)
        for i,s in enumerate(SEEDS):
            self.store.db.policies.update_one({'_id':f'seed-{i+1}'},{'$setOnInsert':{
                'state':'draft','project_id':'default','spec':Strategy(**s).model_dump(),'version':1,'created_at':now()}},upsert=True)

    def choose(self,owner,project,session,query,facility,forced=None):
        baseline=self.store.db.policies.find_one({'_id':'baseline-v2'})
        if forced:
            p=self.store.db.policies.find_one({'_id':forced,'project_id':project})
            if not p:raise ValueError('策略不存在')
            return {'policy_id':p['_id'],'spec':p['spec'],'group':'replay','experiment_id':None,'triggered':self.matches(p,query,facility)}
        sid=digest([owner,project,session])
        pinned=self.store.db.session_policies.find_one({'_id':sid})
        if pinned:
            p=self.store.db.policies.find_one({'_id':pinned['policy_id']})
            if p and p['state'] not in ['rolled_back','deprecated']:
                return {k:v for k,v in pinned.items() if k!='_id'}|{'triggered':pinned.get('group')=='treatment' and self.matches(p,query,facility)}
            # Emergency rollback supersedes session pinning; normal expansion never does.
            self.store.db.session_policies.delete_one({'_id':sid})
        chosen={'policy_id':'baseline-v2','spec':baseline['spec'],'group':'control','experiment_id':None,'triggered':False}
        for p in self.store.db.policies.find({'state':{'$in':['canary','active']},'project_id':project,'_id':{'$ne':'baseline-v2'}}).sort('approved_at',-1):
            if not self.matches(p,query,facility):continue
            bucket=int(digest([owner,p['_id']])[:8],16)%100
            treatment=bucket<p.get('percentage',0)
            chosen={'policy_id':p['_id'] if treatment else 'baseline-v2','spec':p['spec'] if treatment else baseline['spec'],
                'group':'treatment' if treatment else 'control','experiment_id':p['_id'],'triggered':treatment}
            break
        self.store.db.session_policies.update_one({'_id':sid},{'$setOnInsert':chosen},upsert=True)
        return chosen

    @staticmethod
    def matches(p,query,facility):
        s=p['spec']
        return (not s['facilities'] or facility in s['facilities']) and (not s['trigger_terms'] or any(t in query for t in s['trigger_terms']))

    def candidate(self,spec,project,owner):
        spec=Strategy.model_validate(spec).model_dump();identifier=uuid.uuid4().hex
        self.store.db.policies.insert_one({'_id':identifier,'spec':spec,'state':'draft','project_id':project,
            'owner':owner,'version':1,'created_at':now()})
        return identifier

    def publish(self,identifier,actor,percentage,expected_revision):
        import os
        if os.getenv('XF_INFERENCE_MODE')=='injected_fixture':raise ValueError('仿真环境禁止策略发布；请在真实推理环境完成回放')
        from .replay_protocol import PROTOCOL,execution_hash
        if percentage not in [5,20,50,100]:raise ValueError('invalid rollout percentage')
        p=self.store.db.policies.find_one({'_id':identifier})
        if not p or p['project_id'] not in actor.projects:raise ValueError('策略不存在')
        if p['state'] in ['rolled_back','deprecated']:raise ValueError('回滚版本必须创建新候选')
        if p['spec']['kind']=='rule' and (not p.get('rule_reviewed') or p.get('rule_review_hash')!=digest(p['spec'])):raise ValueError('Rule 需要管理员先审核内容')
        fingerprint=(self.store.db.settings.find_one({'_id':'generator_fingerprint'}) or {}).get('value')
        report=self.store.db.evaluations.find_one({'policy_id':identifier,'policy_hash':digest(p['spec']),'status':'passed',
            'protocol':PROTOCOL,'execution_hash':execution_hash(),'model_routes_hash':digest(manifest()),'model_fingerprint':fingerprint},sort=[('created_at',-1)])
        if not report:raise ValueError('缺少同版本通过的回放评测')
        previous=p.get('percentage',0)
        next_step={0:5,5:20,20:50,50:100}
        if next_step.get(previous)!=percentage:raise ValueError('必须逐档发布')
        if previous:
            stats=self.statistics(identifier)
            if min(stats['control']['n'],stats['treatment']['n'])<100:raise ValueError('每组不足100例，保持当前灰度档位')
            if stats['regressed']:raise ValueError('指标退化，禁止扩量')
        changed=self.store.db.policies.update_one({'_id':identifier,'version':expected_revision},
            {'$set':{'state':'active' if percentage==100 else 'canary','percentage':percentage,'approved_by':actor.user_id,
                     'approved_at':now(),'evaluation_id':report['_id']},'$inc':{'version':1}})
        if not changed.modified_count:raise ValueError('策略版本已变化')
        self.store.audit(identifier,'publish:'+str(expected_revision),'policy_published',actor=actor.user_id,percentage=percentage)

    def rollback(self,identifier,reason,actor='monitor'):
        self.store.db.policies.update_one({'_id':identifier,'state':{'$in':['active','canary']}},
            {'$set':{'state':'rolled_back','rollback_reason':reason,'rolled_back_at':now(),'rolled_back_by':actor},'$inc':{'version':1}})
        self.store.audit(identifier,'rollback','policy_rolled_back',reason=reason,actor=actor)

    def incident(self,run,code,reason,actor):
        if code not in ['forged_citation','unauthorized','invalid_finalization']:raise ValueError('严重事件类型无效')
        identifier=digest([run['_id'],code,reason])
        policy=run.get('result',{}).get('policy',{});experiment=policy.get('experiment_id')
        self.store.db.incidents.update_one({'_id':identifier},{'$setOnInsert':{
            'run_id':run['_id'],'project_id':run['project_id'],'code':code,'reason':reason,
            'confirmed_by':actor,'experiment_id':experiment,'created_at':now()}},upsert=True)
        if experiment and policy.get('group')=='treatment':self.rollback(experiment,code+':'+reason,actor)
        return identifier

    def monitor(self,identifier):
        if identifier and self.statistics(identifier)['regressed']:self.rollback(identifier,'metrics_regressed')

    def statistics(self,identifier):
        output={}
        for group in ['control','treatment']:
            rows=list(self.store.db.treatments.find({'experiment_id':identifier,'group':group,'completed':True}))
            output[group]={'n':len(rows),'error_rate':sum(bool(r.get('error')) for r in rows)/max(1,len(rows)),
                'p95':float(np.percentile([r['elapsed'] for r in rows],95)) if rows else 0}
        a,b=output['control'],output['treatment']
        output['regressed']=min(a['n'],b['n'])>=100 and (b['error_rate']>a['error_rate']+.02 or b['p95']>a['p95']*1.2)
        return output

    def record(self,state):
        policy=state['policy'];experiment=policy.get('experiment_id')
        if not experiment:return
        errors=state.get('verification',{}).get('errors',[])
        self.store.db.treatments.update_one({'_id':state['run_id']},{'$setOnInsert':{
            'experiment_id':experiment,'group':policy['group'],'policy_id':policy['policy_id'],
            'completed':False,'elapsed':state.get('active_seconds',0),'error':bool(errors),
            'queries':state.get('queries',[]),'evidence_ids':[e['evidence_id'] for e in state.get('evidence',[])],
            'triggered':policy['triggered'],'template':policy['spec']['template'],'created_at':now()}},upsert=True)
        severe=any(e.get('code') in ['forged_citation','source_mismatch','unauthorized','invalid_finalization'] for e in errors)
        if severe and policy['group']=='treatment':self.rollback(experiment,'critical_verification_failure')
        elif self.statistics(experiment)['regressed']:self.rollback(experiment,'metrics_regressed')
