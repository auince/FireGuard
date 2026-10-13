"""Build an immutable coverage suite; do not change production code or gold."""
import argparse
import copy
import hashlib
import json
import re
import shutil
from collections import Counter, defaultdict
from pathlib import Path

VERSION = 'xfagent-coverage-v1'

REQUIREMENTS = {
 'VIS-01': '三类设施可见异常与正常项', 'VIS-02': '不可见、模糊与不确定性',
 'VIS-03': '单隐患、多隐患与标签标准化', 'INT-01': '设施识别与路由',
 'INT-02': '同设施追问与设施切换', 'RAG-01': '片段级检索召回与全部证据覆盖',
 'RAG-02': '日期、地域、来源与版本过滤', 'RAG-03': '检索降级与父条款上下文',
 'VER-01': '引用存在性及原文逐字段一致性', 'VER-02': '适用性与证据充分性',
 'VER-03': '未测量事实与未知观察保护', 'VER-04': '人工修改后支持性重新核验',
 'HAR-01': '模型调用、时间、查询及重写预算', 'HAR-02': '核验失败的有界定向回退',
 'HAR-03': '服务失败显式降级', 'HAR-04': '重启、租约与检查点恢复',
 'HIT-01': '审批、退回、驳回及持久中断', 'HIT-02': '修订号及重复审核幂等',
 'SEC-01': '角色、所有权与项目权限', 'MEM-01': '记忆隔离、过期及同意',
 'FDB-01': '反馈归因与候选策略边界', 'POL-01': '真实配对回放及发布拒绝',
 'POL-02': '稳定灰度、扩量及严重事件回滚', 'OBS-01': '调用、降级及轨迹统计',
 'OPS-01': '快照发布与版本切换', 'OPS-02': '派发对账与重复消息',
 'OPS-03': '备份、隔离恢复及恢复后核对', 'PER-01': '持续并发、排队及容量',
}

def sha(path): return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def read_rows(path): return [json.loads(x) for x in Path(path).read_text().splitlines() if x.strip()]
def dump(path, value): Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2)+'\n')
def jsonl(path, rows): Path(path).write_text(''.join(json.dumps(r, ensure_ascii=False)+'\n' for r in rows))
def label(text): return re.sub(r'[。；;\s]+$', '', text.strip())

