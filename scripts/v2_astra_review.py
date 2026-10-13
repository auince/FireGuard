"""Evidence-backed second-pass Astra adjudication; no GPU or human labeling gate."""
import copy,json,re,base64,argparse,fcntl
from pathlib import Path
import v2_astra_annotate as base
PROTOCOL='xf-fire-astra-adjudication-v2.0'
BASE_PROMPT=base.PROMPT
PROMPT=BASE_PROMPT+'''
【本轮任务覆盖上面的首轮输出格式：执行第二轮独立核对】
你是本数据集最终的 Astra 标注复核器。本次没有后续人类标注员。请逐例核对原图、已提供的法规正文、原始输入与实际执行上下文，然后审查 first_pass_annotations；不要因为初稿也是 Astra 写的就认可，也不要仅修改措辞。先依据证据判断，再决定保留或纠正。只提供简洁可审计的理由，不输出思维链。
补充背景及优先级：
- 当前是数据集标签复核；needs_human_review 旧字段表示业务报告定稿边界，继续保持 true。它不表示标签等待人审。本轮 label_review_complete 必须为true，不能把裁决委托给未来人工。现场缺少照片或测量时，标签的最终答案就是“无法判断/需补充现场信息”，这是有效标签而非未完成标注。
- cases.execution_context 包含此前保存的实际输入、frozen_memory、故障注入，仅这些输入可补全多轮事实。绝不使用被测9B模型输出。same facility 工作记忆的 last_query 可提供先前已确认的文字事实；切换设施后旧观察不可迁移。组织经验不是法规。场景 query 是用户提问，不是照片真实状态的保证。
- 样本为工程构造场景复用真实照片，as_of 是法规适用评测日期，不等于有证据的照片拍摄日期。照片可标注可见状态；如果图中日期晚于 as_of，只排除“当时现场违法”结论，不删除可见异常标签。住宅公共区域/highrise等是测试给定条件，无须仅因图片不能验证建筑用途就拒绝；与图片明显矛盾时列冲突并限制结论。园区道路并不自动证明没有室内栓，但不能把室内栓强行当室外栓。
- 只评用户实际询问和有事实支持的事项；不要为一个“遮挡”问题要求补齐全部建筑面积、压力、配置数量。knowledge_gaps 只保留会阻止回答当前问题的缺失法规；不相关技术细则从缺口中删除。测量缺失属于现场事实不足，不属于法规缺失。注入指令、遮挡图像和故障本来就是测试刺激，不应一律视为坏样本。
- 设施视觉判断：发现明确可见异常，即使其他部位未知，也可 abnormal；只有关键观察范围充分且无可见异常才 normal；看不清/没拍到目标不能判正常或缺失。图中正在接带使用不等于保护盖永久丢失；水泵接合器、栓阀和其他阀件不得混同。压力表只有型号适用且图像清晰才能判断绿区，模糊不猜读。normalized box 必须有明确可定位依据。
- GB50444补充仅为官方扫描原文中未列入废止清单的附录C检查内容，作为技术检查依据，不称每项都是强制性条文。与GB55036冲突以GB55036为准。补充证据 indexed_in_snapshot=false：可用于标签/回答，但不能假装旧检索库能返回。不要为了使评测可用而删掉确需的补充依据。
- 原文内【条文说明】仅解释，不能变成强制条文。对隐患/维护要求应优先选择真实适用的直接条款。any_of 是可替代证据；若必须联合两条，拆成两个need。首轮所列引用即使字面真实也可能不支撑结论，必须检查。
输出仅一个 JSON: {"reviews":[...]}，所有case恰好一次。每个review格式：
{"case_id":"实际编号","decision":"accept或correct","label_review_complete":true,"review_notes":["简述经核对确认/修正的具体依据"],"checks":{"image":"checked或not_applicable","context":"checked","legal_support":"checked","date_region":"checked","scope":"checked"},"issue_resolutions":[{"issue_index":0,"disposition":"resolved_by_context或corrected_label或valid_uncertainty或test_stimulus或out_of_scope","reason":"此项初稿scenario_issues如何处理"}],"patch":{},"evaluation":{"status":"usable或partially_evaluable或not_evaluable","excluded_dimensions":["不可评估的具体维度及原因"],"uncertainties":["已裁定仍未知的事实，不能等待标注员"],"reason":"为何仍能评哪些内容"}}
patch为first_pass_annotations该例的顶层字段替换，没变的字段省略，变更字段给完整值（数组整体替换）；不得修改case_id/facility/needs_human_review。decision=accept必须patch={}，correct必须有实际内容变化。引用变动时同步修改requirements、requiredIDs、reference_answer。更新scenario_issues时保留事实冲突或证据边界的描述，可以删除已由上下文解决的误报，不能将“待人工标注”当最终状态。
issue_resolutions必须覆盖该例初稿scenario_issues所有0起始索引，不能遗漏或重复。即使没有首轮问题也须做完整核查并给review_notes。evaluation.uncertainties标注最终未知事实；excluded_dimensions只排除无法得到真值的判断维度，不排除“正确表达不确定”的行为评测。not_evaluable只在整个案例完全无可评分内容时使用。不要将大量正常边界场景全部丢弃。
'''
ALLOWED={'scene_facts','gold_observations','visual_decision','evidence_requirements','required_evidence_ids','missing_information','needs_additional_info','critical_points','forbidden_claims','reference_answer','knowledge_gaps','scenario_issues','confidence'}
original_validate=base.validate

