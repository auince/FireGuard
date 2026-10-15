"""Rebuild private local indexes; opt-in publication uses a compare-and-swap pointer."""
import argparse
import json

from xfagent.v2.store import Store
from xfagent.v2.facts import prepare_snapshot, publish_snapshot
from xfagent.v2.retrieval import index_snapshot
from xfagent.v2.structure import materialize_structure
from xfagent.cases import build_cases


def main():
    parser = argparse.ArgumentParser(description='Build heading/body and image/text indexes')
    parser.add_argument('--publish', action='store_true', help='Activate the validated legal snapshot')
    parser.add_argument('--case-source', help='Private local JSONL case manifest')
    parser.add_argument('--case-limit', type=int, default=200)
    args = parser.parse_args()
    store = Store()
    store.setup()
    active = store.db.settings.find_one({'_id': 'active_snapshot'})
    sid = prepare_snapshot(store)
    count = index_snapshot(store, sid)
    structure = materialize_structure(store, sid)
    result = {'snapshot': sid, 'evidence_count': count, 'structure': structure, 'published': False}
    if args.case_source:
        result['cases'] = build_cases(args.case_source, args.case_limit)
    if args.publish:
        publish_snapshot(store, sid, expected_active=active['value'] if active else None)
        result['published'] = True
    print(json.dumps(result, ensure_ascii=False, default=str))


if __name__ == '__main__':
    main()