def contracts():
 rows=[]
 def add(family, name, reqs, operation, params, expected):
  rows.append({'id':'CON-'+name, 'family_id':'CON-'+family, 'split':'contract',
    'suite':'contract', 'requirements':reqs, 'input':{}, 'assets':{},
    'operation':operation, 'params':params, 'expected':expected,
    'oracle_kind':'authored_engineering_invariant',
    'source':{'origin':'new_requirement_case','fixture_authority':'synthetic_not_legal_evidence'},
    'execution':{'mode':'isolated_cpu','status':'not_run'}})
 for name, changes, ok in [
  ('valid',{},True),('before_start',{'as_of':'2024-10-31'},False),
  ('at_start',{'as_of':'2024-11-01'},True),('before_end',{'as_of':'2026-10-04'},True),
  ('at_end',{'as_of':'2026-10-05'},False),('after_end',{'as_of':'2026-10-06'},False),
  ('wrong_region',{'jurisdiction':'全国'},False),('national',{'doc_jurisdiction':'全国','jurisdiction':'四川'},True),
  ('unverified',{'status':'ocr_pending'},False),('not_ready',{'ready':False},False),
  ('announcement',{'kind':'notice'},False),('unbounded',{'effective_from':None,'effective_until':None},True)]:
  add('temporal', 'temporal-'+name,['RAG-02'],'temporal',changes,{'eligible':ok})
 for name, p, code in [
  ('valid',{},None),('forged',{'citation':'unknown'},'forged_citation'),
  ('no_citation',{'citation':None},'missing_evidence'),('unknown_observation',{'observation':'old-o1'},'unknown_observation'),
  ('no_observation',{'observation':None},'missing_observation'),('empty_text',{'text':''},'empty_claim_text'),
  ('duplicate_id',{'duplicate':True},'duplicate_or_empty_claim_id'),
  ('unknown_condition',{'condition':True},'unknown_applicability'),
  ('wrong_condition',{'condition':True,'scene':{'highrise':False}},'inapplicable_evidence'),
  ('known_condition',{'condition':True,'scene':{'highrise':True}},None),
  ('uncertain_observation',{'observation_status':'uncertain'},'uncertain_observation'),
  ('missing_field',{'missing_fields':['building_height']},'insufficient_claim'),
  ('hidden_legal_observation',{'kind':'observation','text':'根据消防法，该消火栓不符合要求','citation':None},'legal_claim_in_nonlegal_field'),
  ('hidden_legal_request',{'kind':'information_request','text':'根据消防法，该消火栓不符合要求','citation':None},'legal_claim_in_nonlegal_field'),
  ('pressure_standard',{'text':'压力为0.25MPa，不符合要求'},'unmeasured_fact'),
  ('width_standard',{'text':'通道宽度为0.8米，不符合要求'},'unmeasured_fact'),
  ('quantity',{'text':'灭火器数量不足'},'unmeasured_fact'),
  ('pressure_paraphrase',{'text':'水压只有0.25MPa，判定为不合格。'},'unmeasured_fact'),
  ('width_paraphrase',{'text':'通道净宽0.8米，判定为不合格。'},'unmeasured_fact')]:
  req=['VER-01']
  if 'condition' in name or name=='missing_field':req=['VER-02']
  if 'pressure' in name or 'width' in name or name in ['quantity','uncertain_observation']:req=['VER-03']
  add('verification', 'verify-'+name, req,'verify',p,{'passed':code is None,'error_code':code})
 for field in ['text','quote_hash','source_hash','version_id','doc_id','snapshot_id','source_url','conditions','location']:
  add('citation-fields','tamper-'+field,['VER-01'],'verify',{'tamper_field':field}, {'passed':False,'error_code':'source_mismatch'})
 for name,p,route in [
  ('supported',{'passed':True},'review_ready'),('exhausted',{'exhausted':True},'review_ready'),
  ('missing-first',{'code':'missing_evidence'},'rewrite'),('source-first',{'code':'source_mismatch'},'rewrite'),
  ('retrieval-exhausted',{'code':'missing_evidence','retrieval_rounds':2},'repair'),
  ('all-exhausted',{'code':'missing_evidence','retrieval_rounds':2,'rewrites':2},'review_ready'),
  ('unknown-condition',{'code':'unknown_applicability'},'review_ready'),
  ('unmeasured',{'code':'unmeasured_fact'},'review_ready'),('verifier-offline',{'code':'semantic_verification_unavailable'},'review_ready'),
  ('semantic-repair',{'code':'semantic_unsupported'},'repair')]:
  add('routing','route-'+name,['HAR-02'],'route',p,{'route':route})
 for name,p in [('call-limit',{'calls':16}),('time-limit',{'active_seconds':300}),
                ('time-over',{'active_seconds':301}),('context-over',{'context_over':True})]:
  add('budgets','budget-'+name,['HAR-01'],'budget',p,{'blocked':True,'model_http_calls':0})
 add('restart-budget','budget-after-interrupted-call',['HAR-01','HAR-04'],'restart_budget',{},
     {'total_external_calls_with_prior_15_at_most':16,'fixture':'resume last saved node input after model received request but node never checkpointed'})
 for name,mut,expected in [
  ('valid','none',True),('regression','regression',False),('aggregate-hidden','aggregate_hidden',False),
  ('critical-citation','citation',False),('latency','latency',False),('no-trigger','no_trigger',False),
  ('execution-failed','execution',False),('no-draft','no_draft',False),('too-few','too_few',False)]:
  add('policy-gates','policy-'+name,['POL-01'],'pair',{'mutation':mut},{'passed':expected})
 for name,spec in [
  ('skip-verifier',{'skip_verifier':True}),('unbounded-k',{'evidence_k':999}),
  ('code-injection',{'code':'import os'}),('bad-hook',{'kind':'hook','hook':'none'}),
  ('hook-retrieval',{'kind':'hook','hook':'before_draft','expand_terms':['压力']}),
  ('rule-without-condition',{'kind':'rule'})]:
  add('strategy-boundary','strategy-'+name,['FDB-01'],'strategy',spec,{'rejected':True})
 for name,p,allowed in [
  ('owner-read',{'role':'inspector'},True),('other-read',{'role':'inspector','owner':'b'},False),
  ('inspector-write',{'role':'inspector','write':True},False),('reviewer-write',{'role':'reviewer','write':True},True),
  ('other-project',{'role':'admin','project':'other'},False),('admin-write',{'role':'admin','write':True},True)]:
  add('access','access-'+name,['SEC-01'], 'access',p,{'allowed':allowed})
 for facility,chinese in [('indoor_hydrant','室内消火栓'),('outdoor_hydrant','室外消火栓'),('fire_extinguisher','灭火器')]:
  for source in ['keyword','model']:
   add('facility-routing','intent-'+facility+'-'+source,['INT-01'],'intent',
       {'query':'请核查'+chinese if source=='keyword' else '请确认这个设备是什么','model_facility':facility},
       {'facility':facility,'model_calls':0 if source=='keyword' else 1})
 add('facility-routing','intent-unknown',['INT-01'],'intent',{'query':'请确认这个设备是什么','model_facility':'not_a_registered_facility'},
     {'facility':'unknown','model_calls':1})
 for name,mode in [('embedding','embedding'),('vector','vector'),('reranker','reranker')]:
  add('retrieval-failures','outage-'+name,['RAG-03','HAR-03'],'retrieval_outage',{'service':mode},
      {'evidence_retained':True,'explicit_warning':True})
 add('verifier-failure','verifier-outage',['VER-01','HAR-03'],'verifier_outage',{}, {'passed':False,'semantic_review':'unavailable'})
 for action in ['approve','return','reject']:
  add('human-review','review-'+action,['HIT-01'],'review',{'action':action},{'status':{'approve':'complete','return':'awaiting_information','reject':'complete'}[action]})
 add('human-review','review-confirmed-scene',['HIT-01'],'review',{'action':'return','confirmed_scene':{'highrise':True}}, {'status':'redrafting'})
 add('human-support','review-opposite-meaning',['VER-04'],'review',{'action':'approve','contradiction':True},{'must_not_final':True})
 for op,req in [('lease','HAR-04'),('resume','HAR-04'),('idempotency','HIT-02'),('snapshot','OPS-01'),
                ('weak_feedback','FDB-01'),('memory_consent','MEM-01'),('incident','POL-02'),
                ('session_rollback','POL-02'),('queue_recovery','OPS-02'),('memory_isolation','MEM-01'),
                ('trace','OBS-01'),('model_failure','HAR-03'),('lease_after_node','HAR-04')]:
  add(op,op,[req],op,{}, {'invariant_holds':True})
 return rows

