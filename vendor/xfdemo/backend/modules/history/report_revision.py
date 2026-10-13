from __future__ import annotations

import json
import threading
import uuid
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from backend.config.paths import INSPECTION_HISTORY_DIR
from backend.modules.history.report_document import (
    changed_report_fields,
    default_review_note,
    normalize_report_document,
    parse_report_document,
    render_report_document,
    report_document_hash,
)


REPORT_REVISION_FILE = INSPECTION_HISTORY_DIR / "report_revisions.jsonl"
_REVISION_LOCK = threading.RLock()


class RevisionConflictError(ValueError):
    pass


def _now() -> datetime:
    return datetime.now(ZoneInfo("Asia/Shanghai"))


def _editor_payload(user: dict[str, Any] | None) -> dict[str, str]:
    payload = user or {}
    return {
        "id": str(payload.get("id") or ""),
        "name": str(
            payload.get("displayName")
            or payload.get("username")
            or "当前用户"
        )[:80],
    }


def _read_all_unlocked() -> list[dict[str, Any]]:
    if not REPORT_REVISION_FILE.exists():
        return []
    revisions: list[dict[str, Any]] = []
    with REPORT_REVISION_FILE.open(encoding="utf-8", errors="replace") as handle:
        for line in handle:
            if not line.strip():
                continue
            try:
                revisions.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return revisions


def read_report_revisions(record_id: str = "", reverse: bool = True) -> list[dict[str, Any]]:
    with _REVISION_LOCK:
        revisions = _read_all_unlocked()
    if record_id:
        revisions = [
            revision
            for revision in revisions
            if revision.get("recordId") == record_id
        ]
    if reverse:
        revisions.reverse()
    return revisions


def report_revisions_by_record() -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for revision in read_report_revisions():
        grouped.setdefault(str(revision.get("recordId") or ""), []).append(revision)
    return grouped


def _model_document(record: dict[str, Any]) -> dict[str, Any]:
    document = record.get("modelReportDocument")
    if isinstance(document, dict):
        try:
            return normalize_report_document(document)
        except ValueError:
            pass
    return parse_report_document(record.get("response") or "")


def report_revision_state(
    record: dict[str, Any],
    revisions: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    model_document = _model_document(record)
    record_revisions = (
        revisions
        if revisions is not None
        else read_report_revisions(str(record.get("id") or ""))
    )
    latest = record_revisions[0] if record_revisions else None
    effective_document = normalize_report_document(
        latest.get("document") if latest else model_document
    )
    changed_from_model = changed_report_fields(model_document, effective_document)
    return {
        "modelReportDocument": model_document,
        "modelResponse": record.get("response") or render_report_document(model_document),
        "effectiveReportDocument": effective_document,
        "effectiveResponse": render_report_document(effective_document),
        "reportRevisions": record_revisions,
        "reportRevisionSummary": {
            "count": len(record_revisions),
            "latest": latest,
            "hasReview": bool(record_revisions),
            "hasCorrection": bool(changed_from_model),
        },
        "reviewNote": str((latest or {}).get("reviewNote") or ""),
    }


def create_report_revision(
    record: dict[str, Any],
    payload: dict[str, Any] | None,
    editor: dict[str, Any] | None,
) -> dict[str, Any]:
    request_data = payload or {}
    record_id = str(record.get("id") or "")
    if not record_id:
        raise ValueError("检测记录 ID 不能为空")

    model_document = _model_document(record)
    revised_document = normalize_report_document(request_data.get("document"))
    review_note = str(request_data.get("reviewNote") or "").strip()[:2000]
    requested_base = str(request_data.get("baseRevisionId") or "")

    with _REVISION_LOCK:
        all_revisions = _read_all_unlocked()
        record_revisions = [
            revision
            for revision in all_revisions
            if revision.get("recordId") == record_id
        ]
        latest = record_revisions[-1] if record_revisions else None
        latest_id = str((latest or {}).get("id") or "")
        if requested_base != latest_id:
            raise RevisionConflictError("报告已被其他操作更新，请刷新后重新修改")

        previous_document = normalize_report_document(
            latest.get("document") if latest else model_document
        )
        changed_fields = changed_report_fields(previous_document, revised_document)
        if not changed_fields and not review_note:
            raise ValueError("报告内容没有变化，请填写复核说明或修改报告")

        changed_from_model = changed_report_fields(model_document, revised_document)
        if not review_note:
            review_note = default_review_note(
                model_document,
                revised_document,
                changed_from_model,
            )

        created_at = _now()
        revision = {
            "id": uuid.uuid4().hex[:12],
            "recordId": record_id,
            "version": len(record_revisions) + 1,
            "baseRevisionId": latest_id,
            "createdAt": created_at.isoformat(),
            "createdText": created_at.strftime("%Y-%m-%d %H:%M:%S"),
            "editor": _editor_payload(editor),
            "changedFields": changed_fields,
            "changedFromModel": changed_from_model,
            "reviewNote": review_note,
            "document": revised_document,
            "beforeHash": report_document_hash(previous_document),
            "afterHash": report_document_hash(revised_document),
        }
        INSPECTION_HISTORY_DIR.mkdir(parents=True, exist_ok=True)
        with REPORT_REVISION_FILE.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(revision, ensure_ascii=False) + "\n")
    return revision


def _write_revisions(revisions: list[dict[str, Any]]) -> None:
    INSPECTION_HISTORY_DIR.mkdir(parents=True, exist_ok=True)
    temp_file = REPORT_REVISION_FILE.with_suffix(".tmp")
    with temp_file.open("w", encoding="utf-8") as handle:
        for revision in revisions:
            handle.write(json.dumps(revision, ensure_ascii=False) + "\n")
    temp_file.replace(REPORT_REVISION_FILE)


def delete_report_revisions_for_record(record_id: str) -> None:
    with _REVISION_LOCK:
        revisions = _read_all_unlocked()
        kept = [
            revision
            for revision in revisions
            if revision.get("recordId") != record_id
        ]
        if len(kept) != len(revisions):
            _write_revisions(kept)


def clear_report_revisions() -> int:
    with _REVISION_LOCK:
        count = len(_read_all_unlocked())
        if REPORT_REVISION_FILE.exists():
            REPORT_REVISION_FILE.unlink()
    return count
