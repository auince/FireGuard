"""Native LangGraph visual workflow; reuse xfDemo functions, never its Agent wrapper."""
import os,sys,time
import re
from typing import TypedDict
from langgraph.graph import StateGraph,START,END
from .config import ROOT,settings

def consistency_guard(report):
    """Do not expose a contradictory normal-evidence/abnormal-label answer as confirmed."""
    match=re.search(r'(?m)^隐患标签[:：]\s*(.+)$',report)
    labels=match.group(1).strip() if match else ''
    if labels and labels not in ['无','无。'] and re.search(r'可见依据[:：]\s*(未见明确隐患|未发现异常)',report):
        scope=re.search(r'(?m)^检查范围[:：]\s*(.+)$',report)
        return ('检查范围：'+(scope.group(1) if scope else '无法确定')+'\n结论：无法判断\n可见依据：模型的证据描述与隐患标签相互矛盾，需要人工复核。\n隐患标签：无\n待复核候选：'+labels),['evidence_verdict_conflict']
    return report,[]

def configure_vendor():
    (ROOT/'runtime/yolo-config/Ultralytics').mkdir(parents=True,exist_ok=True)
    os.environ.setdefault('YOLO_CONFIG_DIR',str(ROOT/'runtime/yolo-config'))
    sys.path.insert(0,str(ROOT/'vendor/xfdemo'));cfg=settings()
    env={'XF_RUNTIME_ROOT':str(ROOT/'runtime/vision'),'XF_RESOURCE_ROOT':str(ROOT/'vendor/xfdemo/resources'),'XF_ARTIFACT_ROOT':str(ROOT/'runtime/vision/artifacts'),'YOLO_PYTHON':str(ROOT/'.venv-model/bin/python'),'YOLO_DEVICE':'cpu','YOLO_INTERNAL_WEIGHTS':'/opt/xfagent/artifacts/yolo/fire_hydrant_v3_20260707/fire_hydrant_20260715.pt','YOLO_CLASSES_FILE':'/opt/xfagent/artifacts/yolo/fire_hydrant_v3_20260707/fire_hydrant_20260715.json'}
    for prefix in ['FIRST_VL','JUDGE_VL','DIRECTION_REVIEW']:
        env.update({prefix+'_API_BASE':cfg['base_url'],prefix+'_API_KEY':cfg['api_key'],prefix+'_MODEL':cfg['model'],prefix+'_PROVIDER':'openai'})
    for key,value in env.items():os.environ.setdefault(key,value)

class VisualState(TypedDict,total=False):
    image:str
    query:str
    branch:str
    task:str
    expected_scope:str
    yolo:dict
    raw_report:str
    final_report:str
    reviewed_text:str
    trace:list
    usage:dict
    vision:dict

