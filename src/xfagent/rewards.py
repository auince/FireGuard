"""Document's three verifiable objectives, using xfLLM's canonical label parser."""
import sys
from .config import ROOT
sys.path.insert(0,str(ROOT/'vendor/xfllm/scripts/rl_hydrant'))
from hydrant_rewards import parse_answer,completion_text,ALL_LABELS
from hydrant_rewards_v4 import format_reward

def label_reward(completions,gold_labels,**kwargs):
    result=[]
    for c,g in zip(completions,gold_labels):
        pred=parse_answer(completion_text(c))['labels'];gold=set(g)
        result.append(2*len(pred&gold)/(len(pred)+len(gold)) if pred or gold else 1.)
    return result

def verdict_reward(completions,gold_verdict,**kwargs):
    return [float(parse_answer(completion_text(c))['verdict']==g) for c,g in zip(completions,gold_verdict)]

REWARD_FUNCTIONS=[format_reward,label_reward,verdict_reward]
REWARD_WEIGHTS=[.2,.5,.3]
