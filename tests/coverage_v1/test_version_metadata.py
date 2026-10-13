import pytest
from xfagent.v2.version_metadata import validate_versions

def versions():
    return [{'version_id':'v1','logical_document_id':'law','lifecycle':'archived',
             'effective_from':'2020-01-01','effective_until':'2024-01-01'},
            {'version_id':'v2','logical_document_id':'law','lifecycle':'active',
             'previous_version_id':'v1','effective_from':'2024-01-01',
             'conditions':{'building_height':{'gte':24}}}]

def test_supplied_version_chain():assert set(validate_versions(versions()))=={'v1','v2'}

@pytest.mark.parametrize('mutation',['duplicate','cycle','missing','cross_document','archived_date','interval','operator'])
def test_invalid_version_metadata(mutation):
    rows=versions()
    if mutation=='duplicate':rows[1]['version_id']='v1'
    if mutation=='cycle':rows[0]['previous_version_id']='v2'
    if mutation=='missing':rows[1]['previous_version_id']='unlisted'
    if mutation=='cross_document':rows[0]['logical_document_id']='unrelated'
    if mutation=='archived_date':rows[0].pop('effective_until')
    if mutation=='interval':rows[0]['effective_until']='2019-01-01'
    if mutation=='operator':rows[1]['conditions']={'height':{'unknown':24}}
    with pytest.raises(ValueError):validate_versions(rows)
