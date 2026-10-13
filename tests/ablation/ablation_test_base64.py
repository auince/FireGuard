"""
XFAgent 消融实验 - Qwen3-VL-4B-GRPO vs Qwen3-VL-32B
支持 base64 图像编码，完整日志记录
"""
import json
import time
import requests
import base64
from pathlib import Path
from datetime import datetime
from collections import Counter
import sys

# 创建日志目录
log_dir = Path("tests/ablation/logs")
log_dir.mkdir(parents=True, exist_ok=True)

# 日志文件
timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
log_file = log_dir / f"ablation_test_{timestamp}.log"

def log(message, to_console=True, to_file=True):
    """写日志到控制台和文件"""
    if to_console:
        print(message)
    if to_file:
        with open(log_file, 'a', encoding='utf-8') as f:
            f.write(message + "\n")

log(f"{'='*70}")
log(f"XFAgent 消融实验测试")
log(f"测试时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
log(f"日志文件: {log_file}")
log(f"{'='*70}\n")

# 加载测试数据
log("加载测试数据...")
test_data = []
with open('/tmp/xfagent_test_scenarios_200.jsonl', 'r', encoding='utf-8') as f:
    for line in f:
        test_data.append(json.loads(line))

# 选择样本大小
SAMPLE_SIZE = int(sys.argv[1]) if len(sys.argv) > 1 else 10
sample = test_data[:SAMPLE_SIZE]

log(f"✓ 加载了 {len(test_data)} 个场景，选取 {SAMPLE_SIZE} 个进行测试\n")

# 检查第一个场景的数据结构
first = sample[0]
log(f"数据结构: {list(first.keys())}")
log(f"示例场景: {json.dumps(first, ensure_ascii=False, indent=2)[:300]}...\n")

def encode_image_base64(image_path):
    """将图像编码为 base64"""
    try:
        with open(image_path, 'rb') as f:
            return base64.b64encode(f.read()).decode('utf-8')
    except Exception as e:
        log(f"  ✗ 图像编码失败: {e}")
        return None

def call_vision_model(model_name, api_url, image_path, prompt, scenario_idx):
    """调用视觉模型 API"""
    # 编码图像
    image_base64 = encode_image_base64(image_path)
    if not image_base64:
        return {"success": False, "error": "图像编码失败"}
    
    # 构造请求
    payload = {
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:image/jpeg;base64,{image_base64}"
                        }
                    }
                ]
            }
        ],
        "max_tokens": 512,
        "temperature": 0.1
    }
    
    start = time.time()
    try:
        response = requests.post(api_url, json=payload, timeout=60)
        latency = time.time() - start
        
        # 记录详细的请求日志
        log(f"  [API 请求] 场景 {scenario_idx}, 延迟: {latency:.2f}s", to_console=False)
        log(f"  [响应状态] HTTP {response.status_code}", to_console=False)
        
        if response.status_code == 200:
            result = response.json()
            answer = result.get("choices", [{}])[0].get("message", {}).get("content", "")
            
            return {
                "success": True,
                "response": answer,
                "latency": latency
            }
        else:
            error_msg = f"HTTP {response.status_code}: {response.text[:200]}"
            log(f"  [错误] {error_msg}", to_console=False)
            return {
                "success": False,
                "error": error_msg,
                "latency": latency
            }
    except Exception as e:
        latency = time.time() - start
        error_msg = str(e)
        log(f"  [异常] {error_msg}", to_console=False)
        return {
            "success": False,
            "error": error_msg,
            "latency": latency
        }

# 准备结果存储
results = {
    "metadata": {
        "test_time": timestamp,
        "sample_size": SAMPLE_SIZE,
        "total_scenarios": len(test_data)
    },
    "models": {
        "qwen3-vl-4b-grpo": {
            "name": "Qwen3-VL-4B-GRPO",
            "description": "消防巡检场景微调模型 (SFT + GRPO)",
            "api_url": "http://127.0.0.1:8003/v1/chat/completions",
            "results": []
        }
    }
}

# 开始测试
log(f"{'='*70}")
log(f"开始测试: Qwen3-VL-4B-GRPO 微调模型")
log(f"{'='*70}\n")

