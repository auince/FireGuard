#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import random
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

EXISTING_V3_DIR = Path('/opt/datasets/fire-inspection/training_data/20260627_hydrant_auto_visible_reasoning_v3')
INTERNAL_JSON_DIR = Path('/opt/datasets/fire-inspection/archive_extracted/20260430-室内消火栓组件组件合规图片已标注/室内消火栓组件组件合规图片已标注')
APPEARANCE_JSON_DIR = Path('/opt/datasets/fire-inspection/archive_extracted/20260428-室内消火栓箱外观合规/室内消火栓箱外观合规')
OUTPUT_DIR = Path('/opt/datasets/fire-inspection/training_data/20260628_hydrant_auto_visible_reasoning_v4_compliant_boost')
PROMPT_PATH = EXISTING_V3_DIR / 'prompt_v3_auto_scope.md'
IMAGE_EXTS = {'.jpg', '.jpeg', '.png', '.bmp', '.webp'}

INTERNAL_COMPONENT_NAMES = [
    ('箱体', ('箱体',)),
    ('箱门', ('箱门',)),
    ('手轮', ('手轮',)),
    ('栓口', ('栓口', '栓头', '阀体')),
    ('消防水带', ('水带',)),
    ('消防水枪', ('水枪',)),
    ('消防接口', ('消防接口',)),
    ('消防软管卷盘', ('软管卷盘', '卷盘')),
]
APPEARANCE_GOOD_NAMES = [
    ('箱体外观', ('箱体',)),
    ('箱门外观', ('箱门',)),
    ('操作说明', ('操作说明', '使用方法', '使用说明')),
    ('铭牌', ('铭牌',)),
    ('“消火栓”/FIRE HYDRANT标识', ('FIRE HYDRANT', '消火栓')),
]


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser()
    p.add_argument('--existing-dir', type=Path, default=EXISTING_V3_DIR)
    p.add_argument('--internal-json-dir', type=Path, default=INTERNAL_JSON_DIR)
    p.add_argument('--appearance-json-dir', type=Path, default=APPEARANCE_JSON_DIR)
    p.add_argument('--output-dir', type=Path, default=OUTPUT_DIR)
    p.add_argument('--val-ratio', type=float, default=0.1)
    p.add_argument('--seed', type=int, default=42)
    p.add_argument('--overwrite', action='store_true')
    return p.parse_args()


def normalize_text(value: Any) -> str:
    if value is None:
        return ''
    text = str(value).replace('\r\n', '\n').replace('\r', '\n')
    text = re.sub(r'[ \t]+', ' ', text)
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text.strip()


def is_system_file(path: Path) -> bool:
    return '__MACOSX' in path.parts or path.name.startswith('._') or path.name == '.DS_Store'


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open('r', encoding='utf-8') as f:
        for line in f:
            if line.strip():
                rows.append(json.loads(line))
    return rows


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open('w', encoding='utf-8') as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + '\n')


def image_sha1(path: Path) -> str:
    h = hashlib.sha1()
    with path.open('rb') as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def find_image_for_json(json_path: Path, data: dict[str, Any]) -> Path | None:
    candidates: list[Path] = []
    image_path = data.get('imagePath')
    if isinstance(image_path, str) and image_path.strip():
        raw = Path(image_path.strip())
        candidates.append(raw if raw.is_absolute() else json_path.parent / raw)
    for ext in sorted(IMAGE_EXTS):
        candidates.append(json_path.with_suffix(ext))
        candidates.append(json_path.with_suffix(ext.upper()))
    for candidate in candidates:
        if candidate.exists() and candidate.is_file() and not is_system_file(candidate):
            return candidate.resolve()
    return None


def load_labelme(path: Path) -> dict[str, Any]:
    with path.open('r', encoding='utf-8') as f:
        data = json.load(f)
    if not isinstance(data, dict):
        raise ValueError(f'{path}: root is not json object')
    return data


def extract_shape_texts(data: dict[str, Any]) -> tuple[list[str], list[str]]:
    labels: list[str] = []
    descriptions: list[str] = []
    for shape in data.get('shapes') or []:
        if not isinstance(shape, dict):
            continue
        label = normalize_text(shape.get('label'))
        desc = normalize_text(shape.get('description'))
        if label:
            labels.append(label)
        if desc:
            descriptions.append(desc)
    return labels, descriptions


