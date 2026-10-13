"""Explicit model clients. Never substitute mocked completions for unavailable models."""
import json
import re
import requests
from .config import settings

class ModelUnavailable(RuntimeError):
    pass

def health():
    s = settings()
    try:
        r = requests.get(s['base_url'].rstrip('/') + '/models', timeout=3,
                         headers={'Authorization': 'Bearer ' + s['api_key']})
        r.raise_for_status()
        names = [x['id'] for x in r.json().get('data', [])]
        return {'available': s['model'] in names, 'configured_model': s['model'], 'served_models': names}
    except (requests.RequestException, ValueError) as e:
        return {'available': False, 'configured_model': s['model'], 'reason': type(e).__name__}

def complete(prompt, image=None, system=None):
    s = settings()
    content = [{'type': 'text', 'text': prompt}]
    if image:
        content.append({'type': 'image_url', 'image_url': {'url': image}})
    messages = ([{'role': 'system', 'content': system}] if system else []) + [{'role': 'user', 'content': content}]
    try:
        r = requests.post(s['base_url'].rstrip('/') + '/chat/completions', timeout=(5, 180),
                          headers={'Authorization': 'Bearer ' + s['api_key']},
                          json={'model': s['model'], 'messages': messages, 'temperature': 0,
                                'max_tokens': 1024, 'stream': False})
        if not r.ok:
            raise ModelUnavailable('模型服务错误：'+str(r.json().get('error',{}))[:350])
        return r.json()['choices'][0]['message']['content']
    except (requests.RequestException, KeyError, ValueError) as e:
        raise ModelUnavailable(f'模型调用失败：{type(e).__name__}') from e

def json_response(text):
    text = re.sub(r'<think>.*?</think>', '', text, flags=re.S).strip()
    if text.startswith('```'):
        text = re.sub(r'^```(?:json)?\s*|\s*```$', '', text)
    return json.loads(text)
