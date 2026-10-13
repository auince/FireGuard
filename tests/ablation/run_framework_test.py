#!/usr/bin/env python3
"""
XFAgent 完整框架测试脚本
测试流程: KEV-4B (意图识别) -> 32B VLM (视觉分析)
"""
import json
import time
import base64
import requests
from pathlib import Path
from datetime import datetime
from collections import Counter
import statistics

class FrameworkTester:
    def __init__(self, kev_url, vlm_url, test_data_path):
        self.kev_url = kev_url
        self.vlm_url = vlm_url
        self.test_data_path = test_data_path
        self.results = []
        
    def load_test_data(self):
        """加载测试数据"""
        scenarios = []
        with open(self.test_data_path, 'r', encoding='utf-8') as f:
            for line in f:
                if line.strip():
                    scenarios.append(json.loads(line))
        return scenarios
    
    def encode_image(self, image_path):
        """将图片编码为base64"""
        with open(image_path, 'rb') as f:
            return base64.b64encode(f.read()).decode('utf-8')
    
    def call_kev_api(self, image_b64, query, scene):
        """调用KEV-4B进行意图识别"""
        try:
            # 构造KEV输入
            prompt = f"""分析以下消防巡检场景：

查询: {query}

场景信息:
- 设施类型: {scene.get('facility_type', 'unknown')}
- 位置: {scene.get('location', 'unknown')}
- 组件: {', '.join(scene.get('components', []))}

请识别:
1. 检查意图和范围
2. 主要关注点
3. 改写更精确的查询语句"""

            response = requests.post(
                f"{self.kev_url}/v1/chat/completions",
                json={
                    "model": "xf-kev-4b",
                    "messages": [
                        {
                            "role": "user",
                            "content": [
                                {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{image_b64}"}},
                                {"type": "text", "text": prompt}
                            ]
                        }
                    ],
                    "max_tokens": 500,
                    "temperature": 0.1
                },
                timeout=30
            )
            
            if response.status_code == 200:
                result = response.json()
                return {
                    "success": True,
                    "output": result['choices'][0]['message']['content']
                }
            else:
                return {
                    "success": False,
                    "error": f"HTTP {response.status_code}: {response.text}"
                }
                
        except Exception as e:
            return {
                "success": False,
                "error": str(e)
            }
    
    def call_32b_vlm_api(self, image_b64, kev_output, original_query):
        """调用32B VLM进行视觉分析"""
        try:
            # 使用KEV输出增强的查询
            enhanced_prompt = f"""请对消防设施进行详细检查。

原始查询: {original_query}

意图分析结果: {kev_output}

请提供:
1. 合规判断（合规/不合规）
2. 检测到的隐患类型（如：遮挡、损坏、缺失、缺少等）
3. 详细分析和建议"""

            response = requests.post(
                f"{self.vlm_url}/v1/chat/completions",
                json={
                    "model": "xf-qwen3-vl-32b",
                    "messages": [
                        {
                            "role": "user",
                            "content": [
                                {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{image_b64}"}},
                                {"type": "text", "text": enhanced_prompt}
                            ]
                        }
                    ],
                    "max_tokens": 800,
                    "temperature": 0.1
                },
                timeout=60
            )
            
            if response.status_code == 200:
                result = response.json()
                return {
                    "success": True,
                    "output": result['choices'][0]['message']['content']
                }
            else:
                return {
                    "success": False,
                    "error": f"HTTP {response.status_code}: {response.text}"
                }
                
        except Exception as e:
            return {
                "success": False,
                "error": str(e)
            }
    
    def extract_issues(self, text):
        """从输出文本中提取隐患类型"""
        keywords = ['不符', '损坏', '缺失', '缺少', '遮挡', '破损', '锈蚀', '老化']
        detected = []
        text_lower = text.lower()
        for keyword in keywords:
            if keyword in text:
                detected.append(keyword)
        return detected
    
    def test_scenario(self, scenario):
        """测试单个场景"""
        scenario_id = scenario['scenario_id']
        print(f"\n{'='*60}")
        print(f"测试场景: {scenario_id}")
        print(f"{'='*60}")
        
        start_time = time.time()
        
        # 读取并编码图片
        image_path = scenario['input']['image_path']
        try:
            image_b64 = self.encode_image(image_path)
        except Exception as e:
            return {
                'scenario_id': scenario_id,
                'success': False,
                'error': f"图片加载失败: {str(e)}"
            }
        
        # 步骤1: KEV-4B意图识别
        print("步骤1: KEV-4B意图识别...")
        kev_start = time.time()
        kev_result = self.call_kev_api(
            image_b64,
            scenario['input']['query'],
            scenario['input']['scene']
        )
        kev_latency = time.time() - kev_start
        
        if not kev_result['success']:
            return {
                'scenario_id': scenario_id,
                'success': False,
                'error': f"KEV-4B调用失败: {kev_result['error']}",
                'kev_latency': kev_latency
            }
        
        print(f"  ✓ KEV-4B完成 ({kev_latency:.2f}s)")
        
        # 步骤2: 32B VLM视觉分析
        print("步骤2: 32B VLM视觉分析...")
        vlm_start = time.time()
        vlm_result = self.call_32b_vlm_api(
            image_b64,
            kev_result['output'],
            scenario['input']['query']
        )
        vlm_latency = time.time() - vlm_start
        
        if not vlm_result['success']:
            return {
                'scenario_id': scenario_id,
                'success': False,
                'error': f"32B VLM调用失败: {vlm_result['error']}",
                'kev_latency': kev_latency,
                'vlm_latency': vlm_latency
            }
        
        print(f"  ✓ 32B VLM完成 ({vlm_latency:.2f}s)")
        
        total_latency = time.time() - start_time
        
        # 提取隐患
        detected_issues = self.extract_issues(vlm_result['output'])
        
        print(f"  总延迟: {total_latency:.2f}s")
        print(f"  检测到的隐患: {', '.join(detected_issues) if detected_issues else '无'}")
        
        return {
            'scenario_id': scenario_id,
            'category': scenario.get('category', 'unknown'),
            'success': True,
            'kev_latency': kev_latency,
            'vlm_latency': vlm_latency,
            'total_latency': total_latency,
            'kev_output': kev_result['output'],
            'vlm_output': vlm_result['output'],
            'detected_issues': detected_issues,
            'expected_output': scenario.get('expected_output', {})
        }
    
    def run_tests(self, limit=None):
        """运行所有测试"""
        print("\n" + "="*70)
        print("XFAgent 完整框架测试")
        print("="*70)
        print(f"\n测试时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"KEV-4B URL: {self.kev_url}")
        print(f"32B VLM URL: {self.vlm_url}")
        print(f"测试数据: {self.test_data_path}")
        
        scenarios = self.load_test_data()
        if limit:
            scenarios = scenarios[:limit]
        
        print(f"\n总场景数: {len(scenarios)}")
        print(f"\n开始测试...\n")
        
        for i, scenario in enumerate(scenarios, 1):
            print(f"\n[{i}/{len(scenarios)}]", end=" ")
            result = self.test_scenario(scenario)
            self.results.append(result)
            
            # 每10个场景保存一次
            if i % 10 == 0:
                self.save_results()
        
        # 最终保存
        self.save_results()
        
        # 生成汇总报告
        self.print_summary()
    
    def save_results(self):
        """保存测试结果"""
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        output_file = f"results/framework_test_results_{timestamp}.json"
        
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump({
                'metadata': {
                    'test_time': datetime.now().isoformat(),
                    'kev_url': self.kev_url,
                    'vlm_url': self.vlm_url,
                    'total_scenarios': len(self.results)
                },
                'results': self.results
            }, f, ensure_ascii=False, indent=2)
        
        print(f"\n结果已保存: {output_file}")
    
    def print_summary(self):
        """打印测试汇总"""
        print("\n" + "="*70)
        print("测试结果汇总")
        print("="*70)
        
        success = [r for r in self.results if r.get('success')]
        failed = [r for r in self.results if not r.get('success')]
        
        print(f"\n总测试: {len(self.results)} 个场景")
        print(f"成功: {len(success)} ({len(success)/len(self.results)*100:.1f}%)")
        print(f"失败: {len(failed)} ({len(failed)/len(self.results)*100:.1f}%)")
        
        if success:
            kev_latencies = [r['kev_latency'] for r in success]
            vlm_latencies = [r['vlm_latency'] for r in success]
            total_latencies = [r['total_latency'] for r in success]
            
            print(f"\n性能指标:")
            print(f"  KEV-4B平均延迟: {statistics.mean(kev_latencies):.2f}s")
            print(f"  32B VLM平均延迟: {statistics.mean(vlm_latencies):.2f}s")
            print(f"  端到端平均延迟: {statistics.mean(total_latencies):.2f}s")
            print(f"  端到端中位数: {statistics.median(total_latencies):.2f}s")
            print(f"  最快: {min(total_latencies):.2f}s")
            print(f"  最慢: {max(total_latencies):.2f}s")
            
            # 隐患统计
            all_issues = []
            for r in success:
                all_issues.extend(r.get('detected_issues', []))
            
            if all_issues:
                issue_counts = Counter(all_issues)
                print(f"\n检测到的隐患类型 (Top 5):")
                for issue, count in issue_counts.most_common(5):
                    print(f"  {issue}: {count} 次 ({count/len(success)*100:.1f}%)")
        
        print("\n" + "="*70)

if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description='XFAgent完整框架测试')
    parser.add_argument('--kev-url', default='http://127.0.0.1:8006', help='KEV-4B服务URL')
    parser.add_argument('--vlm-url', default='http://127.0.0.1:8004', help='32B VLM服务URL')
    parser.add_argument('--data', default='/tmp/xfagent_test_scenarios_200.jsonl', help='测试数据路径')
    parser.add_argument('--limit', type=int, help='限制测试场景数量')
    
    args = parser.parse_args()
    
    tester = FrameworkTester(args.kev_url, args.vlm_url, args.data)
    tester.run_tests(limit=args.limit)
