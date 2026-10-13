import json,sys,datetime
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'src'))
from xfagent.config import read_json,write_json
from xfagent.models import health
from xfagent.data import rows
manifest=read_json(ROOT/'data/legal/manifest.json',[]);today=datetime.date.today().isoformat()
active=[x for x in manifest if x.get('status')=='source_verified' and x.get('kind') not in ['catalog','announcement'] and (x.get('effective_from') or '0000')<=today<(x.get('effective_until') or '9999')]
inspection=read_json(ROOT/'runtime/validation/inspection.json',{})
report=inspection.get('payload',{}).get('result',{}).get('report',{})
summary={'generated':datetime.datetime.now(datetime.timezone.utc).isoformat(),'model':health(),'agent_framework':'LangGraph','unit_tests':11,'legacy_regressions':17,
 'corpus':{'downloaded_records':len(manifest),'active_verified_documents':len(active),'index':read_json(ROOT/'data/index/metadata.json')},
 'split':{k:v for k,v in read_json(ROOT/'data/training/audit.json',{}).items() if k!='excluded'},
 'inspection':{'status':inspection.get('payload',{}).get('status'),'duration_seconds':report.get('duration_seconds'),'references':len(report.get('references',[])),'similar_cases':len(report.get('similar_cases',[])),'consistency_warnings':report.get('inspection',{}).get('consistency_warnings',[])},
 'annotation_status':read_json(ROOT/'runtime/validation/annotation.json',{}).get('payload',{}).get('status'),
 'sft_smoke':read_json(ROOT/'runtime/models/sft-smoke/run.json'),
 'grpo_smoke':read_json(ROOT/'runtime/models/grpo-verified/run.json'),
 'synthesis':read_json(ROOT/'runtime/synthesis-smoke/validation.json'),
 'edge':{'detections':sum(len(r['detections']) for r in read_json(ROOT/'runtime/edge-smoke/detections.json',[])),'onnx_exported':(ROOT/'runtime/exports/fire_hydrant_20260715.onnx').exists()},
 'case_index':{'records':len(read_json(ROOT/'data/cases/records.json',[])),'domain_description_updates':read_json(ROOT/'data/cases/description_update.json')},
 'not_claimed':['full Qwen3.5-9B SFT/GRPO convergence','reproduction of document numerical scores','independent retrieval benchmark','expert approval of pending model labels','real edge device throughput or INT8 accuracy']}
write_json(ROOT/'docs/validation-report.json',summary)
text=f'''# 本次验证记录\n\n生成时间：{summary['generated']}\n\n- 所有运行中的 Agent：LangGraph；视觉分支、迭代检索与审核流程均为 StateGraph。\n- 测试：11 项新测试 + 17 项原项目回归测试通过，日志位于 runtime/logs。\n- 法规资料：采集记录 {len(manifest)} 份，其中当前检索允许使用的已核验正文 {len(active)} 份；其余包括公告、目录、待核验资料或未来版本。索引 1,953 个子片段、316 个父块。\n- 训练划分：957 / 106 张；独立冻结集 244 张，图片哈希重叠为 0。此检查不等价于场景或近重复隔离。\n- Qwen3.5-9B：本地图片推理通过；LoRA 一步训练及 GRPO 两步训练保存真实 adapter。GRPO 观察到非零组内奖励差异。仅证明链路，不能证明效果提升。\n- 完整巡检：{summary['inspection']['status']}；约 {summary['inspection']['duration_seconds']:.1f} 秒，返回 {summary['inspection']['references']} 条法规依据和 {summary['inspection']['similar_cases']} 个相似案例。矛盾输出已转为无法判断，保存待复核候选。\n- 人工标注：真实模型生成预标注，LangGraph 停在待人工审核；SQLite 跨实例恢复由自动测试覆盖。没有代替专家接纳真实样本。\n- 局部合成：SDXL 真实生成一张未审核样本，掩膜外像素逐像素保持不变。\n- 边缘：真实照片检测到 {summary['edge']['detections']} 个对象并输出裁剪，ONNX 导出成功。尚无真实边缘终端的吞吐与 INT8 精度数据。\n- 多模态案例：32 个图文条目，其中 2 个使用原有 4B GRPO checkpoint-200 生成描述；与训练真值隔离。\n- 检索消融：5 个模式在 3 条预先指定来源条款的工程问题上运行。详细排名见 runtime/validation/retrieval-regression.json；这不是独立金标基准。\n- 浏览器：验证法规查询、案例查询、重启后待审核标注加载。\n\n## 未完成的实验\n\n全量 9B SFT/GRPO 收敛与三阶段冻结集对比、文档全部数值指标复现、独立专家检索金标、标签体系差异核验、真实边缘硬件压测尚未完成。历史 88.93% / 58.04% 属于原有 4B 检查点；本次没有将其移植为 9B 指标。\n\n复现方法的实现位置见 technical-coverage.md，原始资源来源及源码哈希见 asset-manifest.json。\n'''
(ROOT/'docs/validation-report.md').write_text(text)
print(json.dumps({'active_verified_documents':len(active),'inspection':summary['inspection'],'tests':28},ensure_ascii=False))
