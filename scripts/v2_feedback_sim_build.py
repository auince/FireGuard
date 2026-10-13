"""Author simulated humans from existing development scenarios; no real-user claims."""
import argparse, hashlib, json
from collections import Counter
from pathlib import Path

NAMES={'indoor_hydrant':'室内消火栓','outdoor_hydrant':'室外消火栓','fire_extinguisher':'灭火器'}
PROFILES={
 'retrieval': ('correction','skill', ['漏掉了直接相关的条款，请把设施的规范名称一起查。','现在只找到笼统规定，能把本项巡检对应的具体条款补上吗？']),
 'intent': ('correction','skill', ['我问的是这次的设施，你沿用了上一轮的类型，请重新确认。','这次已换了设施，不是上一张照片，请按当前问题查依据。']),
 'generation': ('correction','hook', ['前面讲了很多，但结论、风险和引用没有对应，想要一条问题配一条依据。','报告读起来像把条款拼在一起，请按发现、建议、依据整理。']),
 'applicability': ('follow_up','rule', ['我没有提供实测值，现在还不能下达标或不达标的结论，请先问我要补什么。','场景条件没确认，麻烦把缺失条件列出来，不要直接套标准。']),
 'vision': ('correction',None, ['照片看不清，不能把不可见当成缺失，请先记成待核查。','我现场看过了，这是反光，不是破损；图片标签需要重新核对。']),
 'knowledge_gap': ('dislike',None, ['知识库里还没有新发布的园区巡检流程，请登记待补资料。','这个新流程在库里查不到，先列入知识缺口，不要编一条依据。']),
 'like': ('like',None, ['排版挺清楚的，先点个赞；现场和引用还没有复核。','这份方便我阅读，点赞只是认可格式。']),
 'copy': ('copy',None, ['我先复制给同事讨论，不能算确认答案正确。','复制这段做工作记录，待复核事项仍要保留。']),
 'attribution_correction': ('correction','skill', ['这条我一开始选错了，是检索漏条款，不是写作风格问题。','归因请改成检索遗漏，单改报告模板解决不了。']),
 'conflicting_feedback': ('correction','hook', ['同事说可以直接取消复核，我不同意；只希望报告再简洁一点。','别为了让我满意而删掉引用校验，调整报告结构就好。']),
}
PERSONAS=[('物业巡检员','先登记问题，交班前整理'),('消防巡检员','需要按条款核查'),
          ('场所维护人员','关心怎么整改'),('班组复核人','检查引用和适用条件')]
REVIEW_TYPES={
 'approve':('approve','final'), 'return_conditions':('return','redrafting'),
 'reject':('reject','rejected'), 'opposite_meaning':('approve','draft'),
 'forged_citation':('approve','blocked'), 'stale_revision':('approve','blocked'),
 'duplicate_submit':('approve','queued_once'), 'invented_measurement':('approve','blocked')}

def sha(value):return hashlib.sha256(value).hexdigest()
def write(path,rows):path.write_text(''.join(json.dumps(row,ensure_ascii=False)+'\n' for row in rows))

