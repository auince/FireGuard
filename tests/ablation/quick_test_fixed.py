"""快速测试两个视觉模型的 API - 修正版"""
import json
import time
import requests
from pathlib import Path

# 加载测试数据
test_data = []
with open('/tmp/xfagent_test_scenarios_200.jsonl', 'r') as f:
    for line in f:
        test_data.append(json.loads(line))

# 选取 10 个代表性场景
sample = test_data[:10]

print(f"\n{'='*70}")
print("XFAgent 消融实验 - 小样本验证测试")
print("对比 Qwen3-VL-32B 基础模型 vs Qwen3-VL-4B-GRPO 微调模型")
print(f"{'='*70}\n")
print(f"测试样本: {len(sample)} 个场景\n")

# 测试第一个数据的结构
first = sample[0]
print(f"数据字段: {list(first.keys())}\n")

results = {
    "qwen3-vl-4b-grpo": [],
    "metadata": {
        "test_time": time.strftime("%Y-%m-%d %H:%M:%S"),
        "sample_size": len(sample)
    }
}

# 测试 4B 微调模型
print("【模型】Qwen3-VL-4B-GRPO 微调模型")
print("-" * 70)
print("微调方法: SFT + GRPO 强化学习")
print("训练场景: 消防巡检（室内消火栓等）")
print("模型大小: 8.3GB 基础 + 127MB adapter")
print()

for idx, scenario in enumerate(sample, 1):
    # 适配实际字段名
    scenario_id = scenario.get('index', idx)
    check_scope = scenario.get('check_scope', 'N/A')
    conclusion = scenario.get('conclusion', 'N/A')
    image_path = scenario.get('image_path', '')
    
    print(f"场景 {idx}/{len(sample)}: index={scenario_id}")
    print(f"  检查范围: {check_scope}")
    print(f"  真实结论: {conclusion}")
    
    # 构造消防巡检专用提示词
    prompt = f"""请分析这张消防设施照片（{check_scope}），识别以下内容：

1. 设施类型（如：室内消火栓）
2. 检查的具体部位或范围
3. 发现的隐患或问题（如有）
4. 合规性判断（合规/不合规）

请简洁准确地描述。"""
    
    # 准备请求（适配 model_server 的格式）
    payload = {
        "messages": [
            {
                "role": "user", 
                "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {"url": f"file://{image_path}"}}
                ]
            }
        ],
        "max_tokens": 512,
        "temperature": 0.1
    }
    
    start = time.time()
    try:
        response = requests.post(
            "http://127.0.0.1:8003/v1/chat/completions",
            json=payload,
            timeout=30
        )
        latency = time.time() - start
        
        if response.status_code == 200:
            result = response.json()
            answer = result.get("choices", [{}])[0].get("message", {}).get("content", "")
            
            # 简单的隐患提取
            detected_issues = []
            issue_keywords = ['遮挡', '缺失', '破损', '不合规', '无', '未配备', '损坏', '丢失']
            for keyword in issue_keywords:
                if keyword in answer:
                    detected_issues.append(keyword)
            
            print(f"  ✓ 成功 ({latency:.2f}s)")
            print(f"  识别隐患: {', '.join(detected_issues) if detected_issues else '无明显隐患'}")
            print(f"  回复: {answer[:100]}...")
            
            results["qwen3-vl-4b-grpo"].append({
                "scenario_index": scenario_id,
                "check_scope": check_scope,
                "ground_truth": conclusion,
                "success": True,
                "latency": latency,
                "response": answer,
                "detected_issues": detected_issues
            })
        else:
            print(f"  ✗ HTTP {response.status_code}")
            print(f"     {response.text[:100]}")
            results["qwen3-vl-4b-grpo"].append({
                "scenario_index": scenario_id,
                "success": False,
                "error": f"HTTP {response.status_code}: {response.text[:100]}"
            })
    except Exception as e:
        print(f"  ✗ 错误: {str(e)[:80]}")
        results["qwen3-vl-4b-grpo"].append({
            "scenario_index": scenario_id,
            "success": False,
            "error": str(e)
        })
    
    print()

# 保存结果
output_path = "/tmp/ablation_4b_quick_test.json"
with open(output_path, 'w', encoding='utf-8') as f:
    json.dump(results, f, indent=2, ensure_ascii=False)

print(f"{'='*70}")
print("测试结果汇总 - Qwen3-VL-4B-GRPO")
print(f"{'='*70}\n")

model_4b = results["qwen3-vl-4b-grpo"]
success_4b = [r for r in model_4b if r.get("success")]

if success_4b:
    latencies = [r["latency"] for r in success_4b]
    all_issues = [issue for r in success_4b for issue in r.get("detected_issues", [])]
    
    print(f"成功率: {len(success_4b)}/{len(model_4b)} ({len(success_4b)/len(model_4b)*100:.1f}%)")
    print(f"\n性能指标:")
    print(f"  平均延迟: {sum(latencies)/len(latencies):.2f}s")
    print(f"  最快: {min(latencies):.2f}s")
    print(f"  最慢: {max(latencies):.2f}s")
    
    if all_issues:
        from collections import Counter
        issue_counts = Counter(all_issues)
        print(f"\n检测到的隐患类型 (Top 5):")
        for issue, count in issue_counts.most_common(5):
            print(f"  {issue}: {count}次")
else:
    print(f"⚠ 所有测试失败")
    print("失败原因:")
    for r in model_4b:
        if not r.get("success"):
            print(f"  - {r.get('error', 'Unknown error')}")

print(f"\n详细结果已保存: {output_path}")
print(f"\n{'='*70}")
print("说明: 32B 基础模型测试需要确认其 API 格式后进行")
print("本次先验证 4B 微调模型的可用性")
print(f"{'='*70}")
