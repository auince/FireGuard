import tempfile
import unittest
from pathlib import Path

from backend.modules.history import report_revision
from backend.modules.history.report_document import (
    changed_report_fields,
    parse_report_document,
    render_report_document,
)


MODEL_REPORT = """一、检测结论：不合格
室内消火栓消防水枪缺失。

二、涉及法律法规
该功能建设中

三、整改建议
补配消防水枪。"""


class ReportDocumentTests(unittest.TestCase):
    def test_parse_and_render_round_trip(self):
        document = parse_report_document(MODEL_REPORT)

        self.assertEqual(document["verdict"], "unqualified")
        self.assertIn("消防水枪缺失", document["conclusion"])
        self.assertEqual(parse_report_document(render_report_document(document)), document)

    def test_changed_fields_are_section_scoped(self):
        before = parse_report_document(MODEL_REPORT)
        after = {**before, "verdict": "qualified", "conclusion": "组件完整。"}

        self.assertEqual(changed_report_fields(before, after), ["verdict", "conclusion"])


class ReportRevisionTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.original_dir = report_revision.INSPECTION_HISTORY_DIR
        self.original_file = report_revision.REPORT_REVISION_FILE
        report_revision.INSPECTION_HISTORY_DIR = Path(self.temp_dir.name)
        report_revision.REPORT_REVISION_FILE = Path(self.temp_dir.name) / "report_revisions.jsonl"
        self.record = {"id": "record-1", "response": MODEL_REPORT}

    def tearDown(self):
        report_revision.INSPECTION_HISTORY_DIR = self.original_dir
        report_revision.REPORT_REVISION_FILE = self.original_file
        self.temp_dir.cleanup()

    def test_revision_is_append_only_and_generates_review_note(self):
        model_document = parse_report_document(MODEL_REPORT)
        revised = {
            **model_document,
            "verdict": "qualified",
            "conclusion": "画面中消防水枪在位，组件完整。",
            "recommendations": "保持现状并定期巡检。",
        }

        revision = report_revision.create_report_revision(
            self.record,
            {"baseRevisionId": "", "document": revised, "reviewNote": ""},
            {"id": "u1", "displayName": "审核员"},
        )
        state = report_revision.report_revision_state(self.record)

        self.assertEqual(revision["version"], 1)
        self.assertIn("原模型结论为不合格", revision["reviewNote"])
        self.assertEqual(state["effectiveReportDocument"], revised)
        self.assertEqual(state["modelReportDocument"], model_document)
        self.assertTrue(state["reportRevisionSummary"]["hasReview"])
        self.assertTrue(state["reportRevisionSummary"]["hasCorrection"])

    def test_review_note_only_is_not_report_correction(self):
        document = parse_report_document(MODEL_REPORT)
        report_revision.create_report_revision(
            self.record,
            {
                "baseRevisionId": "",
                "document": document,
                "reviewNote": "人工复核后确认模型报告，无需修改。",
            },
            {},
        )

        summary = report_revision.report_revision_state(self.record)["reportRevisionSummary"]

        self.assertTrue(summary["hasReview"])
        self.assertFalse(summary["hasCorrection"])

    def test_stale_base_revision_is_rejected(self):
        document = parse_report_document(MODEL_REPORT)
        first = report_revision.create_report_revision(
            self.record,
            {
                "baseRevisionId": "",
                "document": {**document, "conclusion": "第一次修订。"},
                "reviewNote": "第一次修订。",
            },
            {},
        )
        self.assertTrue(first["id"])

        with self.assertRaises(report_revision.RevisionConflictError):
            report_revision.create_report_revision(
                self.record,
                {
                    "baseRevisionId": "",
                    "document": {**document, "conclusion": "过期修订。"},
                    "reviewNote": "过期修订。",
                },
                {},
            )


if __name__ == "__main__":
    unittest.main()
