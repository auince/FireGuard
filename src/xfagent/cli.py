import argparse,json
from .config import ROOT

def main():
    p=argparse.ArgumentParser(description='XFAgent 消防巡检项目');sub=p.add_subparsers(dest='command',required=True)
    s=sub.add_parser('serve');s.add_argument('--port',type=int,default=8082)
    s=sub.add_parser('crawl');s.add_argument('--limit',type=int,default=80)
    s=sub.add_parser('index');s.add_argument('--sparse',action='store_true')
    s=sub.add_parser('search');s.add_argument('query');s.add_argument('--mode',default='hybrid')
    s=sub.add_parser('curate');s.add_argument('source');s.add_argument('frozen');s.add_argument('--output',default=str(ROOT/'data/training'))
    s=sub.add_parser('cases-index');s.add_argument('source');s.add_argument('--limit',type=int,default=200)
    s=sub.add_parser('export-reviewed');s.add_argument('frozen');s.add_argument('output')
    a=p.parse_args()
    if a.command=='serve':
        from .api import create_app
        create_app().run(host='127.0.0.1',port=a.port,threaded=True);return
    if a.command=='crawl':
        from .crawl import crawl
        result=crawl(a.limit)
    elif a.command=='index':
        from .retrieval import build_index
        result=build_index(not a.sparse)
    elif a.command=='search':
        from .retrieval import SearchIndex
        result=SearchIndex().search(a.query,mode=a.mode)
    elif a.command=='curate':
        from .data import curate
        result=curate(a.source,a.frozen,a.output)
    elif a.command=='cases-index':
        from .cases import build_cases
        result=build_cases(a.source,a.limit)
    elif a.command=='export-reviewed':
        from .data import export_reviewed,Store,rows,image_hash
        result=export_reviewed(Store(),a.output,{image_hash(r['images'][0]) for r in rows(a.frozen)})
    print(json.dumps(result,ensure_ascii=False,indent=2))
if __name__=='__main__':main()
