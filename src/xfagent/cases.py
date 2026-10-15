"""Versioned image/text case retrieval; references never become legal evidence."""
import base64
import hashlib
import io
import json
import os
from pathlib import Path
import time
import uuid

import numpy as np
import requests
from PIL import Image

from .config import ROOT, read_json, write_json
from .retrieval import rrf


def encoder_id():
    return os.getenv('XF_MULTIMODAL_MODEL_ID', 'clip-vit-large-patch14')


def encode_cases(items, kind, timeout=30):
    url = os.getenv('XF_MULTIMODAL_URL', 'http://127.0.0.1:8002/embed')
    response = requests.post(url, json={'kind': kind, 'items': items}, timeout=(min(3, timeout), timeout))
    response.raise_for_status()
    payload = response.json()
    if payload.get('encoder_id', encoder_id()) != encoder_id():
        raise ValueError('multimodal encoder does not match configured model')
    vectors = np.asarray(payload['vectors'], dtype=np.float32)
    if (vectors.ndim != 2 or len(vectors) != len(items) or not np.isfinite(vectors).all()
            or (np.linalg.norm(vectors, axis=1) == 0).any()):
        raise ValueError('invalid multimodal embeddings')
    return vectors / np.linalg.norm(vectors, axis=1, keepdims=True)


def image_bytes(value):
    if not isinstance(value, str) or not value.startswith(('data:image/jpeg;base64,', 'data:image/png;base64,')):
        raise ValueError('only uploaded JPEG/PNG images are accepted')
    if len(value) > 14_000_000:
        raise ValueError('image too large')
    raw = base64.b64decode(value.split(',', 1)[1], validate=True)
    with Image.open(io.BytesIO(raw)) as picture:
        if picture.format not in {'JPEG', 'PNG'} or picture.width * picture.height > 16_000_000:
            raise ValueError('invalid image size or format')
        picture.verify()
    return raw


def crop_views(image, regions):
    """At most two detector regions, in addition to the full scene."""
    raw = image_bytes(image)
    views = [image]
    with Image.open(io.BytesIO(raw)) as picture:
        picture = picture.convert('RGB')
        for box in (regions or [])[:2]:
            if (len(box) != 4 or not all(isinstance(x, (float, int)) and 0 <= x <= 1 for x in box)
                    or box[0] >= box[2] or box[1] >= box[3]):
                continue
            coords = [round(box[i] * (picture.width if i % 2 == 0 else picture.height)) for i in range(4)]
            if coords[2] <= coords[0] or coords[3] <= coords[1]:
                continue
            output = io.BytesIO()
            picture.crop(coords).save(output, 'JPEG')
            views.append('data:image/jpeg;base64,' + base64.b64encode(output.getvalue()).decode())
    return list(dict.fromkeys(views))


def _upload(path):
    with Image.open(path) as picture:
        if picture.format not in {'JPEG', 'PNG'} or picture.width * picture.height > 16_000_000:
            raise ValueError('case image too large')
        output = io.BytesIO()
        picture.convert('RGB').save(output, 'JPEG')
    return 'data:image/jpeg;base64,' + base64.b64encode(output.getvalue()).decode()


