"""Record every data-driven contract result, including ordinary failures."""
import json
import hashlib
import os
from pathlib import Path
import pytest

RECORDS=[]

@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item,call):
 outcome=yield
 report=outcome.get_result()
 if report.when=='call' or (report.when=='setup' and report.failed):
  case=getattr(item,'callspec',None)
  value=case.params.get('case',{}) if case else {}
  RECORDS.append({'id':value.get('id',item.nodeid),'nodeid':item.nodeid,'requirements':value.get('requirements',[]),
       'operation':value.get('operation'),'outcome':report.outcome,'phase':report.when,'seconds':report.duration,
       'expected':value.get('expected'),'failure':str(report.longrepr) if report.failed else None})

def pytest_sessionfinish(session,exitstatus):
 from xfagent.v2.replay_protocol import execution_hash
 target=Path(os.environ.get('XF_COVERAGE_REPORT','reports/coverage_v1/contracts.json'))
 target.parent.mkdir(parents=True,exist_ok=True)
 suite=Path(os.environ.get('XF_COVERAGE_SUITE','benchmarks/coverage_v1'))
 target.write_text(json.dumps({'protocol':'xfagent-coverage-v1','execution_hash':execution_hash(),
     'contracts_sha256':hashlib.sha256((suite/'contracts.jsonl').read_bytes()).hexdigest(),
     'cases':len(RECORDS),'passed':sum(r['outcome']=='passed' for r in RECORDS),
     'failed':sum(r['outcome']=='failed' for r in RECORDS),'skipped':sum(r['outcome']=='skipped' for r in RECORDS),
     'exitstatus':int(exitstatus),'gpu_calls':0,'production_writes':0,
     'scope':'isolated CPU requirements tests; not semantic accuracy or production load',
     'records':RECORDS},ensure_ascii=False,indent=2)+'\n')