def existing_tests(project):
 """Reference existing tests separately; do not inflate scenario counts."""
 import ast
 mapping={
  'temporal':['RAG-02'],'forged':['VER-01'],'citation':['VER-01'],'metadata':['RAG-02'],
  'applicability':['VER-02'],'unobservable':['VER-03'],'numeric':['VER-03'],
  'ownership':['SEC-01'],'project':['SEC-01'],'lease':['HAR-04'],'worker':['HAR-04'],
  'resume':['HAR-04','HIT-01'],'review':['HIT-01','HIT-02'],'final':['HIT-01'],
  'memory':['MEM-01'],'consent':['MEM-01'],'feedback':['FDB-01'],'hook':['FDB-01'],
  'policy':['POL-01'],'paired':['POL-01'],'replay':['POL-01'],'rollback':['POL-02'],
  'canary':['POL-02'],'incident':['POL-02'],'completed':['POL-02'],'budget':['HAR-01'],
  'failure_routing':['HAR-02'],'service_failure':['HAR-03'],'verifier_exception':['HAR-03'],
  'snapshot':['OPS-01'],'dispatch':['OPS-02'],'trace':['OBS-01'],'observability':['OBS-01'],
  'version':['RAG-02'],'retrieval':['RAG-01'],'batch':['RAG-03'],'hyde':['RAG-03'],
  'multi_query':['INT-02'],'structure':['RAG-03'],'original':['VER-01'],'mapping':['VER-01'],
 }
 out=[]
 for p in sorted((project/'tests/v2').glob('test_*.py')):
  for node in ast.walk(ast.parse(p.read_text())):
   if isinstance(node,ast.FunctionDef) and node.name.startswith('test_'):
    req=sorted({r for word,reqs in mapping.items() if word in node.name for r in reqs})
    if req:out.append({'nodeid':str(p.relative_to(project))+'::'+node.name,'requirements':req,'source_sha256':sha(p),
                     'scope':'existing_test_reference_not_new_case'})
 return out