def build_cases(source, limit=200):
    """Publish a complete generation atomically; input files are never Git assets."""
    from .data import rows, text_of
    if limit < 1:
        raise ValueError('limit must be positive')
    records, image_inputs, owners, seen = [], [], [], set()
    for row in rows(source):
        path = Path(row.get('image') or row['images'][0]).expanduser().resolve()
        identifier = str(row.get('id', len(records)))
        if identifier in seen:
            raise ValueError('duplicate case id')
        seen.add(identifier)
        description = row.get('description') or text_of(row, 'assistant')
        if not description.strip():
            raise ValueError('case description required')
        record = {key: row[key] for key in (
            'project_id', 'visibility', 'facility', 'review_status', 'human_reviewed',
            'synthetic', 'group_id', 'split', 'linked_evidence_ids', 'confirmed_conditions',
            'review_conclusion', 'remediation') if key in row}
        record.update(id=identifier, image=str(path), description=description,
                      image_sha256=hashlib.sha256(path.read_bytes()).hexdigest())
        record.setdefault('human_reviewed', False)
        record.setdefault('review_status', 'approved' if record['human_reviewed'] else 'pending')
        record.setdefault('split', 'reference')
        record.setdefault('group_id', identifier)
        views = crop_views(_upload(path), row.get('regions', []))
        image_inputs.extend(views)
        owners.extend([len(records)] * len(views))
        records.append(record)
        if len(records) >= limit:
            break
    if not records:
        raise ValueError('empty case dataset')
    root = ROOT / 'data/cases'
    generation = 'gen-' + uuid.uuid4().hex
    folder = root / generation
    folder.mkdir(parents=True)
    (folder / 'images').mkdir()
    # Keep each generation portable across host tools and read-only API containers.
    for i, record in enumerate(records):
        source_path = Path(record['image'])
        with Image.open(source_path) as picture:
            suffix = '.png' if picture.format == 'PNG' else '.jpg'
        relative = 'images/' + str(i) + suffix
        raw = source_path.read_bytes()
        if hashlib.sha256(raw).hexdigest() != record['image_sha256']:
            raise ValueError('case image changed during build')
        (folder / relative).write_bytes(raw)
        record['image'] = relative
    vectors = {}
    for field, inputs, kind in [('image', image_inputs, 'image_data'),
                                ('description', [r['description'] for r in records], 'text')]:
        vectors[field] = np.concatenate([encode_cases(inputs[i:i+16], kind, timeout=120)
                                        for i in range(0, len(inputs), 16)])
        np.save(folder / (field + '.npy'), vectors[field])
    if vectors['image'].shape[1] != vectors['description'].shape[1]:
        raise ValueError('image and text must use the same embedding space')
    write_json(folder / 'records.json', records)
    write_json(folder / 'owners.json', owners)
    files = ['image.npy', 'description.npy', 'records.json', 'owners.json']
    manifest = {'schema': 2, 'encoder_id': encoder_id(), 'count': len(records),
                'hashes': {name: hashlib.sha256((folder/name).read_bytes()).hexdigest() for name in files}}
    write_json(folder / 'manifest.json', manifest)
    temporary = root / (generation + '.pointer')
    write_json(temporary, {'generation': generation})
    os.replace(temporary, root / 'current.json')
    return {'indexed': len(records), 'image_views': len(owners), 'encoder': encoder_id(), 'generation': generation}


def load_index():
    root = ROOT / 'data/cases'
    pointer = read_json(root / 'current.json', {})
    if pointer:
        generation = pointer['generation']
        if not isinstance(generation, str) or not generation.startswith('gen-') or not generation[4:].isalnum():
            raise ValueError('invalid case index generation')
        root = root / generation
        manifest = read_json(root / 'manifest.json', {})
        if manifest.get('encoder_id') != encoder_id():
            raise ValueError('case index encoder changed; rebuild the index')
        for name in ('image.npy', 'description.npy', 'records.json', 'owners.json'):
            if hashlib.sha256((root/name).read_bytes()).hexdigest() != manifest.get('hashes', {}).get(name):
                raise ValueError('case index integrity mismatch')
    records = read_json(root / 'records.json', [])
    if not records:
        raise ValueError('case index has not been built')
    if pointer:
        for record in records:
            path = (root / record['image']).resolve()
            if not path.is_relative_to((root / 'images').resolve()):
                raise ValueError('case image outside index generation')
            record['image'] = str(path)
    images = np.load(root / 'image.npy', allow_pickle=False)
    texts = np.load(root / 'description.npy', allow_pickle=False)
    owners = read_json(root / 'owners.json', list(range(len(records))))
    if (images.ndim != 2 or texts.ndim != 2 or len(texts) != len(records) or len(images) != len(owners)
            or images.shape[1] != texts.shape[1] or not np.isfinite(images).all() or not np.isfinite(texts).all()
            or any(not isinstance(i, int) or not 0 <= i < len(records) for i in owners)):
        raise ValueError('invalid case index shape')
    return records, images, texts, owners


def permitted(record, project_id):
    scope = record.get('project_id')
    return (scope is not None and scope == project_id) or (scope is None and record.get('visibility') == 'shared')


def reviewed(record):
    return record.get('review_status') == 'approved' or (
        record.get('review_status') is None and record.get('human_reviewed') is True)


