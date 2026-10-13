"""Validate supplied version lineage; never infer repeal/conditions from an LLM."""
from .fact_checks import condition_matches

def validate_versions(documents):
    versions={}
    for doc in documents:
        identifier=doc['version_id']
        if identifier in versions:raise ValueError('duplicate legal version_id')
        versions[identifier]=doc
        if doc.get('lifecycle') not in {'active','archived','revoked'}:raise ValueError('invalid legal lifecycle')
        if doc.get('lifecycle')=='archived' and not doc.get('effective_until'):
            raise ValueError('archived version requires an effective_until date')
        if doc.get('effective_from') and doc.get('effective_until') and doc['effective_until']<=doc['effective_from']:
            raise ValueError('invalid legal effective interval')
        groups=[doc.get('conditions',{})]+list(doc.get('clause_conditions',{}).values())
        for group in groups:
            if not isinstance(group,dict):raise ValueError('conditions must be a mapping')
            for value in group.values():
                # Validate the expression independent of whether a user supplied a fact.
                if isinstance(value,dict):condition_matches(0,value)
    for identifier,doc in versions.items():
        visited={identifier};previous=doc.get('previous_version_id')
        while previous:
            if previous in visited:raise ValueError('cyclic legal version chain')
            if previous not in versions:raise ValueError('version predecessor is missing from manifest')
            parent=versions[previous]
            if parent['logical_document_id']!=doc['logical_document_id']:raise ValueError('version chain crosses logical documents')
            visited.add(previous);previous=parent.get('previous_version_id')
    return versions
