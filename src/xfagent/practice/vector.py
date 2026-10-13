"""Stage 1: plain chunk -> embedding -> Milvus -> evidence text."""
import hashlib
import os
import re
from pathlib import Path

import numpy as np
import requests
from pymilvus import MilvusClient


def chunk(text, size=600, overlap=80):
    if not 0 <= overlap < size or not text.strip():
        raise ValueError('invalid chunk configuration or empty document')
    text = re.sub(r'\n{3,}', '\n\n', text).strip()
    return [text[i:i + size] for i in range(0, len(text), size - overlap)]


def read_document(path):
    path = Path(path)
    if path.suffix.lower() == '.pdf':
        from pypdf import PdfReader
        return '\n'.join(page.extract_text() or '' for page in PdfReader(path).pages)
    if path.suffix.lower() == '.docx':
        from docx import Document
        return '\n'.join(p.text for p in Document(path).paragraphs)
    return path.read_text(encoding='utf-8')


def embed(texts):
    response = requests.post(os.getenv('XF_EMBEDDING_URL', 'http://127.0.0.1:8001/embed'),
                             json={'texts': texts}, timeout=(3, 120))
    response.raise_for_status()
    vectors = np.asarray(response.json()['vectors'], dtype='float32')
    if vectors.ndim != 2 or len(vectors) != len(texts) or not np.isfinite(vectors).all():
        raise ValueError('invalid embeddings')
    norms = np.linalg.norm(vectors, axis=1, keepdims=True)
    if (norms == 0).any():
        raise ValueError('zero embedding')
    return (vectors / norms).tolist()


class BasicVectorRAG:
    def __init__(self, name=None, client=None, embedding=embed):
        self.name = name or os.getenv('XF_PRACTICE_COLLECTION', 'xfpractice_baseline')
        if not re.fullmatch(r'xfpractice_[a-zA-Z0-9_]+', self.name):
            raise ValueError('practice collection must use xfpractice_ prefix')
        self.client = client or MilvusClient(uri=os.getenv('XF_V2_MILVUS', 'http://127.0.0.1:19530'))
        self.embedding = embedding

    def ingest(self, text, title, source_url=''):
        parts = chunk(text)
        vectors = self.embedding(parts)
        if not self.client.has_collection(self.name):
            self.client.create_collection(self.name, dimension=len(vectors[0]), id_type='string',
                                          max_length=64, metric_type='COSINE', consistency_level='Strong')
        records = []
        for index, (part, vector) in enumerate(zip(parts, vectors)):
            identifier = hashlib.sha256((title + ':' + str(index) + ':' + part).encode()).hexdigest()
            records.append({'id': identifier, 'vector': vector, 'text': part,
                            'document_title': title, 'source_url': source_url, 'chunk_index': index})
        self.client.upsert(self.name, records)
        self.client.flush(self.name)
        return len(records)

    def search(self, request, queries):
        if not self.client.has_collection(self.name):
            raise ValueError('请先导入法规文本并建立向量索引')
        groups = self.client.search(self.name, data=self.embedding([queries[0]]), limit=5,
                                    output_fields=['text', 'document_title', 'source_url'])
        evidence = [dict(hit['entity'], evidence_id=str(hit['id'])) for hit in groups[0]]
        return {'evidence': evidence, 'warnings': [], 'snapshot_id': self.name}
