"""Check evaluator semantics independently from product outputs."""
import importlib.util
from pathlib import Path

path=Path(__file__).resolve().parents[2]/'scripts/v2_coverage_runner.py'
spec=importlib.util.spec_from_file_location('coverage_runner',path)
runner=importlib.util.module_from_spec(spec);spec.loader.exec_module(runner)

def test_alternative_evidence_is_one_requirement():
 groups=[{'any_of':['a','b']},{'any_of':['c']}]
 result=runner.retrieval_group_metrics(['b','c'],groups)
 assert result['group_recall@5']==1 and result['all_groups@5']
 assert runner.retrieval_group_metrics(['a'],groups)['group_recall@5']==.5

def test_unscored_dimensions_remain_null():
 case={'suite':'business','expected':{'evaluation_mask':{'visual_binary':False,'visual_uncertainty':False,'retrieval_on_frozen_snapshot':False},
                                     'visual_decision':'not_applicable','evidence_requirements':[]}}
 result=runner.score_output(case,{'report':{'status':'draft'}})
 assert result['visual']['binary_match'] is None and result['visual']['three_state_match'] is None
 assert result['retrieval'] is None and result['semantic_correctness'] is None

def test_unknown_label_does_not_become_a_false_positive():
 case={'suite':'visual','expected':{'visual_status':'visible_anomaly','label_ids':['L-hose'],'label_texts':['无消防水带']}}
 result={'report':{'status':'draft'},'observations':[{'status':'visible_anomaly','labels':['无法自动映射的模型标签']}]}
 score=runner.score_output(case,result,[{'id':'L-hose','text':'无消防水带','aliases':['水带缺失']}])['visual']
 assert score['exact_label_match'] is None and not score['label_metric_eligible']
 assert score['unmapped_labels_require_review']

def test_aliases_and_punctuation_map_to_label_ids():
 case={'suite':'visual','expected':{'visual_status':'visible_anomaly','label_ids':['L-hose'],'label_texts':['无消防水带']}}
 result={'report':{'status':'draft'},'observations':[{'status':'visible_anomaly','labels':['水带缺失。']}]}
 score=runner.score_output(case,result,[{'id':'L-hose','text':'无消防水带','aliases':['水带缺失']}])['visual']
 assert score['exact_label_match'] and score['true_positive_labels']==1 and score['false_positive_labels']==0