for idx, scenario in enumerate(sample, 1):
    scenario_id = scenario.get('scenario_id', idx)
    category = scenario.get('category', 'unknown')
    
    # 从 metadata 中提取信息
    metadata = scenario.get('metadata', {})
    check_scope = metadata.get('check_scope', 'N/A')
    conclusion = metadata.get('conclusion', 'N/A')
    
    # 从 input 中提取图像路径
    input_data = scenario.get('input', {})
    image_path = input_data.get('image_path', '')
    
    log(f"[{idx}/{SAMPLE_SIZE}] 场景 {scenario_id}")
    log(f"  类别: {category}")
    log(f"  检查范围: {check_scope}")
    log(f"  真实结论: {conclusion}")
    log(f"  图像: {Path(image_path).name if image_path else 'N/A'}")
    
    if not image_path or not Path(image_path).exists():
        log(f"  ✗ 图像文件不存在: {image_path}\n")
        results["models"]["qwen3-vl-4b-grpo"]["results"].append({
            "scenario_id": scenario_id,
            "success": False,
            "error": "图像文件不存在"
        })
        continue
    
    # 构造提示词
    prompt = f"""请分析这张消防设施照片，识别以下内容：

1. 设施类型（如：室内消火栓）
2. 检查的具体范围（如：{check_scope}）
3. 发现的隐患或问题（如有）
4. 合规性判断

请用简洁准确的语言描述。"""
    
    # 调用模型
    result = call_vision_model(
        "Qwen3-VL-4B-GRPO",
        "http://127.0.0.1:8003/v1/chat/completions",
        image_path,
        prompt,
        idx
    )
    
    if result["success"]:
        response_text = result["response"]
        
        # 提取隐患关键词
        hazard_keywords = ['遮挡', '缺失', '破损', '不合规', '无', '未配备', '损坏', '丢失', 
                          '不符', '缺少', '缺乏', '失效', '老化', '褪色']
        detected_issues = [kw for kw in hazard_keywords if kw in response_text]
        
        log(f"  ✓ 成功 ({result['latency']:.2f}s)")
        log(f"  识别隐患: {', '.join(detected_issues) if detected_issues else '无明显隐患'}")
        log(f"  回复: {response_text[:80]}...")
        
        results["models"]["qwen3-vl-4b-grpo"]["results"].append({
            "scenario_id": scenario_id,
            "category": category,
            "check_scope": check_scope,
            "ground_truth": conclusion,
            "success": True,
            "latency": result["latency"],
            "response": response_text,
            "detected_issues": detected_issues
        })
    else:
        log(f"  ✗ 失败: {result['error'][:80]}")
        results["models"]["qwen3-vl-4b-grpo"]["results"].append({
            "scenario_id": scenario_id,
            "success": False,
            "error": result["error"]
        })
    
    log("")

# 生成统计报告
log(f"{'='*70}")
log(f"测试结果汇总")
log(f"{'='*70}\n")

model_results = results["models"]["qwen3-vl-4b-grpo"]["results"]
successful = [r for r in model_results if r.get("success")]
failed = [r for r in model_results if not r.get("success")]

log(f"Qwen3-VL-4B-GRPO 微调模型:")
log(f"  总测试: {len(model_results)} 个场景")
log(f"  成功: {len(successful)} ({len(successful)/len(model_results)*100:.1f}%)")
log(f"  失败: {len(failed)} ({len(failed)/len(model_results)*100:.1f}%)")

if successful:
    latencies = [r["latency"] for r in successful]
    log(f"\n  性能指标:")
    log(f"    平均延迟: {sum(latencies)/len(latencies):.2f}s")
    log(f"    最快: {min(latencies):.2f}s")
    log(f"    最慢: {max(latencies):.2f}s")
    log(f"    P50: {sorted(latencies)[len(latencies)//2]:.2f}s")
    
    # 隐患统计
    all_issues = [issue for r in successful for issue in r.get("detected_issues", [])]
    if all_issues:
        issue_counts = Counter(all_issues)
        log(f"\n  检测到的隐患类型 (Top 5):")
        for issue, count in issue_counts.most_common(5):
            log(f"    {issue}: {count} 次 ({count/len(successful)*100:.1f}%)")

if failed:
    log(f"\n  失败原因:")
    error_counts = Counter([r.get("error", "Unknown")[:50] for r in failed])
    for error, count in error_counts.most_common(3):
        log(f"    {error}: {count} 次")

# 保存详细结果
output_file = f"tests/ablation/results/ablation_4b_results_{timestamp}.json"
Path("tests/ablation/results").mkdir(parents=True, exist_ok=True)
with open(output_file, 'w', encoding='utf-8') as f:
    json.dump(results, f, indent=2, ensure_ascii=False)

log(f"\n{'='*70}")
log(f"详细结果已保存: {output_file}")
log(f"完整日志已保存: {log_file}")
log(f"{'='*70}")
