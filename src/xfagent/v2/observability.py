"""Bounded trace statistics: node duration is not a graph critical path."""
from collections import defaultdict
import numpy as np
from prometheus_client import Gauge

class TraceAggregator:
    def __init__(self,store):self.store=store

    @staticmethod
    def summarize(events):
        groups=defaultdict(list)
        for event in events:
            if event.get('node') and isinstance(event.get('seconds'),(int,float)):groups[event['node']].append(event)
        result={}
        for name,rows in groups.items():
            times=[max(0,r['seconds']) for r in rows];known=[r for r in rows if 'outcome' in r]
            result[name]={'count':len(rows),'p50':float(np.percentile(times,50)),
                'p95':float(np.percentile(times,95)),'p99':float(np.percentile(times,99)),
                'total_seconds':sum(times),'mean':sum(times)/len(times),'max':max(times),
                'outcome_known_count':len(known),'failed_count':sum(r['outcome']=='error' for r in known),
                'budget_exhausted_count':sum(r['outcome']=='budget_exhausted' for r in known),
                'degraded_count':sum(bool(r.get('degraded')) for r in known),
                'model_calls':sum(r.get('calls_delta',0) for r in rows),
                'call_delta_known_count':sum('calls_delta' in r for r in rows)}
        return result

    def recent(self,project=None,limit=10000):
        query={'event':'node_complete'}
        if project is not None:query['project_id']=project
        events=list(self.store.db.events.find(query).sort('at',-1).limit(limit+1))
        truncated=len(events)>limit;events=events[:limit];stats=self.summarize(events)
        return {'nodes':stats,'event_count':len(events),'limit':limit,'truncated':truncated,
                'scope':'latest_recorded_events; historical missing outcomes/call deltas remain unknown',
                'slowest_nodes':sorted(stats,key=lambda n:stats[n]['total_seconds'],reverse=True)[:5],
                'interpretation':'节点耗时排序，不声称是并行图的关键路径；小样本分位数仅供排错'}

    def prometheus(self,registry):
        report=self.recent();nodes=report['nodes']
        latency=Gauge('xfagent_node_latency_seconds','Quantiles over latest bounded recorded events',['node','quantile'],registry=registry)
        counts=Gauge('xfagent_node_observations','Latest-window observed node outcomes',['node','kind'],registry=registry)
        calls=Gauge('xfagent_node_model_calls_recorded','Observed call deltas, not cumulative counters',['node'],registry=registry)
        for node,row in nodes.items():
            for name in ['p50','p95','p99']:latency.labels(node,name).set(row[name])
            for name in ['count','outcome_known_count','failed_count','degraded_count','budget_exhausted_count']:
                counts.labels(node,name).set(row[name])
            calls.labels(node).set(row['model_calls'])
        Gauge('xfagent_trace_window_truncated','Whether older traces are omitted from window',registry=registry).set(report['truncated'])
        return report
