import copy,sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).parents[2]/'scripts'))
import v2_astra_review as review
class AstraReviewValidation(unittest.TestCase):
 def setUp(self):
  row={'case_id':'c','facility':'indoor_hydrant','scene_facts':[],'gold_observations':[],'visual_decision':'not_applicable','evidence_requirements':[{'need':'维护','any_of':['E001'],'quotes':[{'evidence_id':'E001','quote':'保持完好有效'}],'applicability':'supported','missing_conditions':[]}],'required_evidence_ids':['E001'],'missing_information':[],'needs_additional_info':False,'needs_human_review':True,'critical_points':['依据有明确原文'],'forbidden_claims':[],'reference_answer':'本条规定消防设施保持完好有效[E001]；本例只有文字说明，没有图像，不能虚构现场故障。','knowledge_gaps':[],'scenario_issues':['没有上一轮上下文'],'confidence':'medium'}
  self.packet={'cases':[{'case_id':'c','facility':'indoor_hydrant','image_present':False,'input':{'as_of':'2026-10-03','jurisdiction':'四川','scene':{}}}],'evidence_aliases':{'E001':{'text':'消防设施保持完好有效。','effective_from':'2020-01-01','effective_until':None,'jurisdiction':'全国','conditions':{}}},'first_pass_annotations':[row]}
  self.obj={'reviews':[{'case_id':'c','decision':'accept','label_review_complete':True,'review_notes':['逐项核对后保留'],'checks':{'image':'not_applicable','context':'checked','legal_support':'checked','date_region':'checked','scope':'checked'},'issue_resolutions':[{'issue_index':0,'disposition':'valid_uncertainty','reason':'该例仍无前文，按不确定评估'}],'patch':{},'evaluation':{'status':'usable','excluded_dimensions':[],'uncertainties':['原始前文未提供'],'reason':'能够评估正确说明未知事实的行为'}}]}
 def test_adjudication_finishes_without_human_labeler(self):
  self.assertEqual(review.validate(self.obj,self.packet),[]);self.assertEqual(self.obj['annotations'],self.packet['first_pass_annotations'])
 def test_unresolved_issue_rejected(self):
  self.obj['reviews'][0]['issue_resolutions']=[];self.assertTrue(any('every original issue' in s for s in review.validate(self.obj,self.packet)))
 def test_duplicate_case_rejected(self):
  self.obj['reviews']*=2;self.assertTrue(review.validate(self.obj,self.packet))
 def test_pending_label_not_accepted(self):
  self.obj['reviews'][0]['label_review_complete']=False;self.assertTrue(review.validate(self.obj,self.packet))
 def test_identity_patch_rejected(self):
  self.obj['reviews'][0].update(decision='correct',patch={'facility':'outdoor_hydrant'});self.assertTrue(review.validate(self.obj,self.packet))
 def test_accept_cannot_hide_changes(self):
  self.obj['reviews'][0]['patch']={'visual_decision':'normal'};self.assertTrue(review.validate(self.obj,self.packet))
 def test_forged_quote_rejected_after_patch(self):
  req=copy.deepcopy(self.packet['first_pass_annotations'][0]['evidence_requirements']);req[0]['quotes'][0]['quote']='压力必须达到99兆帕'
  self.obj['reviews'][0].update(decision='correct',patch={'evidence_requirements':req});self.assertTrue(any('verbatim' in s for s in review.validate(self.obj,self.packet)))
 def test_date_check_not_bypassed_by_second_review(self):
  self.packet['evidence_aliases']['E001']['effective_from']='2027-01-01';self.assertTrue(any('not effective' in s for s in review.validate(self.obj,self.packet)))
 def test_context_issue_can_be_resolved_and_removed(self):
  r=self.obj['reviews'][0];r.update(decision='correct',patch={'scenario_issues':[]});r['issue_resolutions'][0]={'issue_index':0,'disposition':'resolved_by_context','reason':'已提供冻结工作记忆'}
  self.assertEqual(review.validate(self.obj,self.packet),[]);self.assertEqual(self.obj['annotations'][0]['scenario_issues'],[])
 def test_partial_evaluation_requires_exclusion_reason(self):
  self.obj['reviews'][0]['evaluation']['status']='partially_evaluable';self.assertTrue(review.validate(self.obj,self.packet))
 def test_original_annotation_immutable(self):
  original=copy.deepcopy(self.packet['first_pass_annotations']);self.obj['reviews'][0].update(decision='correct',patch={'knowledge_gaps':['缺少型号技术依据']});review.validate(self.obj,self.packet);self.assertEqual(original,self.packet['first_pass_annotations'])
 def test_cross_process_style_lock_serializes_same_family(self):
  import concurrent.futures,tempfile,threading,time
  from unittest.mock import patch
  guard=threading.Lock();state={'active':0,'peak':0,'calls':0}
  def fake(*args):
   with guard:state['active']+=1;state['peak']=max(state['peak'],state['active']);state['calls']+=1
   time.sleep(.04)
   with guard:state['active']-=1
   return 'ok'
  with tempfile.TemporaryDirectory() as d, patch.object(review,'_ORIGINAL_RUN',fake):
   with concurrent.futures.ThreadPoolExecutor(2) as pool:
    fs=[pool.submit(review.run_with_lock,Path('same-family.json'),{},Path(d),Path(d)) for _ in range(2)]
    self.assertEqual([f.result() for f in fs],['ok','ok'])
  self.assertEqual(state,{'active':0,'peak':1,'calls':2})
if __name__=='__main__':unittest.main()
