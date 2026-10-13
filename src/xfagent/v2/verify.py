from .facts import fetch_evidence
from .schema import Conclusion
from .fact_checks import condition_matches,measurement_checks

def verify(store,state,conclusions=None):
    errors=[];requests=[];req=state['request']
    obs={o['observation_id']:o for o in state.get('observations',[])}
    selected={e['evidence_id']:e for e in state.get('evidence',[])}
    canonical={}
    # Validate what the model/reviewer actually saw, not just existence of its ID.
    fields=['text','quote_hash','source_hash','version_id','doc_id','snapshot_id','source_url','conditions','location','effective_from','effective_until','jurisdiction','status','lifecycle']
    for eid,reported in selected.items():
        e=fetch_evidence(store,state['snapshot_id'],eid,req['as_of'],req['jurisdiction'])
        canonical[eid]=e
        if e is None:
            errors.append({'code':'source_mismatch','evidence_id':eid});continue
        mismatched=[key for key in fields if reported.get(key)!=e.get(key)]
        if mismatched:errors.append({'code':'source_mismatch','evidence_id':eid,'fields':mismatched})
    claim_ids=set()
    output=[]
    for raw in conclusions if conclusions is not None else state.get('conclusions',[]):
        try:c=Conclusion.model_validate(raw).model_dump()
        except Exception:
            errors.append({'code':'invalid_claim_schema','claim_id':raw.get('claim_id','unknown')});continue
        cid=c['claim_id'];output.append(c)
        if not cid or cid in claim_ids:errors.append({'code':'duplicate_or_empty_claim_id','claim_id':cid})
        claim_ids.add(cid)
        if not c['text'].strip():errors.append({'code':'empty_claim_text','claim_id':cid})
        import re
        if c['kind']!='legal_assessment' and re.search(r'违反|违法|不符合.{0,12}(规范|标准|规定|要求)|依法|法律规定|根据.{0,12}(消防法|条例)',(c['text']+'。'+c.get('recommendation',''))):
            errors.append({'code':'legal_claim_in_nonlegal_field','claim_id':cid})
        for oid in c['observation_ids']:
            if oid not in obs:errors.append({'code':'unknown_observation','claim_id':cid})
        if c['kind']=='legal_assessment' and not c['evidence_ids']:
            errors.append({'code':'missing_evidence','claim_id':cid})
        if req['mode']=='inspection' and c['kind']=='legal_assessment' and not c['observation_ids']:
            errors.append({'code':'missing_observation','claim_id':cid})
        for eid in c['evidence_ids']:
            if eid not in selected:
                errors.append({'code':'forged_citation','claim_id':cid,'evidence_id':eid});continue
            e=canonical.get(eid)
            if e is None:
                errors.append({'code':'source_mismatch','claim_id':cid,'evidence_id':eid});continue
            for field,expected in e.get('conditions',{}).items():
                if field not in req['scene']:
                    requests.append(field)
                    if c['applicability']=='supported':errors.append({'code':'unknown_applicability','claim_id':cid,'field':field})
                else:
                    try:matches=condition_matches(req['scene'][field],expected)
                    except ValueError:
                        errors.append({'code':'invalid_applicability_metadata','claim_id':cid,'field':field});matches=False
                    if not matches:errors.append({'code':'inapplicable_evidence','claim_id':cid,'field':field})
        if c['kind']=='legal_assessment' and c['sufficiency']=='sufficient':
            if c['applicability']!='supported' or c['missing_fields']:
                errors.append({'code':'insufficient_claim','claim_id':cid})
            if any(obs[x]['status']=='uncertain' for x in c['observation_ids'] if x in obs):
                errors.append({'code':'uncertain_observation','claim_id':cid})
        requests.extend(c['missing_fields'])
    for c in output:
        measurement_errors,missing=measurement_checks({**c,'text':c['text']+'。'+c.get('recommendation','')},req['scene'])
        errors.extend(measurement_errors);requests.extend(missing)
    if not output:errors.append({'code':'empty_report','claim_id':'none'})
    return {'passed':not errors,'errors':errors,'missing_fields':sorted(set(requests)),
            'semantic_review':'pending','professional_review':'pending','conclusions':output}
