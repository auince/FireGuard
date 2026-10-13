#!/usr/bin/env python3
"""
BGE-M3 Embedding 服务
提供 HTTP API 接口供 XFAgent 调用
"""
from flask import Flask, request, jsonify
from sentence_transformers import SentenceTransformer
import numpy as np
import os

app = Flask(__name__)

# 加载模型
model_path = os.getenv('XF_EMBEDDING_MODEL', '/opt/models/bge-m3')
device = os.getenv('XF_EMBEDDING_DEVICE', 'cuda')

print(f"加载 BGE-M3 模型: {model_path}")
print(f"使用设备: {device}")

model = SentenceTransformer(model_path, device=device)
print("✓ 模型加载完成")

@app.route('/embed', methods=['POST'])
def embed():
    data = request.json
    texts = data.get('texts', [])
    
    if not texts:
        return jsonify({'error': 'No texts provided'}), 400
    
    # 生成 embeddings
    embeddings = model.encode(texts, normalize_embeddings=True)
    vectors = embeddings.tolist()
    
    return jsonify({'vectors': vectors})

@app.route('/health', methods=['GET'])
def health():
    return jsonify({'status': 'ok', 'model': model_path, 'device': device})

if __name__ == '__main__':
    app.run(host='127.0.0.1', port=8001, threaded=True)
