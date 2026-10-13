"""快速测试两个视觉模型的 API"""
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

print(f"\n{'='*60}")
print("XFAgent 模型对比测试 - 小样本验证")
print(f"{'='*60}\n")
print(f"测试样本: {len(sample)} 个场景\n")

results = {
    "qwen3-vl-4b-grpo": [],
    "qwen3-vl-32b": []
}

# 测试 4B 微调模型
print("【测试 1/2】Qwen3-VL-4B-GRPO 微调模型")
print("-" * 60)

for idx, scenario in enumerate(sample, 1):
    print(f"\n场景 {idx}/{len(sample)}: {scenario['id']}")
    print(f"  检查范围: {scenario.get('check_scope', 'N/A')}")
    
    # 构造请求
    prompt = f"""请分析这张消防设施照片，识别：
1. 设施类型
2. 检查范围
3. 存在的隐患
4. 是否合规

简洁描述即可。"""
    
    payload = {
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {"url": f"file://{scenario['image_path']}"}}
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
            print(f"  ✓ 成功 ({latency:.2f}s)")
            print(f"  回复: {answer[:80]}...")
            
            results["qwen3-vl-4b-grpo"].append({
                "scenario_id": scenario["id"],
                "success": True,
                "latency": latency,
                "response": answer
            })
        else:
            print(f"  ✗ HTTP {response.status_code}")
            results["qwen3-vl-4b-grpo"].append({
                "scenario_id": scenario["id"],
                "success": False,
                "error": f"HTTP {response.status_code}"
            })
    except Exception as e:
        print(f"  ✗ {str(e)[:50]}")
        results["qwen3-vl-4b-grpo"].append({
            "scenario_id": scenario["id"],
            "success": False,
            "error": str(e)
        })

print(f"\n{'='*60}")
print("【测试 2/2】Qwen3-VL-32B 基础模型")
print("-" * 60)
print("\n注: 32B 模型需要确认 API 端点和格式...")
print("目前 multimodal_server 的接口可能与标准 OpenAI 格式不同")

# 保存结果
output_path = "/tmp/ablation_quick_test_results.json"
with open(output_path, 'w') as f:
    json.dump(results, f, indent=2, ensure_ascii=False)

print(f"\n{'='*60}")
print("测试结果汇总")
print(f"{'='*60}\n")

# 统计 4B 微调模型
model_4b = results["qwen3-vl-4b-grpo"]
success_4b = [r for r in model_4b if r.get("success")]
if success_4b:
    latencies = [r["latency"] for r in success_4b]
    print(f"Qwen3-VL-4B-GRPO:")
    print(f"  成功率: {len(success_4b)}/{len(model_4b)} ({len(success_4b)/len(model_4b)*100:.1f}%)")
    print(f"  平均延迟: {sum(latencies)/len(latencies):.2f}s")
    print(f"  最快/最慢: {min(latencies):.2f}s / {max(latencies):.2f}s")
else:
    print(f"Qwen3-VL-4B-GRPO: 所有测试失败")

print(f"\n结果已保存: {output_path}")