def materialize(obj,packet):
 old={a['case_id']:a for a in packet['first_pass_annotations']}
 return [{**copy.deepcopy(old[r['case_id']]),**copy.deepcopy(r.get('patch',{}))} for r in obj['reviews']]

def validate(obj,packet):
 if not isinstance(obj,dict) or not isinstance(obj.get('reviews'),list):return ['reviews must be a list']
 errors=[];old={a['case_id']:a for a in packet['first_pass_annotations']};cs={c['case_id']:c for c in packet['cases']}
 if sorted(old)!=sorted(r.get('case_id','') for r in obj['reviews']):return ['review case IDs must match exactly once']
 for r in obj['reviews']:
  cid=r['case_id'];a=old[cid];patch=r.get('patch')
  if not isinstance(patch,dict):errors.append(cid+':patch must be object');continue
  if set(patch)-ALLOWED:errors.append(cid+':forbidden patch fields')
  changed=any(a.get(k)!=v for k,v in patch.items())
  if r.get('decision') not in ['accept','correct'] or (r['decision']=='accept' and patch) or (r['decision']=='correct' and not changed):errors.append(cid+':decision/patch mismatch')
  if r.get('label_review_complete') is not True:errors.append(cid+':label adjudication must be complete')
  if not isinstance(r.get('review_notes'),list) or not r['review_notes']:errors.append(cid+':missing audit notes')
  expected={'image':'checked' if cs[cid]['image_present'] else 'not_applicable','context':'checked','legal_support':'checked','date_region':'checked','scope':'checked'}
  if r.get('checks')!=expected:errors.append(cid+':all review checks required')
  issues=r.get('issue_resolutions',[])
  if sorted(x.get('issue_index',-1) for x in issues)!=list(range(len(a['scenario_issues']))):errors.append(cid+':must resolve every original issue index exactly once')
  for x in issues:
   if x.get('disposition') not in ['resolved_by_context','corrected_label','valid_uncertainty','test_stimulus','out_of_scope'] or not x.get('reason'):errors.append(cid+':invalid issue resolution')
  ev=r.get('evaluation',{})
  if ev.get('status') not in ['usable','partially_evaluable','not_evaluable'] or not ev.get('reason') or not isinstance(ev.get('uncertainties'),list) or not isinstance(ev.get('excluded_dimensions'),list):errors.append(cid+':invalid evaluation scope')
  if ev.get('status') in ['partially_evaluable','not_evaluable'] and not ev.get('excluded_dimensions'):errors.append(cid+':excluded dimensions required')
 if errors:return errors
 annotations=materialize(obj,packet)
 errors+=original_validate({'annotations':annotations},packet)
 for a in annotations:
  for o in a['gold_observations']:
   box=o.get('region')
   if box is not None and (not isinstance(box,list) or len(box)!=4 or not all(isinstance(v,(int,float)) and 0<=v<=1 for v in box) or box[0]>=box[2] or box[1]>=box[3]):errors.append(a['case_id']+':invalid normalized region')
  if type(a['needs_additional_info']) is not bool:errors.append(a['case_id']+':additional info must be boolean')
 # Materialized final labels are derived; original unmodified API JSON remains in raw responses.
 if not errors:obj['annotations']=annotations
 return errors

original_build_content=base.build_content
BACKGROUND_ROOT=None
def build_content(packet,image_dir):
 content=original_build_content(packet,image_dir)
 for item in packet.get('background_source_images',[]):
  path=BACKGROUND_ROOT/item['relative_path'];raw=path.read_bytes()
  if base.sha(raw)!=item['sha256']:raise ValueError('background image hash mismatch')
  content.extend([{'type':'text','text':'以下为法规扫描原页，仅核对 supplemental E901..E911 的转写与含义，不是任何case的现场照片。'+json.dumps({k:v for k,v in item.items() if k!='relative_path'},ensure_ascii=False)},{'type':'image_url','image_url':{'url':'data:image/png;base64,'+base64.b64encode(raw).decode(),'detail':'high'}}])
 return content

_ORIGINAL_RUN=base.run
def run_with_lock(packet_path,config,image_dir,out):
 # Cross-process lock covers cache validation and the entire request/commit.
 # flock releases automatically on process exit, including interruption.
 locks=out/'locks';locks.mkdir(parents=True,exist_ok=True)
 with (locks/(packet_path.stem+'.lock')).open('a') as handle:
  fcntl.flock(handle.fileno(),fcntl.LOCK_EX)
  return _ORIGINAL_RUN(packet_path,config,image_dir,out)

def main():
 global BACKGROUND_ROOT
 parser=argparse.ArgumentParser(add_help=False);parser.add_argument('--packets',type=Path,required=True);args,_=parser.parse_known_args();BACKGROUND_ROOT=args.packets.parent
 base.build_content=build_content
 base.run=run_with_lock
 base.PROTOCOL=PROTOCOL;base.PROMPT=PROMPT;base.validate=validate
 base.main()
if __name__=='__main__':main()
