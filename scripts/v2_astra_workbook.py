import argparse,json,hashlib,shutil
from pathlib import Path
p=argparse.ArgumentParser();p.add_argument('--references',type=Path,required=True);p.add_argument('--images',type=Path,required=True);p.add_argument('--template',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args();a.output.mkdir(parents=True,exist_ok=True);(a.output/'images').mkdir(exist_ok=True)
rows=list(map(json.loads,a.references.read_text().splitlines()))
for r in rows:
 if r.get('image_sha256'):
  fs=list(a.images.glob(r['image_sha256']+'.*'));assert len(fs)==1
  f=fs[0];assert hashlib.sha256(f.read_bytes()).hexdigest()==r['image_sha256'];target=a.output/'images'/f.name
  if not target.exists():shutil.copyfile(f,target)
  r['review_image']='images/'+f.name
embedded=json.dumps(rows,ensure_ascii=False).replace('<','\\u003c');(a.output/'index.html').write_text(a.template.read_text().replace('__ASTRA_DATA__',embedded))
(a.output/'README.txt').write_text('GPT-6 Astra模型辅助参考标注，非人工专家审定。打开index.html查看原图、标签、法规证据、场景冲突及填写复核意见。切换场景保留本次页面意见；刷新或关闭前请导出。导出不会自动发布为金标。原始场景划分与历史9B结果未被改写。\n')
print('workbook',len(rows),'images',sum(bool(r.get('image_sha256')) for r in rows))
