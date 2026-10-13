from xfagent.evidence_vision import VisionEvidence
from types import SimpleNamespace
import requests


def test_detector_validates_boxes_and_cases_never_become_facts():
    def post(url, **kwargs):
        data={'enabled':True,'detections':[{'bboxNorm':[.1,.2,.8,.9],'confidence':.8,'label':'栓体'},
            {'bboxNorm':[.9,.1,.2,.4],'confidence':.9}, {'bboxNorm':[0,0,1,1],'confidence':float('nan')}]}
        if url.endswith('/cases'):
            data=[{'id':'private','description':'other department','project_id':'other'},
                  {'id':'case1','description':'历史描述','human_reviewed':True,'score':.2,'image':'/private/path'}]
        return SimpleNamespace(raise_for_status=lambda:None,json=lambda:data)
    result=VisionEvidence(post=post).analyze({'query':'消火栓','image':'photo','project_id':'p'},'indoor_hydrant')
    assert len(result['detector']['detections'])==1
    assert result['similar_cases'][0]['case_id']=='case1'
    assert result['similar_cases'][0]['usable_as_legal_evidence'] is False
    assert result['similar_cases'][0]['review_status']=='legacy_review_unverified'
    assert 'image' not in result['similar_cases'][0]


def test_visual_outage_is_explicit_and_does_not_invent_detections():
    def fail(*a,**kw):raise requests.ConnectionError()
    result=VisionEvidence(post=fail).analyze({'query':'检查','image':'photo'},'indoor_hydrant')
    assert result['detector']['status']=='unavailable' and result['detector']['detections']==[]
    assert result['similar_cases']==[] and len(result['warnings'])==2
