import unittest

from backend.modules.inspection.messages import build_messages
from backend.modules.inspection.prompts import AUTO_PROMPT


class BranchPromptIsolationTests(unittest.TestCase):
    def test_indoor_prompt_payload_matches_legacy_shape(self):
        query = "请帮我判断这张图片里面的消防栓存在的异常"
        image = "data:image/jpeg;base64,dGVzdA=="
        yolo_result = {
            "detections": [
                {"label": "手轮", "confidence": 0.99},
                {"label": "接口", "confidence": 0.95},
            ],
        }

        messages = build_messages(
            query=query,
            image=image,
            task="internal_components",
            branch_key="indoor_hydrant",
            yolo_result=yolo_result,
        )

        self.assertEqual(messages[0]["content"][0]["image_url"]["url"], image)
        self.assertEqual(
            messages[0]["content"][1]["text"],
            f"{AUTO_PROMPT}\n固定检测任务：{query}",
        )
        self.assertNotIn("目标定位", messages[0]["content"][1]["text"])

    def test_new_branch_context_does_not_leak_into_indoor_prompt(self):
        query = "检查消防设施"
        messages = build_messages(
            query=query,
            image=None,
            task="internal_components",
            branch_key="indoor_hydrant",
            yolo_result={"detections": [{"label": "灭火器", "confidence": 0.9}]},
        )

        prompt = messages[0]["content"][0]["text"]
        self.assertEqual(prompt, f"{AUTO_PROMPT}\n固定检测任务：{query}")
        self.assertNotIn("已路由到", prompt)


if __name__ == "__main__":
    unittest.main()
