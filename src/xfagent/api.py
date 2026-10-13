"""Local workbench API. Long jobs persist status; Agent state stays in LangGraph."""
import base64,hashlib,io,json,os,secrets,threading,uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from flask import Flask,request,jsonify,send_from_directory,send_file
from PIL import Image
from langgraph.types import Command
from .config import ROOT,directory,read_json
from .data import Store
from .models import health,ModelUnavailable
from .graphs import inspection_graph,retrieval_graph,annotation_graph,saver,validate_review

def create_app():
    app=Flask(__name__,static_folder=None);app.config['MAX_CONTENT_LENGTH']=18*1024*1024
    store=Store();pool=ThreadPoolExecutor(max_workers=1);graphs={};lock=threading.Lock()
    for job in store.list('job',10000):
        if job['payload'].get('status') in ['running','queued']:
            store.put('job',{**job['payload'],'status':'interrupted','error':'服务重启；可从检查点恢复'},job['id'])
    def graph(kind):
        with lock:
            if kind not in graphs:graphs[kind]={'inspection':inspection_graph,'annotation':annotation_graph,'retrieval':retrieval_graph}[kind](checkpointer=saver(kind))
            return graphs[kind]
    def clean_image(value):
        if not isinstance(value,str) or not value.startswith('data:image/'):raise ValueError('请上传图片')
        try:
            raw=base64.b64decode(value.split(',',1)[1],validate=True)
            with Image.open(io.BytesIO(raw)) as im:
                im=im.convert('RGB');im.thumbnail((1600,1600));out=io.BytesIO();im.save(out,format='JPEG',quality=92)
        except (OSError,ValueError,IndexError) as exc:raise ValueError('图片数据无效，请重新上传') from exc
        # Original hash, retained original image, to prevent re-encoding from bypassing test exclusion.
        digest=hashlib.sha256(raw).hexdigest();path=directory('runtime/uploads')/(digest+'.image');path.write_bytes(raw)
        return 'data:image/jpeg;base64,'+base64.b64encode(out.getvalue()).decode(),digest,str(path)
    def submit(kind,state,resume=None,identifier=None,meta=None):
        identifier=identifier or str(uuid.uuid4());store.put('job',{'status':'queued','kind':kind},identifier)
        def work():
            try:
                store.put('job',{'status':'running','kind':kind},identifier)
                result=graph(kind).invoke(Command(resume=resume) if resume is not None else state,{'configurable':{'thread_id':identifier}})
                paused=bool(result.get('__interrupt__'))
                result.pop('__interrupt__',None);result.pop('image',None)
                payload={**(meta or {}),**result}
                if kind=='annotation':store.put('annotation',payload,identifier)
                if kind=='inspection':store.put('report',result['report'],identifier)
                store.put('job',{'status':'awaiting_review' if paused else 'complete','kind':kind,'result':payload},identifier)
            except Exception as e:store.put('job',{'status':'failed','kind':kind,'error':str(e),'error_type':type(e).__name__},identifier)
        pool.submit(work);return identifier
    @app.errorhandler(ValueError)
    def bad_request(e):return jsonify(error=str(e)),400
    @app.errorhandler(ModelUnavailable)
    def unavailable(e):return jsonify(error=str(e)),503
    @app.get('/')
    def index():return send_from_directory(ROOT/'apps/web','index.html')
    @app.get('/api/health')
    def status():return jsonify(model=health(),index=read_json(ROOT/'data/index/metadata.json',{}),agents='LangGraph',storage='SQLite',legal_documents=len(read_json(ROOT/'data/legal/manifest.json',[])))
    @app.post('/api/inspect')
    def inspect():
        body=request.get_json();im,_,_=clean_image(body.get('image'))
        return jsonify(id=submit('inspection',{'image':im,'query':str(body.get('query','请检查消防隐患'))[:1000]})),202
    @app.post('/api/retrieve')
    def retrieve():
        body=request.get_json();query=str(body.get('query','')).strip()
        if not query:raise ValueError('请输入检索问题')
        return jsonify(id=submit('retrieval',{'query':query[:2000],'mode':body.get('mode','hybrid'),'use_model':bool(body.get('use_model',True)),'max_rounds':2})),202
    @app.get('/api/jobs/<identifier>')
    def job(identifier):
        record=store.get(identifier)
        return (jsonify(record),200) if record else (jsonify(error='not found'),404)
    @app.get('/api/reports')
    def reports():return jsonify(store.list('report'))
    @app.post('/api/jobs/<identifier>/resume')
    def resume_job(identifier):
        row=store.get(identifier)
        if not row or row['payload'].get('status') not in ['failed','interrupted']:raise ValueError('该任务不能恢复')
        kind=row['payload']['kind']
        if not graph(kind).get_state({'configurable':{'thread_id':identifier}}).values:raise ValueError('没有可用检查点，请重新提交')
        meta=(store.get(identifier,'annotation') or {}).get('payload',{}) if kind=='annotation' else {}
        return jsonify(id=submit(kind,None,identifier=identifier,meta=meta)),202
    @app.get('/api/annotations')
    def annotations():return jsonify(store.list('annotation'))
    @app.get('/api/annotations/<identifier>/image')
    def annotation_image(identifier):
        row=store.get(identifier,'annotation')
        if not row:return jsonify(error='annotation not found'),404
        path=Path(row['payload']['image_path']).resolve()
        if not path.is_relative_to(ROOT/'runtime/uploads'):return jsonify(error='unapproved image'),403
        with Image.open(path) as im:
            output=io.BytesIO();im.convert('RGB').save(output,format='JPEG');output.seek(0)
        return send_file(output,mimetype='image/jpeg')
    @app.post('/api/annotations')
    def annotate():
        body=request.get_json();im,digest,path=clean_image(body.get('image'));mode=body.get('mode','model_first')
        if mode not in ['human_seed','model_first']:raise ValueError('invalid annotation mode')
        return jsonify(id=submit('annotation',{'image':im,'image_sha256':digest,'mode':mode,'human_labels':body.get('labels',[])},meta={'image_path':path,'prompt':'请检查图中消防设施并给出结构化隐患判断。'})),202
    @app.post('/api/annotations/<identifier>/review')
    def review(identifier):
        row=store.get(identifier,'annotation');body=request.get_json()
        if not row or row['kind']!='annotation':raise ValueError('没有待审核的标注')
        if row['payload'].get('approved'):raise ValueError('该标注已经完成审核')
        job=store.get(identifier)
        if not job or job['payload']['status']!='awaiting_review':raise ValueError('任务当前不处于待审核状态')
        if not body.get('reviewer') or not isinstance(body.get('labels'),list) or not isinstance(body.get('accepted'),bool):raise ValueError('需要审核人、标签数组和是否接纳')
        validate_review(body)
        return jsonify(id=submit('annotation',None,resume=body,identifier=identifier,meta=row['payload'])),202
    @app.post('/api/cases/search')
    def cases():
        from .cases import search_cases
        b=request.get_json();kind=b.get('kind','text')
        if kind not in ['text','image_data']:raise ValueError('查询只接受文字或上传图片')
        return jsonify(search_cases(b['query'],kind,b.get('mode','rrf')))
    @app.get('/api/cases/image/<path:case_id>')
    def case_image(case_id):
        record=next((x for x in read_json(ROOT/'data/cases/records.json',[]) if str(x['id'])==case_id),None)
        if not record:return jsonify(error='case not found'),404
        path=Path(record['image']).resolve()
        if not any(path.is_relative_to(root) for root in [Path('/opt/datasets/fire-inspection'),ROOT/'runtime/uploads']):return jsonify(error='unapproved image root'),403
        return send_file(path)
    @app.get('/api/legal')
    def legal():return jsonify(read_json(ROOT/'data/legal/manifest.json',[]))
    @app.get('/api/labels')
    def labels():
        from .rewards import ALL_LABELS
        return jsonify(sorted(ALL_LABELS))
    return app
