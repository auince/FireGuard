"""测试视觉模型 API 可用性"""
import requests
import json

# 测试端点
endpoints = {
    "qwen3-vl-4b-grpo": "http://127.0.0.1:8003",
    "multimodal": "http://127.0.0.1:8002"
}

print("检查模型服务状态:\n")

for name, url in endpoints.items():
    try:
        # 尝试健康检查
        response = requests.get(f"{url}/health", timeout=5)
        if response.status_code == 200:
            print(f"✓ {name}: 运行中")
            print(f"  响应: {response.text[:100]}")
        else:
            print(f"⚠ {name}: HTTP {response.status_code}")
    except requests.exceptions.ConnectionError:
        print(f"✗ {name}: 连接失败 (端口未开放或服务未启动)")
    except Exception as e:
        print(f"✗ {name}: {str(e)}")
    print()
