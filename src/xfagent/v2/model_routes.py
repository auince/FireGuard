"""Opt-in role routing; default deployment remains the configured generator."""
import os
from .config import MODEL, MODEL_URL

ROLES = {'intent', 'rewrite', 'answer', 'verify', 'reflect', 'adapt', 'vision'}

def resolve(role='answer'):
    if role not in ROLES:
        raise ValueError('unknown model role')
    prefix = 'XF_' + role.upper()
    backend=os.getenv(prefix+'_BACKEND','chat')
    if backend not in {'chat','systemone'} or (backend=='systemone' and role!='intent'):
        raise ValueError('unsupported role backend')
    explicit = bool(os.getenv(prefix + '_MODEL_URL') or os.getenv(prefix + '_MODEL_NAME'))
    route={'role': role,'backend':backend,
            'min_probability':float(os.getenv(prefix+'_MIN_PROBABILITY','0.75')),
            'min_margin':float(os.getenv(prefix+'_MIN_MARGIN','0.15')), 'url': os.getenv(prefix + '_MODEL_URL', MODEL_URL).rstrip('/'),
            'name': os.getenv(prefix + '_MODEL_NAME', MODEL),
            'revision': os.getenv(prefix + '_MODEL_REVISION', 'unverified'),
            'supports_images': os.getenv(prefix + '_SUPPORTS_IMAGES',
                'false' if backend=='systemone' or role == 'intent' and explicit else 'true').lower() == 'true',
            'context_tokens': int(os.getenv(prefix + '_CONTEXT_TOKENS', '8192' if backend=='systemone' else '16384'))}
    if not 0<=route['min_probability']<=1 or not 0<=route['min_margin']<=1 or route['context_tokens']<2048:
        raise ValueError('invalid model routing limits')
    if backend=='systemone':route['supports_images']=False
    return route

def manifest():
    return {role: resolve(role) for role in sorted(ROLES)}
