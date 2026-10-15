"""Bounded adapters for detector localization and non-authoritative case retrieval."""
import math
import os
import time

import requests


class VisionEvidence:
    def __init__(self, url=None, post=None):
        self.url = (url or os.getenv('XF_VISION_URL', 'http://127.0.0.1:8007')).rstrip('/')
        self.post = post or requests.post

    def call(self, endpoint, payload, deadline, cap):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError('vision deadline exhausted')
        result = self.post(self.url + endpoint, json=payload, timeout=(min(3, remaining), min(cap, remaining)))
        result.raise_for_status()
        return result.json()

    def analyze(self, request, facility, deadline=None, include_cases=True):
        deadline = deadline or time.monotonic() + 50
        result = {'detector': {'enabled': False, 'detections': [], 'status': 'not_requested'},
                  'similar_cases': [], 'warnings': []}
        image = request.get('image')
        if image and facility in {'indoor_hydrant', 'outdoor_hydrant', 'fire_extinguisher'}:
            try:
                found = self.call('/detect', {'image': image, 'facility': facility}, deadline, 35)
                rows = []
                for item in found.get('detections', [])[:50]:
                    box = [float(x) for x in item.get('bboxNorm', [])]
                    score = float(item.get('confidence', 0))
                    if len(box) != 4 or not all(math.isfinite(x) and 0 <= x <= 1 for x in box):
                        continue
                    if box[0] >= box[2] or box[1] >= box[3] or not math.isfinite(score) or not 0 <= score <= 1:
                        continue
                    rows.append({'detector_id': 'd' + str(len(rows)+1), 'label': str(item.get('label', '目标'))[:100],
                                 'confidence': score, 'bboxNorm': box, 'source': 'detector'})
                enabled = found.get('enabled') is True
                result['detector'] = {'enabled': enabled, 'detections': rows,
                    'status': 'completed' if enabled else 'unavailable', 'model_scope': str(found.get('modelScope', found.get('modelType', '')))[:200],
                    'reason': str(found.get('reason', ''))[:300]}
                if not enabled:
                    result['warnings'].append('detector_unavailable')
            except (requests.RequestException, ValueError, KeyError, TypeError, TimeoutError):
                result['detector']['status'] = 'unavailable'
                result['warnings'].append('detector_unavailable')
        elif image:
            result['detector']['status'] = 'unsupported_facility'
        if include_cases:
            references = self.references(request, facility, deadline, result['detector']['detections'])
            result['similar_cases'] = references['similar_cases']
            result['warnings'].extend(references['warnings'])
            result['case_telemetry'] = references['case_telemetry']
        return result

    def references(self, request, facility, deadline=None, detections=None):
        from .cases import permitted, reviewed
        result = {'similar_cases': [], 'warnings': [], 'case_telemetry': {}}
        deadline = deadline or time.monotonic() + 20
        try:
            response = self.call('/cases', {'query': request.get('query', ''), 'image': request.get('image'),
                'project_id': request.get('project_id'), 'facility': facility,
                'regions': [d['bboxNorm'] for d in (detections or [])[:2]], 'k': 3}, deadline, 20)
            rows = response.get('cases', []) if isinstance(response, dict) else response
            if isinstance(response, dict):
                result['warnings'].extend(response.get('warnings', []))
                result['case_telemetry'] = {'routes': response.get('routes', [])}
            for case in rows[:10]:
                if not permitted(case, request.get('project_id')) or not reviewed(case):
                    continue
                score = float(case.get('score', 0))
                if not math.isfinite(score):
                    continue
                reference = {'case_id': str(case['id'])[:160], 'description': str(case['description'])[:1800],
                    'score': score, 'authority': 'historical_case_not_current_fact', 'usable_as_legal_evidence': False,
                    'review_status': case.get('review_status', 'legacy_review_unverified'),
                    'synthetic': case.get('synthetic', False), 'route_scores': case.get('route_scores', {}),
                    'linked_evidence_ids': [x for x in case.get('linked_evidence_ids', [])[:10] if isinstance(x, str)]}
                result['similar_cases'].append(reference)
                if len(result['similar_cases']) == 3:
                    break
        except (requests.RequestException, ValueError, KeyError, TypeError, TimeoutError):
            result['warnings'].append('case_reference_unavailable')
        return result
