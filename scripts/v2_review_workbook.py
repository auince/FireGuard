"""Export a local, editable review workbook; never infer professional labels."""
import json,shutil,hashlib
from pathlib import Path
from xfagent.v2.config import ROOT

def main():
    source=ROOT/'reports/v2/system/expert_review_queue.jsonl'
    rows=[json.loads(line) for line in source.read_text().splitlines()]
    cases={c['id']:c for c in map(json.loads,(ROOT/'benchmarks/inspection_scenarios/v2/cases.jsonl').read_text().splitlines())}
    out=ROOT/'reports/v2/review-workbook';(out/'images').mkdir(parents=True,exist_ok=True)
    for row in rows:
        row['training_overlap_status']=cases[row['case_id']].get('training_overlap_status','no_image')
        if row.get('image_path'):
            p=Path(row['image_path']);sha=hashlib.sha256(p.read_bytes()).hexdigest()
            if sha!=cases[row['case_id']]['image_sha256']:raise ValueError('Original image changed: '+row['case_id'])
            target=out/'images'/(sha+p.suffix.lower());shutil.copyfile(p,target)
            row['review_image']='images/'+target.name
    template=(ROOT/'apps/v2/review_workbook.html').read_text()
    embedded=json.dumps(rows,ensure_ascii=False).replace('<','\\u003c')
    (out/'index.html').write_text(template.replace('__REVIEW_DATA__',embedded))
    (out/'README.txt').write_text('打开index.html查看与填写；原始图片位于images。所有专业判断初始待审。填写后导出JSON，页面刷新前请保存。原始记录保留于服务器reports/v2/system。\n')
    print('Exported review workbook:',len(rows),'cases; professional labels remain pending')

if __name__=='__main__':main()