def build(project, source, out):
 from xfagent.v2.store import Store
 from xfagent.v2.schema import InspectionInput
 from xfagent.legal_benchmark import query_text
 out.mkdir(parents=True,exist_ok=True);(out/'original').mkdir(exist_ok=True)
 shutil.copyfile(source,out/'original/xfagent_test_scenarios_200.jsonl')
 source_sha=sha(source);original=read_rows(source)
 grouped=defaultdict(list);labels={};provenance=[]
 for row in original:
  raw=Path(row['input']['image_path']);content=raw.read_bytes();h=hashlib.sha256(content).hexdigest()
  assert hashlib.sha1(content).hexdigest()==row['metadata']['image_sha1']
  grouped[h].append(row)
  for t in row['expected_output']['labels']:
   text=label(t);key=hashlib.sha256(text.encode()).hexdigest()[:12];labels[text]={'id':'L-'+key,'text':text}
 short_aliases={
  '室内消火栓无消防水带':['水带缺失','消防水带缺失','无消防水带','hose_missing'],
  '室内消火栓无消防水枪':['水枪缺失','消防水枪缺失','无消防水枪','water_gun_missing','gun_missing'],
  '室内消火栓手轮缺失':['手轮缺失','handwheel_missing'],
  '室内消火栓消防接口缺失':['消防接口缺失','fire_interface_missing'],
  '消防软管卷盘供水管道折弯严重':['软管折弯严重','供水管道折弯严重','hose_reel_pipe_bent','reel_pipe_bent'],
  '室内消火栓栓口方向错误':['栓口方向错误','outlet_direction_wrong'],
  '室内消火栓箱体或箱门被物品遮挡':['消火栓被遮挡','箱门被遮挡','obstructed'],
  '室内消火栓箱锈蚀':['箱体锈蚀','box_rust'],
  '室内消火栓箱门缺失':['箱门缺失','door_missing'],
  '室内消火栓无箱体':['箱体缺失','cabinet_missing'],
  '室内消火栓箱体无铭牌':['无铭牌','铭牌缺失','nameplate_missing'],
  '室内消火栓箱门标识模糊':['箱门标识模糊','door_text_blurry'],
  '室内消火栓箱门为玻璃门':['玻璃门','glass_door'],
  '室内消火栓箱门上未标注“消火栓”和英文“FIRE HYDRANT”字样':['door_text_missing'],
  '室内消火栓箱明显部位未采用耐久性文字或图形标注操作说明':['操作说明缺失','operation_instruction_missing'],
 }
 for text,item in labels.items():item['aliases']=short_aliases.get(text,[])
 label_list=sorted(labels.values(),key=lambda r:r['id']);visual=[]
 for h, group in sorted(grouped.items()):
  first=group[0];expected=first['expected_output'];canonical=sorted(labels[label(t)]['id'] for t in expected['labels'])
  assert all(sorted(labels[label(t)]['id'] for t in r['expected_output']['labels'])==canonical and r['expected_output']['scope']==expected['scope'] for r in group)
  origins={'train' if '__train_' in r['metadata']['source_id'] else 'val' for r in group};assert len(origins)==1
  split='legacy_train_regression' if 'train' in origins else 'legacy_validation'
  rid='VIS-'+h[:16]
  visual.append({'id':rid,'family_id':rid,'suite':'visual','split':split,
    'requirements':['VIS-01','VIS-03'],'input':{'query':first['input']['query'],'scene':{},'facility':'indoor_hydrant',
      'project_id':'default','session_id':'coverage-'+h[:16],'as_of':'2026-10-05','jurisdiction':'四川',
      'mode':'inspection','retrieval_mode':'rrf','use_model':True},
    'assets':{'image_path':first['input']['image_path'],'image_sha256':h,'image_sha1':first['metadata']['image_sha1']},
    'expected':{'scope':expected['scope'],'visual_status':'visible_anomaly' if expected['labels'] else 'no_visible_anomaly',
      'label_ids':canonical,'label_texts':[labels[label(t)]['text'] for t in expected['labels']],
      'legacy_verdict':expected['verdict'],'legal_verdict':None},
    'oracle_kind':'inherited_sft_visual_annotation_not_legal_gold',
    'source':{'original_ids':[r['scenario_id'] for r in group],'original_source_ids':[r['metadata']['source_id'] for r in group],
      'file_sha256':source_sha,'training_overlap':'known_sft_train' if split=='legacy_train_regression' else 'known_sft_validation',
      'human_reverified':False},'execution':{'mode':'live_model','status':'not_run'}})
  for r in group:provenance.append({'original_id':r['scenario_id'],'enhanced_id':rid,'original_scene_removed':r['input']['scene'],
      'original_metadata':r['metadata'],'removed_from_model_input':['scene_category_description','expected_output','metadata','category']})
 store=Store();sid=store.active_snapshot()
 gold_path=project/'benchmarks/inspection_scenarios/v2/astra-reviewed/astra-reviewed-gold.jsonl'
 cases_path=project/'benchmarks/inspection_scenarios/v2/astra-reviewed/cases.jsonl'
 gold={r['case_id']:r for r in read_rows(gold_path)};business=[]
 for case in read_rows(cases_path):
  g=gold[case['id']];ctx=g['execution_context'];inp=copy.deepcopy(case['input'])
  inp.update(ctx['executed_input']);inp['retrieval_mode']='rrf';inp['session_id']='coverage-'+case['id']
  faults=ctx.get('fault_injection',[])
  if case['category']=='partial_failure':faults=['reranker_timeout'];inp['retrieval_mode']='rerank'
  req=['VER-01','VER-02','HAR-01','HIT-01']
  if case.get('image_path'):req+=['VIS-01','VIS-02','INT-01','VER-03']
  if case['category'] in ['follow_up','facility_switch']:req+=['INT-02','MEM-01']
  if faults:req+=['RAG-03','HAR-03']
  if g['evaluation_mask'].get('retrieval_on_frozen_snapshot'):req+=['RAG-01']
  mask=copy.deepcopy(g['evaluation_mask'])
  groups=copy.deepcopy(g.get('evidence_requirements',[]))
  # Evidence may be absent from the index; never manufacture retrieval targets.
  missing=[eid for need in groups for eid in need.get('any_of',[]) if not store.db.evidence.find_one({'snapshot_id':g['snapshot_id'],'evidence_id':eid},{'_id':1})]
  business.append({'id':'BUS-'+case['id'],'family_id':'BUS-'+case['family_id'],'split':case['split'],'suite':'business',
    'requirements':sorted(set(req)),'category':case['category'],'input':inp,
    'assets':{'image_path':case.get('image_path'),'image_sha256':case.get('image_sha256')},
    'context':{'frozen_memory':ctx['frozen_memory'],'fault_injection':faults},
    'snapshot_id':g['snapshot_id'],'expected':{'behavior':case['expected']['behavior'],
      'visual_decision':g['visual_decision'],'gold_observations':g['gold_observations'],
      'evidence_requirements':groups,'missing_information':g['missing_information'],'critical_points':g['critical_points'],
      'forbidden_claims':g['forbidden_claims'],'reference_answer':g['reference_answer'],'evaluation_mask':mask,
      'unindexed_reference_evidence':sorted(set(missing))},
    'oracle_kind':'astra_reviewed_model_reference_not_expert_gold',
    'source':{'case_id':case['id'],'case_file_sha256':sha(cases_path),'gold_file_sha256':sha(gold_path),
      'packet_hash':g['packet_hash'],'training_overlap':case.get('training_overlap_status','not_applicable_no_image' if not case.get('image_path') else 'unknown'),'human_verified':False,
      'split_preserved':True},'execution':{'mode':'live_model','status':'not_run'}})
 rag_path=project/'benchmarks/legal_scenarios/v1/cases.jsonl';rag=[]
 historical_report=project/'reports/v2/retrieval/summary-all.json'
 rag_sid=json.loads(historical_report.read_text())['snapshot_id']
 if not store.db.snapshots.find_one({'_id':rag_sid,'state':'published'}):raise ValueError('Historical RAG snapshot is unavailable')
 for c in read_rows(rag_path):
  rag.append({'id':'RAG-'+c['id'],'family_id':'RAG-'+c['family_id'],'suite':'rag','split':'legacy_'+c['split'],
    'requirements':['RAG-01','RAG-02'],'input':{'query':query_text(c),'facility':'auto','project_id':'default',
      'session_id':'coverage-rag-'+c['id'],'scene':{},'as_of':c['as_of'],'jurisdiction':'四川','mode':'retrieval','retrieval_mode':'bm25','use_model':False},
    'assets':{},'snapshot_id':rag_sid,'expected':{'legacy_evidence_ids':c['gold_evidence_ids'],
      'retrieval_expectation':c['retrieval_expectation'],'action':c['expected']['action'],'must_not':c['expected']['must_not'],
      'forbidden_doc_ids':c.get('forbidden_doc_ids',[])},'oracle_kind':'source_aligned_legacy_retrieval_reference',
    'source':{'case_id':c['id'],'case_file_sha256':sha(rag_path),'historical_test_previously_viewed':True,'human_verified':False},
    'execution':{'mode':'cpu_bm25','status':'not_run'}})
 contract=contracts();allrows=visual+business+rag+contract
 for row in visual+business+rag:InspectionInput.model_validate(row['input'])
 for name,rows in [('visual.jsonl',visual),('business.jsonl',business),('rag.jsonl',rag),('contracts.jsonl',contract),('cases.jsonl',allrows),('original-to-enhanced.jsonl',provenance)]:jsonl(out/name,rows)
 dump(out/'label-vocabulary.json',label_list)
 testrefs=existing_tests(project);dump(out/'existing-test-references.json',testrefs)
 dump(out/'requirements.json',REQUIREMENTS)
 legacy_evidence=project/'benchmarks/legal_scenarios/v1/evidence.json'
 shutil.copyfile(legacy_evidence,out/'rag-evidence.json')
 # Store full reference evidence separately so it cannot be accidentally fed as context.
 jsonl(out/'business-reference-gold.jsonl',[gold[c['source']['case_id']] for c in business])
 coverage=[]
 for req,description in REQUIREMENTS.items():
  cases=[r['id'] for r in allrows if req in r['requirements']]
  refs=[r['nodeid'] for r in testrefs if req in r['requirements']]
  coverage.append({'requirement':req,'description':description,'case_ids':cases,'existing_test_refs':refs,
                   'status':'scenario_defined_execution_pending' if cases or refs else 'planned_live_load_required'})
 dump(out/'coverage-matrix.json',coverage)
 load={'scope':'real_performance_not_mock','status':'not_run','tasks_per_level':100,'warmup_tasks':10,
       'concurrency':[1,2,4,8],'repetitions':3,'max_model_parallelism':4,
       'metrics':['queue_seconds','active_seconds','end_to_end_seconds','p50','p95','throughput','model_calls','tokens','failure_rate'],
       'preconditions':['model services healthy','GPU owners and spare capacity checked','separate project/session identities'],
       'case_sources':['dev only business scenarios, balanced facilities; do not use holdout for tuning'],
       'warning':'This is a protocol, not an executed capacity or SLA result.'}
 dump(out/'load-protocol.json',load)
 dump(out/'restore-protocol.json',{'requirement':'OPS-03','status':'not_run',
   'historical_reference':'reports/v2/restore_check.json and docs/v2/OPERATIONS.md',
   'source':'a new consistent archive of a disposable test deployment, never overwrite current DB',
   'checks':['archive restore into a new isolated database','document and evidence counts match manifest',
     'all text/source hashes unchanged','task/report/checkpoint/outbox associations intact',
     'resume paused approval from restored checkpoint','rebuild index before snapshot publication'],
   'note':'Data scenarios cannot prove backup recoverability; this operation needs a separate restore exercise.'})
 files={p.name:sha(p) for p in sorted(out.glob('*')) if p.is_file() and p.name not in ['manifest.json','README.md']}
 manifest={'version':VERSION,'source_200_sha256':source_sha,'original_rows':len(original),'clean_visual_rows':len(visual),
   'duplicates_removed':len(original)-len(visual),'original_scene_descriptions_removed':sum(r['input']['scene']!='未指定场景' for r in original),
   'counts':dict(Counter(r['suite'] for r in allrows)),'total_cases':len(allrows),'splits':dict(Counter(r['split'] for r in allrows)),
   'business_facilities':dict(Counter(r['input']['facility'] for r in business)),
   'visual_status':dict(Counter(r['expected']['visual_status'] for r in visual)),
   'business_visual_reference':dict(Counter(r['expected']['visual_decision'] for r in business)),
   'snapshot_id':sid,'legacy_rag_snapshot_id':rag_sid,'source_files':{str(p.relative_to(project)):sha(p) for p in [cases_path,gold_path,rag_path,legacy_evidence,historical_report]},
   'files':files,'known_boundaries':['165 visual train images are regression only','23 visual validation images are previously used validation',
    'business 180/60/60 split preserved; no holdout tuning','Astra labels are model references, not expert certification',
    'historical 272 retrieval cases are not blind','performance protocol is pending live execution','contract fixtures are synthetic and must never enter legal KB'],
   'production_code_modified':False}
 dump(out/'manifest.json',manifest)
 return manifest

if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--project-root',type=Path,required=True);p.add_argument('--source200',type=Path,default=Path('/tmp/xfagent_test_scenarios_200.jsonl'));p.add_argument('--output',type=Path,required=True)
 a=p.parse_args();print(json.dumps(build(a.project_root,a.source200,a.output),ensure_ascii=False,indent=2))