def uniq(items: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        if item and item not in seen:
            seen.add(item)
            out.append(item)
    return out


def internal_normal_items(labels: list[str], descriptions: list[str]) -> list[str]:
    joined = '\n'.join(labels + descriptions)
    found = []
    for name, needles in INTERNAL_COMPONENT_NAMES:
        if any(needle in joined for needle in needles):
            found.append(name)
    return uniq(found)


def appearance_normal_items(labels: list[str], descriptions: list[str]) -> list[str]:
    joined = '\n'.join(labels + descriptions)
    found = []
    for name, needles in APPEARANCE_GOOD_NAMES:
        if any(needle in joined for needle in needles):
            found.append(name)
    return uniq(found)


def build_prompt(prompt_path: Path) -> str:
    text = prompt_path.read_text(encoding='utf-8')
    m = re.search(r'```text\n(.*?)\n```', text, re.S)
    if not m:
        raise ValueError(f'cannot extract prompt from {prompt_path}')
    return m.group(1).strip() + '\n'


def build_internal_answer(normal_items: list[str]) -> str:
    normal = '、'.join(normal_items) if normal_items else '箱内关键组件整体可见，未见明确缺失、损坏或方向异常'
    return (
        '检查范围：内部组件\n\n'
        '结论：合规\n\n'
        '检查过程：\n'
        '1. 画面判断：图片主要呈现室内消火栓箱内器材，检查证据集中在手轮、栓口、水带、水枪、接口或软管卷盘等内部组件，因此按内部组件检查。\n'
        f'2. 可见正常项：可见{normal}。\n'
        '3. 可见异常项：未见明确异常项。\n'
        '4. 无法判断项：无。\n\n'
        '判定依据：当前图片按内部组件进行检查，图片中可见关键组件未见明确缺失、损坏、严重锈蚀或方向异常，因此判定为合规。\n\n'
        '隐患标签：无。'
    )


def build_appearance_answer(normal_items: list[str]) -> str:
    normal = '、'.join(normal_items) if normal_items else '箱体外观、箱门标识、操作说明和铭牌处未见明确异常'
    return (
        '检查范围：箱体外观\n\n'
        '结论：合规\n\n'
        '检查过程：\n'
        '1. 画面判断：图片主要呈现消火栓箱体正面、箱门、标识、操作说明或铭牌等外观信息，因此按箱体外观检查。\n'
        f'2. 可见正常项：可见{normal}。\n'
        '3. 可见异常项：未见明确异常项。\n'
        '4. 无法判断项：无。\n\n'
        '判定依据：当前图片按箱体外观进行检查，图片中未见箱门标识、操作说明、铭牌、材质或遮挡方面的明确异常，因此判定为合规。\n\n'
        '隐患标签：无。'
    )


def split_new_rows(rows: list[dict[str, Any]], val_ratio: float, seed: int) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    by_task: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        by_task[row['meta']['task']].append(row)
    rng = random.Random(seed)
    train: list[dict[str, Any]] = []
    val: list[dict[str, Any]] = []
    for task, group in sorted(by_task.items()):
        group = sorted(group, key=lambda x: x['meta']['image_sha1'])
        rng.shuffle(group)
        if len(group) <= 1:
            val_n = 0
        else:
            val_n = max(1, round(len(group) * val_ratio))
            val_n = min(val_n, len(group) - 1)
        val.extend(group[:val_n])
        train.extend(group[val_n:])
    return sorted(train, key=lambda x: x['meta']['image_sha1']), sorted(val, key=lambda x: x['meta']['image_sha1'])


def existing_hashes(rows: list[dict[str, Any]]) -> set[str]:
    return {row.get('meta', {}).get('image_sha1') for row in rows if row.get('meta', {}).get('image_sha1')}


def build_internal_rows(existing_hash_set: set[str], prompt: str) -> tuple[list[dict[str, Any]], dict[str, int]]:
    rows = []
    counters = Counter()
    for json_path in sorted(p for p in INTERNAL_JSON_DIR.glob('*.json') if not is_system_file(p)):
        counters['json_files'] += 1
        data = load_labelme(json_path)
        image = find_image_for_json(json_path, data)
        if not image:
            counters['missing_image'] += 1
            continue
        sha1 = image_sha1(image)
        if sha1 in existing_hash_set:
            counters['duplicate_with_existing'] += 1
            continue
        labels, descriptions = extract_shape_texts(data)
        normal_items = internal_normal_items(labels, descriptions)
        rows.append({
            'images': [str(image)],
            'messages': [
                {'role': 'user', 'content': [{'type': 'image', 'image': str(image)}, {'type': 'text', 'text': prompt}]},
                {'role': 'assistant', 'content': [{'type': 'text', 'text': build_internal_answer(normal_items)}]},
            ],
            'meta': {
                'task': 'internal_components',
                'verdict': '合规',
                'defect_labels': [],
                'defect_keys': [],
                'image_sha1': sha1,
                'source_dataset': str(INTERNAL_JSON_DIR),
                'source_images': [str(image)],
                'source_jsons': [str(json_path)],
                'source_kind': 'internal_compliant_boost',
                'normal_items': normal_items,
                'prompt_version': 'v4_auto_scope_visible_reasoning',
            },
        })
        existing_hash_set.add(sha1)
        counters['added'] += 1
    return rows, dict(counters)


def build_appearance_rows(existing_hash_set: set[str], prompt: str) -> tuple[list[dict[str, Any]], dict[str, int]]:
    rows = []
    counters = Counter()
    for json_path in sorted(p for p in APPEARANCE_JSON_DIR.glob('*.json') if not is_system_file(p)):
        counters['json_files'] += 1
        data = load_labelme(json_path)
        image = find_image_for_json(json_path, data)
        if not image:
            counters['missing_image'] += 1
            continue
        sha1 = image_sha1(image)
        if sha1 in existing_hash_set:
            counters['duplicate_with_existing'] += 1
            continue
        labels, descriptions = extract_shape_texts(data)
        normal_items = appearance_normal_items(labels, descriptions)
        rows.append({
            'images': [str(image)],
            'messages': [
                {'role': 'user', 'content': [{'type': 'image', 'image': str(image)}, {'type': 'text', 'text': prompt}]},
                {'role': 'assistant', 'content': [{'type': 'text', 'text': build_appearance_answer(normal_items)}]},
            ],
            'meta': {
                'task': 'appearance',
                'verdict': '合规',
                'defect_labels': [],
                'defect_keys': [],
                'image_sha1': sha1,
                'source_dataset': str(APPEARANCE_JSON_DIR),
                'source_images': [str(image)],
                'source_jsons': [str(json_path)],
                'source_kind': 'appearance_compliant_boost',
                'normal_items': normal_items,
                'prompt_version': 'v4_auto_scope_visible_reasoning',
            },
        })
        existing_hash_set.add(sha1)
        counters['added'] += 1
    return rows, dict(counters)


def assign_ids(rows: list[dict[str, Any]], train_start: int, val_start: int) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    train, val = split_new_rows(rows, args.val_ratio, args.seed)
    for i, row in enumerate(train, start=train_start):
        row['id'] = f'xf_hydrant_auto_v4_train_{i:06d}'
    for i, row in enumerate(val, start=val_start):
        row['id'] = f'xf_hydrant_auto_v4_val_{i:06d}'
    return train, val


def max_suffix(rows: list[dict[str, Any]], prefix: str) -> int:
    max_id = 0
    for row in rows:
        rid = row.get('id', '')
        m = re.match(rf'^{re.escape(prefix)}(\d+)$', rid)
        if m:
            max_id = max(max_id, int(m.group(1)))
    return max_id


def main() -> None:
    global args
    args = parse_args()
    if args.output_dir.exists() and any(args.output_dir.iterdir()) and not args.overwrite:
        raise FileExistsError(f'output exists: {args.output_dir}')
    args.output_dir.mkdir(parents=True, exist_ok=True)

    existing_all = read_jsonl(args.existing_dir / 'all.jsonl')
    existing_train = read_jsonl(args.existing_dir / 'train.jsonl')
    existing_val = read_jsonl(args.existing_dir / 'val.jsonl')
    prompt = build_prompt(PROMPT_PATH)
    hashes = existing_hashes(existing_all)

    new_internal, internal_stats = build_internal_rows(hashes, prompt)
    new_appearance, appearance_stats = build_appearance_rows(hashes, prompt)
    new_rows = new_internal + new_appearance

    train_start = max_suffix(existing_train, 'xf_hydrant_auto_v3_train_') + 1
    val_start = max_suffix(existing_val, 'xf_hydrant_auto_v3_val_') + 1
    new_train, new_val = assign_ids(new_rows, train_start, val_start)

    all_rows = existing_all + new_train + new_val
    train_rows = existing_train + new_train
    val_rows = existing_val + new_val

    write_jsonl(args.output_dir / 'all.jsonl', all_rows)
    write_jsonl(args.output_dir / 'train.jsonl', train_rows)
    write_jsonl(args.output_dir / 'val.jsonl', val_rows)
    (args.output_dir / 'prompt_v4_auto_scope.md').write_text(PROMPT_PATH.read_text(encoding='utf-8'), encoding='utf-8')

    summary = {
        'input_dir': str(args.existing_dir),
        'output_dir': str(args.output_dir),
        'prompt_version': 'v4_auto_scope_visible_reasoning',
        'rows': len(all_rows),
        'train_rows': len(train_rows),
        'val_rows': len(val_rows),
        'added_rows': len(new_rows),
        'added_train_rows': len(new_train),
        'added_val_rows': len(new_val),
        'rows_by_task': dict(Counter(row['meta']['task'] for row in all_rows)),
        'verdict_by_task': {task: dict(Counter(row['meta']['verdict'] for row in all_rows if row['meta']['task'] == task)) for task in sorted({row['meta']['task'] for row in all_rows})},
        'new_rows_by_task': dict(Counter(row['meta']['task'] for row in new_rows)),
        'internal_compliant_stats': internal_stats,
        'appearance_compliant_stats': appearance_stats,
        'notes': [
            'Built by appending compliant boost rows to the existing v3 auto-scope dataset.',
            'Only new image hashes absent from the existing v3 dataset are added.',
            'New rows are compliant internal and appearance examples intended to reduce false positives and strengthen real single-image behavior.',
        ],
    }
    with (args.output_dir / 'summary.json').open('w', encoding='utf-8') as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)
        f.write('\n')
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
