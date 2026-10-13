"""Render completed capacity measurements without treating them as quality evals."""
import json,argparse
from pathlib import Path

def main():
 p=argparse.ArgumentParser();p.add_argument('run',type=Path);a=p.parse_args();s=json.loads((a.run/'summary.json').read_text())
 if s['status']=='probing':raise ValueError('Probe is still active')
 lines=['# Qwen3.5-9B GRPO 显存与训练可行性实测','',f"开始：{s['started_at']}；结束：{s.get('finished_at')}。",'',
 '仅测试 GPU 0；测试期间暂停本项目9B推理服务。其他卡原有进程未停止。使用现有训练集中的4条合规和4条不合规数据，初始化适配器是此前只训练1步的SFT smoke产物。该试验验证执行能力和参数更新，不构成隐患识别效果评测。','',
 '## 资源快照','', '```text',s['gpu_before'].strip(),'```','',
 '## 训练配置与结果','', '| 配置 | 每题回答数 | 图像像素上限 | 梯度累积 | 梯度检查点 | 已完成更新步数 | GPU实测峰值GiB | PyTorch分配峰值GiB | 训练秒数 | 结果 |',
 '|---|---:|---:|---:|---|---:|---:|---:|---:|---|']
 for x in s['runs']:
  c=x.get('capacity',{});cfg=c.get('config',{});m=c.get('memory',{});steps=c.get('update_verification',{}).get('global_steps',0);runtime=c.get('metrics',{}).get('train_runtime')
  if not steps:
   f=a.run/x['name']/'steps.jsonl'
   if f.exists():steps=max(json.loads(l).get('step',0) for l in f.read_text().splitlines())
  lines.append(f"| {x['name']} | {cfg.get('num_generations')} | {cfg.get('max_pixels')} | {cfg.get('gradient_accumulation_steps')} | {cfg.get('gradient_checkpointing')} | {steps} | {x['peak_nvidia_smi_mib']/1024:.2f} | {m.get('peak_allocated_bytes',0)/2**30:.2f} | {runtime if runtime is not None else '未完成'} | {c.get('status','unknown')} |")
 lines+=['','GPU峰值来自每秒一次的nvidia-smi采样，可能漏掉极短瞬时峰值；PyTorch峰值来自CUDA分配器计数。GiB按1024³字节；服务器每卡可见46068 MiB，约44.99 GiB。失败配置的“分配峰值”不包括那次申请失败的内存。','',
 '共同设置：完整BF16基座、无量化；LoRA r=8、alpha=32、all-linear；单卡microbatch=1；最大输出512 tokens；学习率5e-6；每组目标2次优化器更新；beta=0.04；格式/标签F1/异常判断奖励权重为0.2/0.5/0.3；不用vLLM生成。',
 '', '图像像素上限由处理器设置，不代表每张图片都达到上限。具体输入token数、图像网格和实际输出长度保存在每组capacity.json和steps.jsonl。', '', '## 参数更新与奖励诊断','']
 for x in s['runs']:
  c=x.get('capacity',{});u=c.get('update_verification',{});logs=c.get('step_logs',[])
  lines += [f"### {x['name']}",'',f"参数规模：{c.get('parameters')}；更新校验：{u or '未完成'}。",'']
  if c.get('error'):lines += ['失败原因：'+c['error'],'']
  if logs:
   zero=[l['frac_reward_zero_std'] for l in logs if 'frac_reward_zero_std' in l];grads=[l['grad_norm'] for l in logs if 'grad_norm' in l]
   lengths=[l['completions/mean_length'] for l in logs if 'completions/mean_length' in l]
   lines += [f"组内奖励标准差为零的比例（逐步）：{zero}；梯度范数：{grads}；实际平均输出长度（逐步）：{lengths}。",'']
   if zero and all(v==1 for v in zero):lines += ['本组没有观察到组内奖励区分，更新不能作为任务奖励优化有效的证据，KL正则也会产生梯度。正式训练前需检查SFT起点、输出格式和奖励分布。','']
 lines += ['## 恢复与适用范围','',f"原推理服务恢复状态：{s.get('inference_restored',s.get('restore_error','未确认'))}",'',
 '成功仅说明这些图像/提示长度、LoRA秩、生成组大小和batch设置下，两步训练和权重保存可完成。不能据此保证更长上下文、更大图片、每题更多回答、原配置累积16或全参数GRPO均可运行。也未证明模型业务准确率提高。探针产物未替换在线模型。',
 '', '当前训练日志提示线性注意力采用PyTorch回退实现；这次记录的是现有环境性能，未安装新加速内核或对速度作额外调优。',
 '', '官方实现参考：[TRL GRPOTrainer](https://huggingface.co/docs/trl/grpo_trainer)。完整命令、版本、输入哈希、显存采样及权重更新量均保存在同目录。']
 (a.run/'REPORT.md').write_text('\n'.join(lines)+'\n');print(a.run/'REPORT.md')
if __name__=='__main__':main()
