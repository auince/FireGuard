"""
XFAgent 消融实验测试脚本
对比 Qwen3-VL-32B vs Qwen3-VL-4B-GRPO 在消防巡检场景的性能
"""
import json
import time
import requests
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Any
import statistics

# 模型配置
MODELS = {
    "qwen3-vl-32b": {
        "name": "Qwen3-VL-32B-Instruct",
        "api_url": "http://127.0.0.1:8002/v1/chat/completions",  # multimodal_server
        "description": "基础大模型 (63GB)"
    },
    "qwen3-vl-4b-grpo": {
        "name": "Qwen3-VL-4B-GRPO",
        "api_url": "http://127.0.0.1:8003/v1/chat/completions",
        "description": "消防巡检场景微调模型 (8.3GB + 127MB adapter)"
    }
}

class AblationTester:
    def __init__(self, test_data_path: str, output_dir: str):
        self.test_data_path = Path(test_data_path)
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        
        # 加载测试数据
        with open(self.test_data_path, 'r', encoding='utf-8') as f:
            self.test_scenarios = [json.loads(line) for line in f]
        
        print(f"✓ 加载了 {len(self.test_scenarios)} 个测试场景")
    
    def call_vision_model(self, model_key: str, image_path: str, prompt: str) -> Dict[str, Any]:
        """调用视觉模型 API"""
        model_config = MODELS[model_key]
        
        # 准备请求
        payload = {
            "model": model_config["name"],
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
        
        start_time = time.time()
        try:
            response = requests.post(
                model_config["api_url"],
                json=payload,
                timeout=60
            )
            latency = time.time() - start_time
            
            if response.status_code == 200:
                result = response.json()
                return {
                    "success": True,
                    "response": result["choices"][0]["message"]["content"],
                    "latency": latency,
                    "model": model_key
                }
            else:
                return {
                    "success": False,
                    "error": f"HTTP {response.status_code}: {response.text}",
                    "latency": latency,
                    "model": model_key
                }
        except Exception as e:
            return {
                "success": False,
                "error": str(e),
                "latency": time.time() - start_time,
                "model": model_key
            }
    
    def extract_hazards(self, response_text: str) -> List[str]:
        """从模型输出中提取隐患列表"""
        # 简单的关键词匹配提取
        hazards = []
        keywords = ['遮挡', '缺失', '破损', '不合规', '无', '未配备']
        
        for keyword in keywords:
            if keyword in response_text:
                hazards.append(keyword)
        
        return hazards
    
    def evaluate_scenario(self, scenario: Dict, model_key: str) -> Dict[str, Any]:
        """评估单个场景"""
        # 构造提示词
        prompt = f"""请分析这张消防设施照片，识别以下内容：
1. 设施类型（如：室内消火栓）
2. 检查范围（如：箱体外观、内部组件）
3. 存在的隐患（如果有）
4. 是否合规

请用简洁的语言描述。"""
        
        # 调用模型
        result = self.call_vision_model(
            model_key,
            scenario["image_path"],
            prompt
        )
        
        if not result["success"]:
            return {
                "scenario_id": scenario["id"],
                "model": model_key,
                "success": False,
                "error": result["error"],
                "latency": result["latency"]
            }
        
        # 提取模型识别的隐患
        predicted_hazards = self.extract_hazards(result["response"])
        ground_truth_hazards = scenario.get("hazard_labels", [])
        
        # 计算准确性
        correct_predictions = len(set(predicted_hazards) & set(ground_truth_hazards))
        precision = correct_predictions / len(predicted_hazards) if predicted_hazards else 0
        recall = correct_predictions / len(ground_truth_hazards) if ground_truth_hazards else 0
        f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0
        
        return {
            "scenario_id": scenario["id"],
            "model": model_key,
            "success": True,
            "latency": result["latency"],
            "response": result["response"],
            "predicted_hazards": predicted_hazards,
            "ground_truth_hazards": ground_truth_hazards,
            "metrics": {
                "precision": precision,
                "recall": recall,
                "f1": f1
            }
        }
    
    def run_test(self, sample_size: int = None, models: List[str] = None):
        """运行消融实验"""
        if models is None:
            models = list(MODELS.keys())
        
        if sample_size:
            scenarios = self.test_scenarios[:sample_size]
        else:
            scenarios = self.test_scenarios
        
        print(f"\n{'='*60}")
        print(f"开始消融实验测试")
        print(f"测试场景数: {len(scenarios)}")
        print(f"测试模型: {', '.join([MODELS[m]['description'] for m in models])}")
        print(f"{'='*60}\n")
        
        results = {model: [] for model in models}
        
        for idx, scenario in enumerate(scenarios, 1):
            print(f"\n进度: {idx}/{len(scenarios)} - 场景 {scenario['id']}")
            print(f"  检查范围: {scenario.get('check_scope', 'N/A')}")
            print(f"  结论: {scenario.get('conclusion', 'N/A')}")
            
            for model_key in models:
                print(f"  测试模型: {MODELS[model_key]['name']}...", end=' ', flush=True)
                result = self.evaluate_scenario(scenario, model_key)
                results[model_key].append(result)
                
                if result["success"]:
                    print(f"✓ ({result['latency']:.2f}s, F1: {result['metrics']['f1']:.3f})")
                else:
                    print(f"✗ {result['error']}")
        
        # 生成报告
        self.generate_report(results, scenarios)
    
    def generate_report(self, results: Dict[str, List[Dict]], scenarios: List[Dict]):
        """生成对比报告"""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        report_path = self.output_dir / f"ablation_report_{timestamp}.json"
        
        report = {
            "timestamp": timestamp,
            "test_size": len(scenarios),
            "models": {}
        }
        
        for model_key, model_results in results.items():
            successful = [r for r in model_results if r["success"]]
            
            if not successful:
                report["models"][model_key] = {
                    "name": MODELS[model_key]["name"],
                    "description": MODELS[model_key]["description"],
                    "success_rate": 0,
                    "error": "所有测试失败"
                }
                continue
            
            latencies = [r["latency"] for r in successful]
            f1_scores = [r["metrics"]["f1"] for r in successful]
            precisions = [r["metrics"]["precision"] for r in successful]
            recalls = [r["metrics"]["recall"] for r in successful]
            
            report["models"][model_key] = {
                "name": MODELS[model_key]["name"],
                "description": MODELS[model_key]["description"],
                "success_rate": len(successful) / len(model_results),
                "performance": {
                    "latency_mean": statistics.mean(latencies),
                    "latency_p50": statistics.median(latencies),
                    "latency_p95": sorted(latencies)[int(len(latencies) * 0.95)] if len(latencies) > 20 else max(latencies),
                    "latency_min": min(latencies),
                    "latency_max": max(latencies)
                },
                "accuracy": {
                    "f1_mean": statistics.mean(f1_scores),
                    "precision_mean": statistics.mean(precisions),
                    "recall_mean": statistics.mean(recalls)
                },
                "total_tests": len(model_results),
                "successful_tests": len(successful)
            }
        
        # 保存详细报告
        with open(report_path, 'w', encoding='utf-8') as f:
            json.dump(report, f, ensure_ascii=False, indent=2)
        
        # 打印摘要
        print(f"\n{'='*60}")
        print("消融实验结果摘要")
        print(f"{'='*60}")
        
        for model_key, stats in report["models"].items():
            print(f"\n【{stats['name']}】")
            print(f"  描述: {stats['description']}")
            print(f"  成功率: {stats['success_rate']*100:.1f}%")
            
            if 'performance' in stats:
                print(f"  \n  性能指标:")
                print(f"    平均延迟: {stats['performance']['latency_mean']:.2f}s")
                print(f"    P50 延迟: {stats['performance']['latency_p50']:.2f}s")
                print(f"    P95 延迟: {stats['performance']['latency_p95']:.2f}s")
                
                print(f"  \n  准确性指标:")
                print(f"    平均 F1 Score: {stats['accuracy']['f1_mean']:.3f}")
                print(f"    平均 Precision: {stats['accuracy']['precision_mean']:.3f}")
                print(f"    平均 Recall: {stats['accuracy']['recall_mean']:.3f}")
        
        print(f"\n{'='*60}")
        print(f"详细报告已保存: {report_path}")
        print(f"{'='*60}")

if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="XFAgent 消融实验测试")
    parser.add_argument("--test-data", default="/tmp/xfagent_test_scenarios_200.jsonl", help="测试数据路径")
    parser.add_argument("--output-dir", default="tests/ablation/results", help="输出目录")
    parser.add_argument("--sample-size", type=int, help="测试样本数量（默认全部）")
    parser.add_argument("--models", nargs="+", choices=list(MODELS.keys()), default=list(MODELS.keys()), help="要测试的模型")
    
    args = parser.parse_args()
    
    tester = AblationTester(args.test_data, args.output_dir)
    tester.run_test(sample_size=args.sample_size, models=args.models)
