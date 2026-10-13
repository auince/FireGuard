import argparse,hashlib,json,shutil
from pathlib import Path
p=argparse.ArgumentParser();p.add_argument('--references',type=Path,required=True);p.add_argument('--images',type=Path,required=True);p.add_argument('--template',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args();a.output.mkdir(parents=True,exist_ok=True);(a.output/'images').mkdir(exist_ok=True)
rows=list(map(json.loads,a.references.read_text().splitlines()))
for r in rows:
 if r.get('image_sha256'):
  files=list(a.images.glob(r['image_sha256']+'.*'));assert len(files)==1
  f=files[0];assert hashlib.sha256(f.read_bytes()).hexdigest()==r['image_sha256']
  target=a.output/'images'/f.name
  if not target.exists():shutil.copyfile(f,target)
  r['review_image']='images/'+f.name
encoded=json.dumps(rows,ensure_ascii=False).replace('<','\\u003c')
(a.output/'index.html').write_text(a.template.read_text().replace('__ASTRA_DATA__',encoded))
(a.output/'README.txt').write_text('Astra 第二轮复核已完成；无需人工标注。查看每项裁决、原图、法规和标签修改。未知现场事实是最终不确定标签。来源为模型复核，非人类专家审定。导出数据带评估掩码与不可变来源哈希。\n')
print(json.dumps({'cases':len(rows),'images':sum(bool(r.get('image_sha256')) for r in rows)},ensure_ascii=False))