def visual_graph():
    configure_vendor()
    from backend.modules.inspection import messages as m,parser as p
    from backend.modules.inspection.router import resolve_yolo_route
    from backend.modules.inspection.intent import resolve_intent
    from backend.modules.inspection.registry import get_branch
    from backend.modules.inspection.pipeline import _probe_for_intent,expected_scope_for_branch,merge_usage
    from backend.modules.inspection.postprocess import guarded_format_judge_json,enforce_report_scope
    from backend.modules.inspection.yolo_context import apply_yolo_backstop,MISSING_EQUIPMENT_LABELS,yolo_labels_for_trace
    from backend.modules.inspection.utils import strip_reasoning
    from backend.infrastructure.vision.yolo_detector import run_yolo_detection
    from backend.infrastructure.ai.model_client import create_model_client
    from backend.config.settings import get_settings
    cfg=get_settings();client=create_model_client(cfg,provider='openai')
    def call(messages):
        r=client.invoke(messages);return strip_reasoning(r.content),r.usage
    def trace(s,name,**extra):return s.get('trace',[])+[{'node':name,**extra}]
    def route(s):
        intent,yolo,meta=resolve_yolo_route(s['image'])
        if intent.inspection_type=='unknown':
            intent,review=resolve_intent(client,'',s['image'])
            if intent.inspection_type!='unknown':yolo,meta['selectedTask']=_probe_for_intent(meta,intent.inspection_type,intent.scope_hint)
        branch=intent.inspection_type;task=meta.get('selectedTask','internal_components')
        return {'branch':branch,'task':task,'yolo':yolo,'usage':{},'trace':[{'node':'route','branch':branch,'task':task,'evidence':intent.evidence}]}
    def first(s):
        text,usage=call(m.build_messages(query=s['query'],image=s['image'],task=s['task'],branch_key=s['branch'],yolo_result=s['yolo']))
        report=p.pick_primary_structured_report(text)
        return {'raw_report':report,'final_report':report,'usage':usage,'trace':trace(s,'first_analysis',report=report)}
    def align(s):
        task=s['task'];yolo=s['yolo']
        if s['branch']=='indoor_hydrant':
            task=p.detect_task('','auto',s['raw_report'])
            if task=='auto':task='internal_components' if '内部' in s['raw_report'] else 'appearance'
            desired='appearance_presence' if task=='appearance' else 'component_presence'
            if yolo.get('modelType')!=desired:yolo=run_yolo_detection(s['image'],task=task)
        return {'task':task,'yolo':yolo,'expected_scope':expected_scope_for_branch(s['branch'],task),'trace':trace(s,'scope_alignment',task=task)}
    def judge(s):
        text,usage=call(m.build_judge_messages(s['query'],s['image'],s['raw_report'],s['task'],yolo_result=s['yolo'],branch_key=s['branch']))
        report=guarded_format_judge_json(text,s['raw_report'],expected_scope=s['expected_scope'])
        if not report:report=p.sanitize_final_report(text) if p.has_structured_report(text) else s['raw_report']
        return {'final_report':report,'reviewed_text':text,'usage':merge_usage(s['usage'],usage),'trace':trace(s,'judge',report=report)}
    def specialist(name,build,parse,apply,predicate,extra=lambda s:[]):
        def node(s):
            if not predicate(s):return {'trace':trace(s,name,status='not_triggered')}
            args=[s['image'],s['query'],s['raw_report'],s['final_report'],*extra(s)]
            kwargs={'yolo_result':s['yolo']} if name in ['operation_instruction','outlet_direction'] else {}
            raw,usage=call(build(*args,**kwargs));data=parse(raw)
            report=apply(s['final_report'],data,*extra(s))
            return {'final_report':report,'usage':merge_usage(s['usage'],usage),'trace':trace(s,name,status='reviewed' if data else 'invalid_review',changed=report!=s['final_report'],raw=raw)}
        return node
    def internal(s):return s['branch']=='indoor_hydrant' and s['task']=='internal_components'
    def missing(s):return sorted((set(p.labels_from_report(s['raw_report']))|set(p.labels_from_report(s['final_report'])))&MISSING_EQUIPMENT_LABELS)
    def direction(s):
        labels=set(yolo_labels_for_trace(s['yolo']))
        return internal(s) and ('室内消火栓栓口方向错误' in p.labels_from_report(s['final_report']) or ('接口' in labels and bool(labels&{'栓体','阀门'})))
    nodes={
      'operation_instruction':specialist('operation_instruction',m.build_operation_instruction_verify_messages,m.parse_operation_instruction_verify,m.apply_operation_instruction_review,lambda s:s['branch']=='indoor_hydrant' and s['task']=='appearance'),
      'missing_equipment':specialist('missing_equipment',m.build_missing_equipment_verify_messages,m.parse_missing_equipment_verify,m.apply_missing_equipment_visibility_review,lambda s:internal(s) and bool(missing(s)),lambda s:[missing(s)]),
      'bend':specialist('bend',m.build_bend_verify_messages,m.parse_bend_verify,m.apply_bend_review,lambda s:internal(s) and p.has_bend_candidate(s['raw_report'],s['reviewed_text'],s['final_report'])),
      'outlet_direction':specialist('outlet_direction',m.build_outlet_direction_verify_messages,m.parse_outlet_direction_verify,m.apply_outlet_direction_review,direction)}
    def finish(s):
        if s['branch']=='unknown':report='检查范围：无法确定\n结论：无法判断\n隐患标签：无\n可见证据：无法可靠识别消防设施，请补拍清晰照片。'
        else:report=enforce_report_scope(apply_yolo_backstop(s['final_report'],s['raw_report'],s['yolo']),s['expected_scope'])
        checked,warnings=consistency_guard(report)
        return {'vision':{'structured_report':checked,'candidate_report':report,'consistency_warnings':warnings,'trace':s['trace'],'yolo':s['yolo'],'usage':s['usage'],'branch':s['branch']}}
    g=StateGraph(VisualState)
    for name,fn in [('route',route),('first_analysis',first),('scope_alignment',align),('judge',judge),*nodes.items(),('finish',finish)]:g.add_node(name,fn)
    g.add_edge(START,'route');g.add_conditional_edges('route',lambda s:'finish' if s['branch']=='unknown' else 'first_analysis')
    order=['first_analysis','scope_alignment','judge',*nodes,'finish']
    for a,b in zip(order,order[1:]):g.add_edge(a,b)
    g.add_edge('finish',END);return g.compile()