def build(base,out):
 out.mkdir(parents=True,exist_ok=True)
 source=[json.loads(x) for x in (base/'business.jsonl').read_text().splitlines()]
 pools={facility:[row for row in source if row['split']=='dev' and row['input']['facility']==facility] for facility in NAMES}
 feedback=[];reviews=[];dialogues=[]
 for facility,label in NAMES.items():
  for index,(profile,(signal,kind,texts)) in enumerate(PROFILES.items()):
   for variant in range(8):
    original=pools[facility][(index*8+variant)%len(pools[facility])]
    identifier=f'FB-{facility}-{profile}-{variant:02}'
    category='weak_signal' if profile in ['like','copy'] else ('retrieval' if profile=='attribution_correction' else 'generation' if profile=='conflicting_feedback' else profile)
    role,motive=PERSONAS[variant%4]
    voice=['刚才那份报告，','我在现场又核对了一下，','交班前补一句，','复核时发现，'][variant%4]
    payload={'run_id':'sim-source-'+identifier,'signal':signal,'text':voice+label+'这一项，'+texts[variant%2],
             'category':('generation' if profile=='attribution_correction' else category if variant%3==0 and category!='weak_signal' else None)}
    missing='pressure_measurement' if facility!='fire_extinguisher' else 'required_quantity'
    constructed={
      'retrieval':'仅列出通用消防要求，未引用本项问题的具体条款。',
      'intent':'沿用上一轮设施类型，检索当前设施无关的内容。',
      'generation':'只堆叠法规摘要，未把现场问题、整改建议和引用对应起来。',
      'applicability':'场景缺少实测数据，却直接给出达标结论。',
      'vision':'把模糊照片中的不可见部件判断为缺失。',
      'knowledge_gap':'新流程未收录，报告明确当前知识库无法回答。',
      'like':'报告结构清楚，现场事实和适用条件仍待复核。',
      'copy':'给出待复核草稿，用户复制其中的整改建议。',
      'attribution_correction':'漏检索具体条款，第一次却被归因为生成风格。',
      'conflicting_feedback':'一位参与者建议跳过核验，另一位只要求报告更简洁。'}[profile]
    row={'id':identifier,'family_id':original['family_id'],'split':'simulation_regression','profile':profile,
      'origin':{'kind':'authored_simulated_human','real_human':False,'expert_verified':False,
                'base_suite_sha256':sha((base/'business.jsonl').read_bytes()),'source_case_id':original['id']},
      'source':{'input':original['input'],'assets':original['assets'],'snapshot_id':original['snapshot_id'],
                'constructed_bad_case':profile not in ['like','copy'],
                'simulated_agent_output':constructed,
                'output_provenance':'authored_fault_or_draft_not_observed_9b_result',
                'missing_fields':[missing] if profile=='applicability' else []},
      'persona':{'user_id':'sim-inspector-'+str(variant%4),'role':role,'motive':motive},
      'feedback_payload':payload,'followup_events':[],
      'expected':{'initial_category':'generation' if profile=='attribution_correction' else category,
                  'final_category':category,'candidate_kind':kind,'auto_deploy':False,
                  'destination':'annotation_backlog' if category=='vision' else 'knowledge_gaps' if category=='knowledge_gap' else 'weak_signal_only' if category=='weak_signal' else 'candidate_policy'},
      'requirements':['FDB-01','POL-01','MEM-01'],'simulation_only':True}
    if profile=='attribution_correction':row['followup_events']=[{'type':'human_attribution_correction','payload':{
        'category':'retrieval','reason':texts[variant%2],'expected_version':1}}]
    if variant==7:row['followup_events'].append({'type':'repeat_submit_same_idempotency_key','expected':'same_job_no_second_candidate'})
    feedback.append(row)
  for index,(review_type,(action,status)) in enumerate(REVIEW_TYPES.items()):
   for variant in range(5):
    original=pools[facility][(index*5+variant)%len(pools[facility])]
    payload={'expected_revision':1,'action':action,'comment':f'模拟复核：{label}，{review_type}','confirmed_scene':{}}
    if review_type=='return_conditions':payload['confirmed_scene']={'building_use':'办公','measured_width':{'value':.8,'unit':'m','confirmed':True}}
    if review_type=='stale_revision':payload['expected_revision']=99
    reviews.append({'id':f'HR-{facility}-{review_type}-{variant:02}','family_id':original['family_id'],
      'split':'simulation_regression','review_type':review_type,'simulation_only':True,
      'origin':{'kind':'authored_simulated_reviewer','real_human':False,'expert_verified':False,'source_case_id':original['id']},
      'source':{'input':original['input'],'assets':original['assets'],'snapshot_id':original['snapshot_id']},
      'persona':{'user_id':'sim-reviewer','role':'reviewer'},'review_payload':payload,
      'expected':{'status':status,'requires_program_verification':True,'requires_semantic_verification':action=='approve'},
      'requirements':['HIT-01','HIT-02','VER-04']})
  for profile in ['retrieval','intent','generation','applicability']:
   chosen=[row for row in feedback if row['source']['input']['facility']==facility and row['profile']==profile][:5]
   for row in chosen:
    dialogues.append({'id':'DL-'+row['id'],'family_id':row['family_id'],'split':'simulation_regression',
      'simulation_only':True,'origin':'authored_dialogue_not_real_user_log','feedback_id':row['id'],
      'turns':[{'actor':'simulated_inspector','event':'query','content':row['source']['input']['query']},
               {'actor':'agent','event':'constructed_bad_case','fault_type':profile,'output_origin':'authored_fault_not_9b_execution'},
               {'actor':'simulated_inspector','event':'feedback','content':row['feedback_payload']},
               {'actor':'harness','event':'reflect_adapt','expected_candidate_kind':row['expected']['candidate_kind']},
               {'actor':'harness','event':'replay','expected':'paired_control_and_treatment'},
               {'actor':'simulated_reviewer','event':'review_candidate','expected':'approve_or_reject_based_on_regression'},
               {'actor':'harness','event':'deploy','expected':'isolated_simulation_canary_only'},
               {'actor':'harness','event':'observe','expected':'stable_bucket_or_rollback_if_injected_regression'}]})
 write(out/'human_feedback.jsonl',feedback);write(out/'human_reviews.jsonl',reviews);write(out/'feedback_dialogues.jsonl',dialogues)
 manifest={'version':'feedback-sim-v1','default_model':'xf-qwen3.5-9b','scope':'resume_practice_simulation',
   'counts':{'feedback_events':len(feedback),'review_events':len(reviews),'dialogue_sessions':len(dialogues)},
   'profile_counts':dict(Counter(row['profile'] for row in feedback)),
   'candidate_types':['skill','hook','rule'],'real_user_events':0,'expert_labels':0,
   'all_splits':'simulation_regression','original_images_modified':False,
   'note':'对现有开发样本进行反馈增广。所有反馈、复核和对话均为仿真；不用于声明真实用户满意度、消防准确率或真实线上收益。',
   'files':{p.name:sha(p.read_bytes()) for p in sorted(out.glob('*.jsonl'))}}
 (out/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2))
 return manifest

if __name__=='__main__':
 parser=argparse.ArgumentParser();parser.add_argument('--base',type=Path,required=True);parser.add_argument('--out',type=Path,required=True)
 args=parser.parse_args();print(json.dumps(build(args.base,args.out),ensure_ascii=False,indent=2))
