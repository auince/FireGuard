"""Evaluate configured intent endpoint only; no production DB writes."""
import argparse, json, time
from pathlib import Path
from xfagent.v2.model import complete
from xfagent.v2.model_routes import resolve
from xfagent.v2.config import FACILITIES

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--cases',default='benchmarks/coverage_v2/intent_dev_candidates.jsonl')
    parser.add_argument('--output',default='reports/gaps_v1/intent-live.json')
    parser.add_argument('--include-keyword-routing',action='store_true')
    args=parser.parse_args();route=resolve('intent');results=[]
    cases=[json.loads(x) for x in Path(args.cases).read_text().splitlines()]
    for case in cases:
        if case.get('split')!='dev':raise ValueError('only development cases may be executed')
    for case in cases:
        t=time.monotonic();state={'calls':0,'active_seconds':0};predicted=None;error=None
        try:
            if args.include_keyword_routing:
                matches=[key for key,value in FACILITIES.items() if value in case['input']['query']]
                predicted=matches[0] if len(matches)==1 else None
            if predicted is None:
                response=complete(state,'识别唯一主要设施；含混、多设施或未支持的设施返回unknown。返回 {"facility":"indoor_hydrant|outdoor_hydrant|fire_extinguisher|unknown"}。',case['input'],role='intent')
                predicted=response.get('facility')
        except Exception as exc:error=type(exc).__name__+': '+str(exc)[:300]
        results.append({'case_id':case['id'],'family_id':case['family_id'],'expected':case['expected']['facility'],
            'predicted':predicted,'correct':not error and predicted==case['expected']['facility'],
            'error':error,'seconds':time.monotonic()-t,'calls':state.get('calls',0)})
    report={'scope':'authored_development_routing_not_real_user_accuracy','route':route,
        'keyword_routing':args.include_keyword_routing,'cases':len(results),
        'correct':sum(x['correct'] for x in results),'errors':sum(bool(x['error']) for x in results),
        'accuracy_on_authored_cases':sum(x['correct'] for x in results)/max(1,len(results)),
        'domain_calibration':'pending_real_chinese_queries','results':results}
    Path(args.output).write_text(json.dumps(report,ensure_ascii=False,indent=2))
    print(json.dumps({key:value for key,value in report.items() if key!='results'},ensure_ascii=False))

if __name__=='__main__':main()
