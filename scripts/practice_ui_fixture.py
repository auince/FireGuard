"""Opt-in UI test server; explicitly synthetic model/evidence, isolated SQLite."""
import os
import tempfile
from pathlib import Path

import uvicorn

from xfagent.practice.app import create_app
from xfagent.practice.harness import Harness
from xfagent.practice.storage import Storage


class FixtureRAG:
    def documents(self, as_of, jurisdiction):
        return {'snapshot_id': 'simulated-ui-fixture', 'documents': [self.document('fixture-doc', as_of, jurisdiction)]}

    def document(self, doc_id, as_of, jurisdiction):
        if doc_id != 'fixture-doc':
            return None
        return {'doc_id': 'fixture-doc', 'title': 'UI 测试仿真条款（非法律依据）',
                'version_id': 'fixture-v1', 'effective_from': '2026-01-01', 'url': '',
                'jurisdiction': '四川', 'full_text': '仿真工程夹具：设施应便于取用，不得遮挡。'}

    def search(self, request, queries):
        return {'snapshot_id': 'simulated-ui-fixture', 'warnings': [], 'evidence': [
            {'evidence_id': 'fixture-e', 'text': '仿真工程夹具：设施应便于取用，不得遮挡。',
             'document_title': 'UI 测试仿真条款（非法律依据）', 'source_url': ''}]}


class FixtureModel:
    name = 'injected-ui-fixture-not-real-9b'
    def complete(self, role, payload, image=None, **kwargs):
        if role == 'intent':
            return {'facility': 'indoor_hydrant'}
        if role == 'rewrite':
            return {'queries': ['室内消火栓遮挡核查']}
        if role == 'verify':
            return {'supported': True, 'issues': []}
        return {'hazards': [{'description': '仿真示例：消火栓前有杂物，需现场确认取用是否受阻。',
                 'suggestion': '仿真建议：清理杂物，再检查操作空间。', 'evidence_ids': ['fixture-e']}],
                'missing_information': []}


folder = Path(tempfile.mkdtemp(prefix='xfagent-ui-fixture-'))
store = Storage(folder / 'state.sqlite')
for role in ['inspector', 'reviewer']:
    store.add_user(role, 'ui-fixture-only', role)
print('UI fixture only; model responses are injected. Accounts: inspector / reviewer, password ui-fixture-only.', flush=True)
uvicorn.run(create_app(Harness(FixtureRAG(), FixtureModel()), store), host='127.0.0.1',
            port=int(os.getenv('XF_PRACTICE_UI_PORT', '8081')))
