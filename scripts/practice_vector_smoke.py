"""Real embedding HTTP + real Milvus, explicitly simulated text/model output."""
import json
import uuid

from xfagent.practice.vector import BasicVectorRAG

rag = BasicVectorRAG(name='xfpractice_smoke_' + uuid.uuid4().hex)
try:
    count = rag.ingest('仿真工程夹具：消防设施应便于取用，不得遮挡。' * 30,
                       '仿真工程夹具（非法律依据）')
    result = rag.search({}, ['消火栓被杂物遮挡'])
    assert count and result['evidence']
    print(json.dumps({'embedding': 'real_http', 'vector_store': 'real_milvus',
                      'source': 'authored_fixture', 'llm_inference': 'not_executed',
                      'chunks': count, 'hits': len(result['evidence']), 'passed': True}, ensure_ascii=False))
finally:
    if rag.client.has_collection(rag.name):
        rag.client.drop_collection(rag.name)
