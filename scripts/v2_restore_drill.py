"""Native Mongo dump/restore of a disposable paused workflow; never production."""
import json, subprocess, time, uuid
from pathlib import Path
from xfagent.v2.store import Store, digest
from xfagent.v2.schema import Actor
from xfagent.v2.policy import Policies
from xfagent.v2.graphs import inspection_graph
from xfagent.v2.worker import execute

def main():
    suffix=uuid.uuid4().hex
    source_name='xfagent_restore_test_source_'+suffix
    target_name='xfagent_restore_test_target_'+suffix
    source=Store(name=source_name);target=Store(name=target_name)
    archive=Path('reports/gaps_v1/restore-fixture.archive.gz')
    uri='mongodb://127.0.0.1:27017/?replicaSet=xfv2&directConnection=true'
    t=time.monotonic();result={'scope':'disposable_fixture_not_production_disaster_recovery',
        'source_db':source_name,'restored_db':target_name,'inference':'not_used'}
    try:
        source.setup();Policies(source).seed()
        source.db.settings.insert_one({'_id':'active_snapshot','value':'fixture-kb'})
        source.db.snapshots.insert_one({'_id':'fixture-kb','state':'published','index_ready':True})
        text='测试夹具：不得遮挡该设施。'
        source.db.documents.insert_one({'_id':'d','doc_id':'d','snapshot_id':'fixture-kb','ready':True,
            'status':'source_verified','kind':'law','jurisdiction':'全国','effective_from':'2021-01-01',
            'sha256':digest(text.encode()),'body_hash':digest(text.encode()),'full_text':text,
            'url':'https://fixture.invalid/not-real-law','conditions':{},'version_id':'fixture-v1'})
        source.db.evidence.insert_one({'_id':'e','snapshot_id':'fixture-kb','doc_id':'d','evidence_id':'e',
            'legacy_id':'e','text':text,'source_hash':digest(text.encode()),'quote_hash':digest(text.encode()),
            'version_id':'fixture-v1','location':{'article':'第一条'}})

        actor=Actor(user_id='restore-fixture',role='reviewer',projects=['default'])
        request={'query':'隔离恢复夹具：材料不足时请求人工补充','scene':{},'facility':'unknown',
            'project_id':'default','session_id':suffix,'as_of':'2026-10-05','jurisdiction':'四川',
            'mode':'retrieval','retrieval_mode':'bm25','use_model':False}
        job=source.submit('retrieval',request,actor,'fixture');claimed=source.claim(job['_id'],'before-backup')
        g=inspection_graph(source);config={'configurable':{'thread_id':job['_id']},'recursion_limit':70}
        state=g.invoke({'run_id':job['_id'],'owner':actor.user_id,'request':request,
            'execution_worker':'before-backup','snapshot_id':'fixture-kb','frozen_memory':{},
            'forced_policy':'baseline-v2','calls':0,'active_seconds':0,'trace':[],'warnings':[]},config)
        assert state.pop('__interrupt__') and state['status']=='awaiting_review'
        source.finish(job['_id'],'before-backup',{'status':'awaiting_review','result':state},
            report={'owner':actor.user_id,'project_id':'default','revision':1,'report':state['report']})
        # Quota and response cache belong in the same backup as jobs/checkpoints.
        source.db.model_budgets.insert_one({'_id':'quota-fixture','calls':15})
        source.db.model_calls.insert_one({'_id':'cache-fixture','run_id':'quota-fixture',
            'status':'completed','result':{'queries':['fixture']}})
        before={name:source.db[name].count_documents({}) for name in source.db.list_collection_names()}
        with archive.open('wb') as stream:
            dumped=subprocess.run(['docker','exec','xfagent-v2-mongo-1','mongodump','--uri',uri,
                '--db',source_name,'--archive','--gzip','--quiet'],stdout=stream,stderr=subprocess.PIPE)
        if dumped.returncode:raise RuntimeError('mongodump failed: '+dumped.stderr.decode()[-1000:])
        source.client.close()
        with archive.open('rb') as stream:
            restored=subprocess.run(['docker','exec','-i','xfagent-v2-mongo-1','mongorestore','--uri',uri,
                '--archive','--gzip','--nsFrom',source_name+'.*','--nsTo',target_name+'.*','--quiet'],
                stdin=stream,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
        if restored.returncode:raise RuntimeError('mongorestore failed: '+restored.stderr.decode()[-1000:])
        after={name:target.db[name].count_documents({}) for name in target.db.list_collection_names()}
        assert before==after
        from xfagent.v2.facts import fetch_evidence
        assert fetch_evidence(target,'fixture-kb','e','2026-10-05','四川')['text']==text
        assert target.db.model_budgets.find_one({'_id':'quota-fixture'})['calls']==15
        assert target.db.model_calls.find_one({'_id':'cache-fixture'})['result']=={'queries':['fixture']}
        restored_job=target.db.jobs.find_one({'_id':job['_id']})
        assert restored_job['status']=='awaiting_review'
        target.enqueue_resume(restored_job,{'expected_revision':1,'action':'approve'},actor)
        execute(target,inspection_graph(target),target.claim(job['_id'],'after-restore'),'after-restore')
        final=target.db.jobs.find_one({'_id':job['_id']})
        assert final['status']=='complete' and final['result']['report']['status']=='final'
        assert final['result']['report']['snapshot_id']=='fixture-kb'
        result.update(passed=True,collections=before,archive_sha256=digest(archive.read_bytes()),
            archive_bytes=archive.stat().st_size,restored_workflow_status='complete')
    finally:
        # Fresh client because the source client was deliberately disconnected.
        cleanup=Store()
        assert source_name.startswith('xfagent_restore_test_source_') and target_name.startswith('xfagent_restore_test_target_')
        cleanup.client.drop_database(source_name);cleanup.client.drop_database(target_name)
        result['cleanup_verified']=source_name not in cleanup.client.list_database_names() and target_name not in cleanup.client.list_database_names()
        cleanup.client.close();target.client.close();source.client.close()
        result['elapsed_seconds']=round(time.monotonic()-t,3)
        Path('reports/gaps_v1/restore-drill.json').write_text(json.dumps(result,ensure_ascii=False,indent=2))
    print(json.dumps(result,ensure_ascii=False))

if __name__=='__main__':main()
