"""Bounded retrieval hints; hypothetical text is never admissible evidence."""
import json
from .config import FACILITIES
from .model import complete

TERMS={'消防箱':'消火栓箱','消防栓':'消火栓','水枪头':'消防水枪','灭火瓶':'灭火器'}

def multi_queries(query,facility,scene,working,model_queries):
    base=query
    for term,standard in TERMS.items():
        if term in query and standard not in base:base+=' '+standard
    if working.get('facility')==facility and any(term in query for term in ['这个','它','怎么改','上述']):
        base+=' '+FACILITIES.get(facility,facility)+' '+str(working.get('last_query',''))[:400]
    # Conditions are supplied facts, never measurements inferred from words/images.
    if scene:base+=' 已确认条件：'+json.dumps(scene,ensure_ascii=False)
    choices=[base]+[q for q in model_queries if isinstance(q,str) and q.strip()]
    return list(dict.fromkeys(choices))[:3]

def hypothetical_hint(state):
    obj=complete(state,'为检索生成一段不超过150字的假设相关内容，输出 {"retrieval_hint":"..."}。仅描述主题、可能的适用条件和规范术语，不生成法规编号、引文、具体数值或合规结论。此内容是检索假设，绝不能作为事实或引用。',
        {'query':state['request']['query'],'facility':state.get('facility'),'scene':state['request']['scene']},role='rewrite')
    text=obj.get('retrieval_hint')
    if not isinstance(text,str) or not text.strip():raise ValueError('empty hypothetical retrieval hint')
    return text[:600]
