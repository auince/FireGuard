<div align="center">

# 🔥 FireGuard: 智能消防巡检与合规审查多模态智能体
**Fire Inspection Assistant with Governed LangGraph Workflows, Evidence-Grounded RAG, Human Review, Memory & Feedback-Driven Policy Iteration**

[![Python 3.10+](https://img.shields.io/badge/Python-3.10%2B-blue.svg?logo=python&logoColor=white)](https://www.python.org/)
[![LangGraph](https://img.shields.io/badge/Orchestration-LangGraph-FF6F00.svg?logo=langchain&logoColor=white)](https://github.com/langchain-ai/langgraph)
[![Qwen3.5-VL](https://img.shields.io/badge/VLM-Qwen3.5--9B-7B2CBF.svg)](https://github.com/QwenLM/Qwen2.5-VL)
[![RLVR-GRPO](https://img.shields.io/badge/Post--Training-SFT%20%2B%20GRPO-success.svg)]()
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

[**📖 项目背景**](#-项目背景与核心痛点) | [**✨ 核心特性**](#-核心特性-key-features) | [**🏗️ 系统架构**](#️-系统架构与工作流) | [**📊 实验与评测**](#-性能评测与实验结果) | [**🚀 快速开始**](#-快速开始-quick-start)

</div>

---

## 📖 项目背景与核心痛点

在真实的消防安全巡检与执法场景中，传统人工巡检效率低、标准执行不一，而直接应用通用多模态大模型（VLM）及自由式 Agent（如 ReAct）又面临三大致命瓶颈：

| 传统/通用大模型方案的痛点 ❌ | **FireGuard 的破局方案** ✅ |
| :--- | :--- |
| **1. 细粒度隐患识别难 & 罕见样本稀缺**<br>通用 VLM 缺乏消防专业视觉先验，合规判定准确率仅 **53.12%**，且输出格式极不稳定。 | **人机协同数据合成 + SFT & GRPO 后训练**<br>结合实采与局部缺陷仿真构建高质量数据集；通过 LoRA SFT 与基于可验证奖励的 **GRPO** 强化学习，将识别准确率拉升至 **90.63%**。 |
| **2. 法规条款复杂 & 检索严重幻觉**<br>消防规范层级深、跨度大，基础稠密向量检索 Top-1 命中率仅 **61.51%**，模型常“张冠李戴”编造法条。 | **Evidence-Grounded 多模态混合 RAG**<br>构建目录层级驱动的“标题-正文”双向量索引与父子分块；融合 BM25 + 稠密检索 + RRF 重排与 Agent 迭代改写，Top-5 准确率达 **92.06%**。 |
| **3. 自由 Agent 不可控 & 高风险场景零容错**<br>ReAct 等自由推理易陷入死循环，且消防整改报告具有严肃法律与安全效力，绝不允许“带病输出”。 | **Governed LangGraph + HITL + 记忆与策略飞轮**<br>将工作流收敛为受控状态图（StateGraph），内置置信度路由与**人工审核（Human-in-the-Loop）**中断机制，并利用专家反馈驱动线上记忆更新与离线策略迭代。 |

---

## ✨ 核心特性 (Key Features)

### 🧭 1. 受控图工作流编排 (Governed LangGraph Workflows)
摒弃不可控的开放式循环，采用强状态约束的有向图架构（`StateGraph`）：
- **确定性阶段流转**：严格遵循 `视觉隐患感知` $\rightarrow$ `查询重写与法规检索` $\rightarrow$ `证据相关性核验 (Grader)` $\rightarrow$ `结构化整改报告生成` 的受控管线。
- **自适应防死循环**：内置最大重试跳数（Max Retries）与条件边（Conditional Edges）降级兜底策略，确保工业级高可用。

### 📚 2. 证据锚定检索增强 (Evidence-Grounded RAG)
整合 70+ 份国家及地方消防技术规范、标准及历史执法案例：
- **目录层级驱动的双向量索引**：构建“章节标题 + 条款正文”双向量表征，结合**父子文档分块（Parent-Child Chunking）**，做到“小块精准检索、大块完整上下文注入”，保留法条严密的上下文逻辑。
- **多路混合检索与重排**：融合稀疏检索（BM25 精准匹配消防专有名词/国标编号）与稠密向量检索（语义理解），通过 **RRF (Reciprocal Rank Fusion)** 算法重排序，并支持图文双向索引。
- **Agentic Query Rewriting**：当检索证据置信度不足时，由 Agent 自动提炼视觉特征并改写专业法学术语，触发多跳迭代检索，确保每一条隐患结论都有真实法条原文（Citation）强力支撑。

### 🛡️ 3. 人机协同审核与长短期记忆 (Human Review & Memory)
- **Human-in-the-Loop (HITL)**：基于 LangGraph `interrupt` 与持久化 Checkpointer，当遇到低置信度隐患判定、罕见复合型缺陷或重大火灾风险项时，工作流自动挂起并推送至消防专家审核台，支持专家在线增删法条、修正结论后无缝恢复执行。
- **双层记忆机制 (Dual-Layer Memory)**：
  - **短期会话记忆 (Thread-level)**：维护单次多图巡检上下文与多轮追问状态。
  - **长期经验记忆 (Cross-thread Store)**：动态沉淀高频误判案例与特定建筑场所的历史隐患档案，推理时作为动态 Few-shot 样本注入，实现“越用越聪明”。

### 🔄 4. 反馈驱动的策略迭代闭环 (Feedback-Driven Policy Iteration)
打通从“线上人机交互”到“底层策略进化”的数据飞轮：
- **人机协同数据 Pipeline**：基于 1,196 组实采巡检样本 + 开源图像 + 局部缺陷仿真补充罕见异常，采用“人工提示+模型生成”、“模型预标注+人工复审”两阶段流程，统一专业标签与描述规范。
- **线上轻量级策略热更新**：将 HITL 阶段专家的驳回原因与纠偏记录实时转化为路由规则调整与 Prompt 负例约束。
- **离线重量级模型后训练 (SFT + RLVR/GRPO)**：
  - **第一阶段 (SFT)**：基于 `Qwen3.5-9B` 进行 LoRA 监督微调，注入消防领域细粒度视觉判别与结构化报告生成能力。
  - **第二阶段 (RLVR via GRPO)**：利用沉淀的专家反馈数据，精心设计**格式合规性（Format）、隐患标签准确率（Hazard Tags）、最终合规结论（Final Verdict）**三类可验证奖励函数（Verifiable Rewards），通过 **GRPO** 算法强化模型的细粒度缺陷识别能力与前后逻辑一致性。

---

## 🏗️ 系统架构与工作流

```mermaid
graph TD
    A[📸 巡检图像 / 现场描述输入] --> B(👁️ VLM 视觉隐患感知节点<br/>Qwen3.5-9B SFT+GRPO)
    B --> C{🔍 隐患特征提取 & 路由}
    C -->|发现疑似隐患| D[✍️ Agent 查询改写<br/>Query Rewriter]
    C -->|完全合规 & 高置信度| I[📝 生成合规巡检报告]
    
    subgraph 📚 Evidence-Grounded RAG 引擎
        D --> E[🗂️ 混合检索: BM25 + 稠密向量<br/>标题-正文双索引 & 父子分块]
        E --> F[⚖️ RRF 重排 & 图文双向匹配]
    end
    
    F --> G{🎯 证据充分性核验<br/>Evidence Grader}
    G -->|证据不足 & 未达最大步数| D
    G -->|证据充分| H{🛡️ 风险等级与置信度评估}
    G -->|达到最大重试| J
    
    H -->|高置信度 & 常规隐患| I[📝 生成证据锚定结构化报告]
    H -->|低置信度 / 重大消防隐患| J((⏸️ Human Review 人工审核中断))
    
    J -->|👨‍🚒 专家修正标签/法条依据| I
    J -.->|💾 收集专家纠偏反馈| K[(🧠 长期记忆库 & 离线回流池)]
    
    K -.->|Few-shot 动态注入| B
    K -.->|构建三类可验证奖励 RLVR<br/>Format / Tag / Conclusion| L[🚀 GRPO 强化学习策略迭代]
    L -.->|权重更新| B
