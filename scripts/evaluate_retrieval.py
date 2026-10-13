import argparse,json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'src'))
from xfagent.retrieval import SearchIndex,retrieval_metrics
p=argparse.ArgumentParser();p.add_argument('gold',help='JSON array with query and human-provided gold_ids');p.add_argument('--output',required=True);a=p.parse_args()
queries=json.loads(Path(a.gold).read_text());index=SearchIndex()
result={m:retrieval_metrics(queries,index,m) for m in ['bm25','dense','hierarchical','weighted','hybrid']}
Path(a.output).write_text(json.dumps(result,ensure_ascii=False,indent=2))
