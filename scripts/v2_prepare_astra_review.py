"""Freeze enriched review inputs without evaluated model answers or expected labels."""
import argparse,json,hashlib,copy
from pathlib import Path
from v2_astra_annotate import sha

def prepare(root):
 out=root/'review-packets';out.mkdir(exist_ok=True)
 contexts={r['case_id']:r for r in map(json.loads,(root/'frozen-review-context.jsonl').read_text().splitlines())}
 locations=json.loads((root/'source-locations.json').read_text())['locations']
 bg=root/'review-background';pdf=bg/'GB50444-2008.pdf';pdfhash=sha(pdf.read_bytes())
 texts={3:'灭火器的铭牌是否朝外，并且器头宜向上',4:'灭火器的类型、规格、灭火级别和配置数量是否符合配置设计要求',9:'灭火器周围是否存在有障碍物、遮挡、拴系等影响取用的现象',10:'灭火器箱是否上锁，箱内是否干燥、清洁',12:'灭火器的铭牌是否无残缺，并清晰明了',14:'灭火器的铅封、销闩等保险装置是否未损坏或遗失',15:'灭火器的筒体是否无明显的损伤（磕伤、划伤）、缺陷、锈蚀（特别是筒底和焊缝）、泄漏',16:'灭火器喷射软管是否完好、无明显龟裂、喷嘴不堵塞',17:'灭火器的驱动气体压力是否在工作压力范围内（贮压式灭火器查看压力指示器是否指示在绿区范围内，二氧化碳灭火器和储气瓶式灭火器可用称重法检查）',18:'灭火器的零部件是否齐全，并且无松动、脱落或损伤现象',19:'灭火器是否未开启、喷射过'}
 source='https://js.119.gov.cn/group1/M00/00/2B/ZYS-ZGGB6oOAEfdqAEAK60AmDRM740.pdf'
 notice='https://js.119.gov.cn/202111/206aebe848d24575894f22639ff3e721_c_3b4857e24c0c4bab8ca4.html'
 supplement={}
 for i,(n,text) in enumerate(texts.items(),901):
  article=f'附录C 表C第{n}项';eid=sha([pdfhash,article,text])
  supplement[f'E{i:03d}']={'evidence_id':eid,'doc_id':'review-gb50444-2008','article':article,'text':text,'source_hash':pdfhash,'location':{'pdf_page':25,'printed_page':18,'table':'C','row':n,'coordinate_system':'pdf_page_table_row'},'version_id':'review-gb50444:'+pdfhash[:16],'source_url':source,'title':'建筑灭火器配置验收及检查规范 GB50444-2008','effective_from':'2008-11-01','effective_until':None,'jurisdiction':'全国','conditions':{},'indexed_in_snapshot':False,'source_provenance':'官方PDF扫描；表C选定行经图像对读转写，复核时同时提供原页','authority_note':'表C检查内容；不称为逐项强制性条文，与GB55036冲突以通用规范为准','publication_notice':notice}
 (bg/'supplemental-evidence.json').write_text(json.dumps(supplement,ensure_ascii=False,indent=2))
 count=0
 for pf in sorted((root/'packets').glob('*.json')):
  p=json.loads(pf.read_text());first=json.loads((root/'results-v1.1'/pf.name).read_text())
  p['first_pass_annotations']=first['output']['annotations'];p['first_pass_record_hash']=sha(first)
  for c in p['cases']:
   frozen=contexts[c['case_id']]
   c['execution_context']={'executed_input':{k:v for k,v in frozen['executed_input'].items() if k in ['query','facility','scene','as_of','jurisdiction','mode']},'frozen_memory':frozen['frozen_memory'],'fault_injection':frozen['fault_injection'],'provenance':'frozen original execution inputs, excluding answers and expected labels'}
  for e in p['evidence_aliases'].values():e['location']=locations[e['evidence_id']];e['indexed_in_snapshot']=True
  if p['cases'][0]['facility']=='fire_extinguisher':
   p['evidence_aliases'].update(copy.deepcopy(supplement))
   for key,e in supplement.items():p['legal_context'].append({'document':e['title'],'version':e['version_id'],'valid_from':e['effective_from'],'valid_until_exclusive':None,'jurisdiction':'全国','conditions':{},'article':e['article'],'source_url':source,'indexed_in_snapshot':False,'fragments':[{'id':key,'text':e['text']}]})
   p['background_source_images']=[{'relative_path':'review-background/appendix-c25.png','sha256':sha((bg/'appendix-c25.png').read_bytes()),'role':'法规原页，绝不是现场照片','source_url':source,'pdf_page':25}]
  p['review_background']={'scope':'标签由Astra完成复核，保留不确定真值，不设置人工标注待办','legal_date_vs_photo_date':'as_of是法规适用日期；拍摄日期未独立证明','GB50444_notice':{'url':notice,'effective_from':'2023-03-01','repealed_clauses':['2.2.1','3.1.3','3.1.5','3.2.2','4.1.1','4.2.1','4.2.2','4.2.3','4.2.4','5.3.2','5.4.1','5.4.2','5.4.3','5.4.4'],'rule':'与GB55036-2022不一致以通用规范为准；不把废止条款当现行强制依据'},'evaluation_scope':'只就题意相关且有来源的现场事实标注，资料未知可以是有效最终标签，不要求虚构实际数据'}
  p['context_selection']['additional_inputs']=['frozen_execution_input','frozen_working_memory','fault_injection','independent_first_pass_labels','review_rubric','GB50444_table_C_for_extinguishers']
  (out/pf.name).write_text(json.dumps(p,ensure_ascii=False,indent=2));count+=1
 print(json.dumps({'review_packets':count,'supplementary_source_rows':len(supplement),'production_answers_included':False}))
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('root',type=Path);a=p.parse_args();prepare(a.root)
