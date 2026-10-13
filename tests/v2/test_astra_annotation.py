import copy,importlib.util,unittest
from pathlib import Path
spec=importlib.util.spec_from_file_location('astra',Path(__file__).parents[2]/'scripts/v2_astra_annotate.py')
a=importlib.util.module_from_spec(spec);spec.loader.exec_module(a)
class AnnotationValidation(unittest.TestCase):
 def setUp(self):
  self.p={'cases':[{'case_id':'c','facility':'extinguisher','image_present':False,'input':{'as_of':'2024-11-01','jurisdiction':'四川','scene':{}}}], 'evidence_aliases':{'E001':{'text':'消防设施应当保持完好有效。','effective_from':'2024-11-01','effective_until':None,'jurisdiction':'四川','conditions':{}}}}
  self.row={'case_id':'c','facility':'extinguisher','scene_facts':[],'gold_observations':[],'visual_decision':'not_applicable','evidence_requirements':[{'need':'维护责任','any_of':['E001'],'quotes':[{'evidence_id':'E001','quote':'应当保持完好有效'}],'applicability':'supported','missing_conditions':[]}],'required_evidence_ids':['E001'],'missing_information':[],'needs_additional_info':False,'needs_human_review':True,'critical_points':['保持完好有效'],'forbidden_claims':[],'reference_answer':'[E001]提供维护责任依据，但本次没有现场图像，不能由此证明现场设备已经完好有效，仍需人工核查。','knowledge_gaps':[],'scenario_issues':[],'confidence':'medium'}
 def check(self):return a.validate({'annotations':[self.row]},self.p)
 def test_effective_start_inclusive(self):self.assertEqual(self.check(),[])
 def test_future_law_rejected(self):
  self.p['cases'][0]['input']['as_of']='2024-10-31';self.assertTrue(any('not effective' in e for e in self.check()))
 def test_end_exclusive(self):
  self.p['evidence_aliases']['E001']['effective_until']='2024-11-01';self.assertTrue(any('not effective' in e for e in self.check()))
 def test_paraphrased_quote_rejected(self):
  self.row['evidence_requirements'][0]['quotes'][0]['quote']='消防设备必须完全有效';self.assertTrue(any('verbatim' in e for e in self.check()))
 def test_missing_condition_rejected(self):
  self.p['evidence_aliases']['E001']['conditions']={'highrise':True};self.assertTrue(any('applicability' in e for e in self.check()))
 def test_explicit_false_is_not_unknown(self):
  self.p['evidence_aliases']['E001']['conditions']={'highrise':True};self.p['cases'][0]['input']['scene']={'highrise':False};self.row['evidence_requirements'][0]['applicability']='conditional';self.assertTrue(any('conflicting' in e for e in self.check()))
 def test_unseen_image_not_invented(self):
  self.row['gold_observations']=[{'status':'uncertain','image_sha256':None}];self.assertTrue(any('image/observations' in e for e in self.check()))
 def test_human_review_cannot_bypass(self):
  self.row['needs_human_review']=False;self.assertTrue(any('human review' in e for e in self.check()))
 def test_image_hash_checked(self):
  self.p['cases'][0].update(image_present=True,image_sha256='correct');self.row['gold_observations']=[{'status':'uncertain','image_sha256':'wrong'}];self.assertTrue(any('image hash' in e for e in self.check()))
 def test_unknown_reference_rejected(self):
  self.row['reference_answer']+='[E999]';self.assertTrue(any('undeclared' in e for e in self.check()))
 def test_all_cases_once(self):self.assertTrue(a.validate({'annotations':[self.row,self.row]},self.p))
if __name__=='__main__':unittest.main()