def retrieve_cases(query='', image=None, *, project_id=None, facility=None, regions=None,
                   k=5, mode='rrf', alpha=.5, deadline=None, exclude_ids=None, exclude_group_ids=None):
    if mode not in {'rrf', 'weighted', 'image_only'} or not 1 <= k <= 10 or not 0 <= alpha <= 1:
        raise ValueError('invalid case search options')
    if not isinstance(query, str) or len(query) > 1000:
        raise ValueError('invalid query text')
    if facility is not None and facility not in {'auto', 'unknown', 'indoor_hydrant', 'outdoor_hydrant', 'fire_extinguisher'}:
        raise ValueError('invalid facility')
    if not query.strip() and not image:
        raise ValueError('text or image required')
    deadline = deadline or time.monotonic() + 20
    records, images, texts, owners = load_index()
    warnings, rankings, details = [], [], {}
    excluded_ids, excluded_groups = set(exclude_ids or []), set(exclude_group_ids or [])
    image_hash = hashlib.sha256(image_bytes(image)).hexdigest() if image else None
    allowed = [i for i, r in enumerate(records) if permitted(r, project_id) and reviewed(r)
               and r.get('split', 'reference') not in {'test', 'eval', 'validation', 'dev'}
               and not r.get('disabled') and r['id'] not in excluded_ids
               and r.get('group_id', r['id']) not in excluded_groups
               and (not facility or facility in {'auto', 'unknown'} or r.get('facility') in {None, facility})
               and (not image_hash or r.get('image_sha256') != image_hash)]
    if not allowed:
        return {'cases': [], 'warnings': [], 'routes': []}
    routes = []
    inputs = ([('text', [query], 'text')] if query.strip() else [])
    if image:
        inputs.append(('image', crop_views(image, regions), 'image_data'))
    for route, values, kind in inputs:
        try:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError('case retrieval budget exhausted')
            vectors = encode_cases(values, kind, timeout=min(15, remaining))
            if vectors.shape[1] != texts.shape[1]:
                raise ValueError('query/index embedding dimension mismatch')
            image_scores = np.max(images @ vectors.T, axis=1)
            by_case = {i: -1. for i in allowed}
            for owner, score in zip(owners, image_scores):
                if owner in by_case:
                    by_case[owner] = max(by_case[owner], float(score))
            text_scores = np.max(texts @ vectors.T, axis=1)
            for target, scores in [('image', by_case), ('text', {i: float(text_scores[i]) for i in allowed})]:
                name = route + '_to_' + target
                for i in allowed:
                    details.setdefault(i, {})[name] = scores[i]
                if mode == 'rrf' or (mode == 'image_only' and target == 'image'):
                    rankings.append(sorted(allowed, key=lambda i: (-scores[i], records[i]['id']))[:40])
                    routes.append(name)
            if mode == 'weighted':
                scores = {i: alpha * by_case[i] + (1-alpha) * float(text_scores[i]) for i in allowed}
                rankings.append(sorted(allowed, key=lambda i: (-scores[i], records[i]['id']))[:40])
                routes.append(route + '_weighted')
        except (requests.RequestException, ValueError, TimeoutError, KeyError) as exc:
            warnings.append('case_' + route + '_unavailable:' + type(exc).__name__)
    ranking, scores = rrf(rankings)
    output, groups = [], set()
    for i in ranking:
        record = records[i]
        group = record.get('group_id', record['id'])
        if group in groups:
            continue
        groups.add(group)
        public = {key: record[key] for key in ('id', 'description', 'project_id', 'visibility', 'facility',
            'review_status', 'human_reviewed', 'synthetic', 'linked_evidence_ids', 'confirmed_conditions',
            'review_conclusion', 'remediation') if key in record}
        output.append({**public, 'score': scores[i], 'route_scores': details[i],
                       'authority': 'historical_case_not_current_fact', 'usable_as_legal_evidence': False})
        if len(output) == k:
            break
    return {'cases': output, 'warnings': warnings, 'routes': routes}


def search_cases(query, kind='text', mode='rrf', k=5, alpha=.5, **options):
    if kind not in {'text', 'image_data', 'image_path'}:
        raise ValueError('invalid input kind')
    image = _upload(query) if kind == 'image_path' else query if kind == 'image_data' else None
    return retrieve_cases(query if kind == 'text' else '', image, mode=mode, k=k, alpha=alpha, **options)['cases']


def case_image(case_id, project_id):
    records, _, _, _ = load_index()
    record = next((r for r in records if r['id'] == case_id and permitted(r, project_id) and reviewed(r)
                   and not r.get('disabled') and r.get('split', 'reference') not in {'test', 'eval', 'validation', 'dev'}), None)
    if record is None:
        return None
    path = Path(record['image'])
    if not path.is_file() or not record.get('image_sha256'):
        return None
    if hashlib.sha256(path.read_bytes()).hexdigest() != record['image_sha256']:
        raise ValueError('case image integrity mismatch')
    return path
