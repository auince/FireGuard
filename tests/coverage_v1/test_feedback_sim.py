import copy,json
from pathlib import Path
import pytest
from test_contract_cases import fixture_store, initial
from xfagent.v2.schema import Feedback,Review,Actor
from xfagent.v2.feedback import feedback_graph
from xfagent.v2.policy import Policies

@pytest.mark.parametrize('category,missing,kind',[
 ('generation',[],'hook'),('applicability',['pressure_measurement'],'rule'),
 ('applicability',['required_quantity','unknown_field'],'rule'),
 ('applicability',['disable_verifier'],'hook')])
def test_feedback_produces_bounded_candidate(fixture_store,category,missing,kind):
 s=fixture_store;f={'_id':'f','owner':'a','category':category,'signal':'correction','text':'模拟复核意见'}
 s.db.feedback.insert_one(f)
 source={'_id':'source','input':initial(s)['request'],'project_id':'default','owner':'a',
  'result':{'report':{'verification':{'missing_fields':missing}}}}
 result=feedback_graph(s).invoke({'feedback':f,'source':source})
 candidate=s.db.policies.find_one({'_id':result['candidate_id']})
 assert candidate['state']=='draft' and candidate['spec']['kind']==kind
 assert 'disable_verifier' not in candidate['spec']['require_fields']
 if kind=='rule':
  with pytest.raises(ValueError,match='Rule'):Policies(s).publish(candidate['_id'],Actor(user_id='a',role='admin',projects=['default']),5,1)
 else:assert candidate['spec']['hook']=='before_draft'

def test_control_session_does_not_turn_into_triggered_treatment(fixture_store):
 p=Policies(fixture_store)
 a=p.choose('a','default','same-session','消防箱','indoor_hydrant')
 b=p.choose('a','default','same-session','消防箱','indoor_hydrant')
 assert a==b and a['group']=='control' and not b['triggered']

def test_simulated_data_contract():
 root=Path('benchmarks/feedback_sim_v1')
 feedback=[json.loads(x) for x in (root/'human_feedback.jsonl').read_text().splitlines()]
 reviews=[json.loads(x) for x in (root/'human_reviews.jsonl').read_text().splitlines()]
 dialogues=[json.loads(x) for x in (root/'feedback_dialogues.jsonl').read_text().splitlines()]
 assert (len(feedback),len(reviews),len(dialogues))==(240,120,60)
 assert len({x['id'] for x in feedback+reviews+dialogues})==420
 for case in feedback:
  Feedback.model_validate(case['feedback_payload'])
  assert case['simulation_only'] and not case['origin']['real_human'] and not case['origin']['expert_verified']
 for case in reviews:Review.model_validate(case['review_payload'])
 assert {x['feedback_id'] for x in dialogues}<={x['id'] for x in feedback}
