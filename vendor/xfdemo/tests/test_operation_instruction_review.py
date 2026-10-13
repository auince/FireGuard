import unittest

from backend.modules.inspection.labels import (
    ALLOWED_LABELS,
    APPEARANCE_LABELS,
    SUGGESTION_LABELS,
)
from backend.modules.inspection.messages import (
    apply_operation_instruction_review,
    parse_operation_instruction_verify,
)
from backend.modules.inspection.parser import labels_from_report, suggestions_from_report
from backend.modules.inspection.output_formatter import format_public_report


OPERATION_LABEL = "室内消火栓箱操作说明缺失或不清晰"
CHINESE_MARKING_LABEL = "室内消火栓箱门未清晰标注中文“消火栓”字样"


class OperationInstructionReviewTests(unittest.TestCase):
    def test_operation_instruction_is_an_active_appearance_hazard(self):
        self.assertIn(OPERATION_LABEL, APPEARANCE_LABELS)
        self.assertIn(OPERATION_LABEL, ALLOWED_LABELS)
        self.assertNotIn(OPERATION_LABEL, SUGGESTION_LABELS)

    def test_missing_instruction_is_added_without_overwriting_other_hazards(self):
        report = "\n".join([
            "检查范围：箱体外观",
            "结论：不合规",
            "可见依据：箱门中文标识无法辨认，箱体正面清晰可见。",
            f"隐患标签：{CHINESE_MARKING_LABEL}",
            "建议项：无",
        ])
        verify = {
            "instruction_missing_supported": True,
            "instruction_unclear_supported": False,
            "instruction_panel_visible": False,
            "instruction_readable": False,
            "evidence": "消火栓箱正面和箱门主要区域清晰可见，未见操作步骤或使用方法说明。",
        }

        updated = apply_operation_instruction_review(report, verify)

        self.assertEqual(
            labels_from_report(updated),
            [CHINESE_MARKING_LABEL, OPERATION_LABEL],
        )
        self.assertIn("箱门中文标识无法辨认", updated)
        self.assertIn("未见操作步骤或使用方法说明", updated)
        self.assertIn("结论：不合规", updated)

    def test_readable_instruction_removes_only_operation_hazard(self):
        report = "\n".join([
            "检查范围：箱体外观",
            "结论：不合规",
            "可见依据：箱门中文标识无法辨认；操作说明缺失。",
            f"隐患标签：{CHINESE_MARKING_LABEL}；{OPERATION_LABEL}",
            "建议项：室内消火栓箱体无铭牌",
        ])
        verify = {
            "instruction_missing_supported": False,
            "instruction_unclear_supported": False,
            "instruction_panel_visible": True,
            "instruction_readable": True,
            "evidence": "箱门下部可见完整操作说明面板，步骤文字和示意清楚。",
        }

        updated = apply_operation_instruction_review(report, verify)

        self.assertEqual(labels_from_report(updated), [CHINESE_MARKING_LABEL])
        self.assertEqual(suggestions_from_report(updated), ["室内消火栓箱体无铭牌"])
        self.assertIn("箱门中文标识无法辨认", updated)
        self.assertIn("完整操作说明面板", updated)
        self.assertIn("结论：不合规", updated)

    def test_distance_only_uncertainty_does_not_create_hazard(self):
        parsed = parse_operation_instruction_verify(
            """{
              "cabinet_front_sufficiently_visible": true,
              "instruction_panel_visible": true,
              "instruction_readable": false,
              "instruction_missing_supported": false,
              "instruction_unclear_supported": false,
              "needs_manual_review": true,
              "evidence": "可见疑似说明面板，但受拍摄距离影响无法读取小字。",
              "confidence": "低"
            }"""
        )

        self.assertIsNotNone(parsed)
        self.assertFalse(parsed["instruction_missing_supported"])
        self.assertFalse(parsed["instruction_unclear_supported"])
        self.assertTrue(parsed["needs_manual_review"])

    def test_public_report_contains_matching_operation_remediation(self):
        report = "\n".join([
            "\u68c0\u67e5\u8303\u56f4\uff1a\u7bb1\u4f53\u5916\u89c2",
            "\u7ed3\u8bba\uff1a\u4e0d\u5408\u89c4",
            "\u53ef\u89c1\u4f9d\u636e\uff1a\u6d88\u706b\u6813\u7bb1\u6b63\u9762\u548c\u7bb1\u95e8\u4e3b\u8981\u533a\u57df\u6e05\u6670\u53ef\u89c1\uff0c\u672a\u89c1\u64cd\u4f5c\u6b65\u9aa4\u6216\u4f7f\u7528\u65b9\u6cd5\u8bf4\u660e\u3002",
            f"\u9690\u60a3\u6807\u7b7e\uff1a{OPERATION_LABEL}",
            "\u5efa\u8bae\u9879\uff1a\u65e0",
        ])

        public_report = format_public_report(report)

        self.assertIn("\u4e00\u3001\u68c0\u6d4b\u7ed3\u8bba\uff1a\u4e0d\u5408\u683c", public_report)
        self.assertIn("\u64cd\u4f5c\u6b65\u9aa4\u6216\u4f7f\u7528\u65b9\u6cd5", public_report)
        self.assertIn("\u8865\u5145\u6e05\u6670\u3001\u8010\u4e45\u7684\u64cd\u4f5c\u8bf4\u660e", public_report)
        self.assertNotIn("\u5efa\u8bae\u4fdd\u6301\u8bbe\u65bd\u73b0\u72b6", public_report)


if __name__ == "__main__":
    unittest.main()
