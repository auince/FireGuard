from __future__ import annotations

import base64
import json
import os
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from backend.config.paths import PROJECT_ROOT, YOLO_OUTPUT_ROOT, YOLO_TMP_DIR
YOLO_PYTHON = Path(os.getenv("YOLO_PYTHON", "/opt/conda/envs/detector/bin/python")).resolve()
YOLO_INFER_SCRIPT = Path(os.getenv("YOLO_INFER_SCRIPT", str(PROJECT_ROOT / "scripts" / "yolo_infer.py"))).resolve()
DEFAULT_MODEL_DIR = YOLO_OUTPUT_ROOT
INTERNAL_WEIGHTS = Path(os.getenv("YOLO_INTERNAL_WEIGHTS", str(DEFAULT_MODEL_DIR / "fire_hydrant_v3.pt"))).resolve()
APPEARANCE_WEIGHTS = Path(os.getenv("YOLO_APPEARANCE_WEIGHTS", str(DEFAULT_MODEL_DIR / "fire_hydrant_exter_v3.pt"))).resolve()
OUTDOOR_HYDRANT_WEIGHTS = Path(os.getenv(
    "YOLO_OUTDOOR_HYDRANT_WEIGHTS",
    "/opt/xfagent/artifacts/yolo/20260723_yolo_outdoor_hydrant_v2/train/outdoor_hydrant_yolo11n/weights/best.pt",
)).resolve()
FIRE_EXTINGUISHER_WEIGHTS = Path(os.getenv(
    "YOLO_FIRE_EXTINGUISHER_WEIGHTS",
    "/opt/xfagent/artifacts/yolo/20260723_yolo_fire_extinguisher_v2/train/fire_extinguisher_yolo11n/weights/best.pt",
)).resolve()
CLASSES_FILE = Path(os.getenv("YOLO_CLASSES_FILE", str(DEFAULT_MODEL_DIR / "classes.json"))).resolve()
DEFAULT_CONF = float(os.getenv("YOLO_CONF", "0.20"))
DEFAULT_IMGSZ = int(os.getenv("YOLO_IMGSZ", "640"))
DEFAULT_DEVICE = os.getenv("YOLO_DEVICE", "0")
DEFAULT_TIMEOUT = int(os.getenv("YOLO_TIMEOUT", "90"))
MIN_GPU_FREE_MB = int(os.getenv("YOLO_MIN_GPU_FREE_MB", "1024"))
TMP_DIR = YOLO_TMP_DIR

DEFAULT_COMPONENT_CLASSES = ["手轮", "接口", "控制器", "栓体", "水带", "水枪", "软管", "阀门"]
DEFAULT_APPEARANCE_CLASSES = ["中文标识", "把手", "操作说明", "消火栓", "箱门", "英文标识", "装饰性箱门", "铭牌"]
OUTDOOR_HYDRANT_CLASSES = ["室外消火栓"]
FIRE_EXTINGUISHER_CLASSES = ["灭火器", "灭火器压力指示器"]


def _load_internal_class_labels() -> dict[str, str]:
    if CLASSES_FILE.exists():
        try:
            raw = json.loads(CLASSES_FILE.read_text(encoding="utf-8"))
            if isinstance(raw, list):
                return {str(index): str(name) for index, name in enumerate(raw)}
            if isinstance(raw, dict):
                return {str(key): str(value) for key, value in raw.items()}
        except Exception:
            pass
    return {str(index): name for index, name in enumerate(DEFAULT_COMPONENT_CLASSES)}


INTERNAL_CLASS_LABELS = _load_internal_class_labels()
APPEARANCE_CLASS_LABELS = {str(index): name for index, name in enumerate(DEFAULT_APPEARANCE_CLASSES)}


def _is_appearance_task(task: str) -> bool:
    normalized = (task or "auto").strip().lower()
    return normalized in {"appearance", "box_appearance", "箱体外观", "外观"}


def _normalize_model_task(task: str) -> str:
    normalized = (task or "auto").strip().lower()
    if normalized in {"outdoor", "outdoor_hydrant", "室外消火栓"}:
        return "outdoor_hydrant"
    if normalized in {"fire_extinguisher", "extinguisher", "灭火器"}:
        return "fire_extinguisher"
    if _is_appearance_task(normalized):
        return "appearance"
    return "internal_components"


def _class_labels_for_task(task: str) -> dict[str, str]:
    model_task = _normalize_model_task(task)
    if model_task == "appearance":
        return APPEARANCE_CLASS_LABELS
    if model_task == "outdoor_hydrant":
        return {str(index): name for index, name in enumerate(OUTDOOR_HYDRANT_CLASSES)}
    if model_task == "fire_extinguisher":
        return {str(index): name for index, name in enumerate(FIRE_EXTINGUISHER_CLASSES)}
    return INTERNAL_CLASS_LABELS


def _weights_for_task(task: str) -> Path:
    model_task = _normalize_model_task(task)
    if model_task == "appearance":
        return APPEARANCE_WEIGHTS
    if model_task == "outdoor_hydrant":
        return OUTDOOR_HYDRANT_WEIGHTS
    if model_task == "fire_extinguisher":
        return FIRE_EXTINGUISHER_WEIGHTS
    return INTERNAL_WEIGHTS


def _scope_for_task(task: str) -> str:
    model_task = _normalize_model_task(task)
    if model_task == "appearance":
        return "箱体外观"
    if model_task == "outdoor_hydrant":
        return "室外消火栓"
    if model_task == "fire_extinguisher":
        return "灭火器"
    return "内部组件"


def _type_for_task(task: str) -> str:
    model_task = _normalize_model_task(task)
    if model_task == "appearance":
        return "appearance_presence"
    if model_task == "outdoor_hydrant":
        return "outdoor_hydrant_presence"
    if model_task == "fire_extinguisher":
        return "fire_extinguisher_presence"
    return "component_presence"


def _enabled() -> bool:
    return os.getenv("YOLO_ENABLED", "1").strip().lower() not in {"0", "false", "no", "off"}


def _empty_result(enabled: bool = False, reason: str = "", task: str = "internal_components") -> dict[str, Any]:
    labels = _class_labels_for_task(task)
    model_task = _normalize_model_task(task)
    return {
        "enabled": enabled,
        "modelScope": _scope_for_task(task),
        "modelType": _type_for_task(task),
        "weights": str(_weights_for_task(task)),
        "classesFile": str(CLASSES_FILE) if model_task == "internal_components" else "model.names",
        "classes": list(labels.values()),
        "confThreshold": DEFAULT_CONF,
        "imgsz": DEFAULT_IMGSZ,
        "device": DEFAULT_DEVICE,
        "detections": [],
        "reason": reason,
    }


def _image_suffix(mime: str) -> str:
    mime = (mime or "").lower()
    if "png" in mime:
        return ".png"
    if "webp" in mime:
        return ".webp"
    return ".jpg"


def _write_temp_image(image: str | None) -> Path | None:
    if not image:
        return None
    value = image.strip()
    if not value.startswith("data:"):
        return None
    header, _, payload = value.partition(",")
    if not payload:
        return None
    mime = header[5:].split(";", 1)[0] if header.startswith("data:") else "image/jpeg"
    content = base64.b64decode(payload)
    TMP_DIR.mkdir(parents=True, exist_ok=True)
    handle = tempfile.NamedTemporaryFile(prefix="inspect_", suffix=_image_suffix(mime), dir=TMP_DIR, delete=False)
    try:
        handle.write(content)
        return Path(handle.name)
    finally:
        handle.close()


def _parse_stdout(stdout: str) -> dict[str, Any]:
    for line in reversed((stdout or "").splitlines()):
        if line.startswith("YOLO_JSON_RESULT="):
            return json.loads(line.split("=", 1)[1])
    raise ValueError("YOLO JSON result marker not found")


def _gpu_free_memory() -> dict[str, int]:
    try:
        proc = subprocess.run(
            ["nvidia-smi", "--query-gpu=index,memory.free", "--format=csv,noheader,nounits"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except Exception:
        return {}
    if proc.returncode != 0:
        return {}
    free_memory: dict[str, int] = {}
    for line in proc.stdout.splitlines():
        parts = [part.strip() for part in line.split(",")]
        if len(parts) != 2:
            continue
        try:
            free_memory[parts[0]] = int(parts[1])
        except ValueError:
            continue
    return free_memory


def _candidate_devices() -> list[str]:
    configured = str(DEFAULT_DEVICE).strip() or "0"
    if configured.lower() == "cpu":
        return ["cpu"]
    free_memory = _gpu_free_memory()
    if not free_memory:
        return [configured, "cpu"]
    devices: list[str] = []
    if free_memory.get(configured, 0) >= MIN_GPU_FREE_MB:
        devices.append(configured)
    for device, free_mb in sorted(free_memory.items(), key=lambda item: item[1], reverse=True):
        if free_mb >= MIN_GPU_FREE_MB and device not in devices:
            devices.append(device)
    devices.append("cpu")
    return devices



def _bbox_xyxy(item: dict[str, Any]) -> list[float]:
    bbox = item.get("bbox") or []
    if len(bbox) != 4:
        return []
    try:
        x1, y1, x2, y2 = [float(v) for v in bbox]
    except Exception:
        return []
    if x2 <= x1 or y2 <= y1:
        return []
    return [x1, y1, x2, y2]


def _area(box: list[float]) -> float:
    if len(box) != 4:
        return 0.0
    return max(0.0, box[2] - box[0]) * max(0.0, box[3] - box[1])


def _iou(left: list[float], right: list[float]) -> float:
    if len(left) != 4 or len(right) != 4:
        return 0.0
    ix1 = max(left[0], right[0])
    iy1 = max(left[1], right[1])
    ix2 = min(left[2], right[2])
    iy2 = min(left[3], right[3])
    inter = _area([ix1, iy1, ix2, iy2])
    union = _area(left) + _area(right) - inter
    return inter / union if union > 0 else 0.0


def _contained_ratio(inner: list[float], outer: list[float]) -> float:
    if len(inner) != 4 or len(outer) != 4:
        return 0.0
    ix1 = max(inner[0], outer[0])
    iy1 = max(inner[1], outer[1])
    ix2 = min(inner[2], outer[2])
    iy2 = min(inner[3], outer[3])
    inter = _area([ix1, iy1, ix2, iy2])
    base = _area(inner)
    return inter / base if base > 0 else 0.0


def suppress_overlapping_detections(detections: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Keep the prompt/display signal clean: remove duplicate boxes of the same component."""
    grouped: dict[str, list[dict[str, Any]]] = {}
    for item in detections:
        label = str(item.get("label") or item.get("component") or item.get("className") or "").strip()
        grouped.setdefault(label, []).append(item)

    kept: list[dict[str, Any]] = []
    for label, items in grouped.items():
        selected: list[dict[str, Any]] = []
        ordered = sorted(items, key=lambda x: float(x.get("confidence") or 0), reverse=True)
        for item in ordered:
            box = _bbox_xyxy(item)
            if not box:
                continue
            duplicate = False
            for chosen in selected:
                chosen_box = _bbox_xyxy(chosen)
                if _iou(box, chosen_box) >= 0.72 or _contained_ratio(box, chosen_box) >= 0.88 or _contained_ratio(chosen_box, box) >= 0.92:
                    duplicate = True
                    break
            if not duplicate:
                selected.append(item)
            if len(selected) >= 3:
                break
        kept.extend(selected)

    return sorted(kept, key=lambda x: float(x.get("confidence") or 0), reverse=True)[:24]


def compact_detections_for_prompt(detections: list[dict[str, Any]]) -> list[dict[str, Any]]:
    compact: list[dict[str, Any]] = []
    grouped: dict[str, list[dict[str, Any]]] = {}
    for item in suppress_overlapping_detections(detections):
        label = str(item.get("label") or item.get("component") or item.get("className") or "").strip()
        grouped.setdefault(label, []).append(item)
    for label, items in sorted(grouped.items(), key=lambda pair: max(float(x.get("confidence") or 0) for x in pair[1]), reverse=True):
        top = max(items, key=lambda x: float(x.get("confidence") or 0))
        compact.append({
            "label": label,
            "count": len(items),
            "confidence": float(top.get("confidence") or 0),
            "bboxNorm": [round(float(v), 4) for v in (top.get("bboxNorm") or [])[:4]],
        })
    return compact

def run_yolo_detection(image: str | None, task: str = "auto") -> dict[str, Any]:
    model_task = _normalize_model_task(task)
    weights = _weights_for_task(model_task)
    class_labels = _class_labels_for_task(model_task)
    if not _enabled():
        return _empty_result(False, "YOLO disabled by YOLO_ENABLED", model_task)
    if not YOLO_PYTHON.exists():
        return _empty_result(False, f"YOLO python not found: {YOLO_PYTHON}", model_task)
    if not YOLO_INFER_SCRIPT.exists():
        return _empty_result(False, f"YOLO infer script not found: {YOLO_INFER_SCRIPT}", model_task)
    if not weights.exists():
        return _empty_result(False, f"YOLO weights not found: {weights}", model_task)
    temp_image = None
    try:
        temp_image = _write_temp_image(image)
        if not temp_image:
            return _empty_result(False, "YOLO currently supports uploaded data-url images only", model_task)
        attempted_devices: list[str] = []
        failures: list[dict[str, Any]] = []
        for device in _candidate_devices():
            attempted_devices.append(device)
            cmd = [
                str(YOLO_PYTHON),
                str(YOLO_INFER_SCRIPT),
                "--weights", str(weights),
                "--image", str(temp_image),
                "--conf", str(DEFAULT_CONF),
                "--imgsz", str(DEFAULT_IMGSZ),
                "--device", device,
            ]
            try:
                proc = subprocess.run(cmd, capture_output=True, text=True, timeout=DEFAULT_TIMEOUT, check=False)
            except subprocess.TimeoutExpired:
                failures.append({"device": device, "returncode": None, "stderr": "YOLO subprocess timeout"})
                continue
            if proc.returncode != 0:
                failures.append({"device": device, "returncode": proc.returncode, "stderr": (proc.stderr or "")[-2000:]})
                continue
            try:
                payload = _parse_stdout(proc.stdout)
            except Exception as exc:
                failures.append({"device": device, "returncode": proc.returncode, "stderr": str(exc)})
                continue
            detections = []
            for item in payload.get("detections") or []:
                class_name = str(item.get("className", ""))
                class_id = str(item.get("classId", ""))
                label = class_labels.get(class_name) or class_labels.get(class_id) or class_name
                detections.append({
                    **item,
                    "label": label,
                    "component": label,
                    "modelScope": _scope_for_task(model_task),
                    "modelType": _type_for_task(model_task),
                })
            return {
                "enabled": True,
                "modelScope": _scope_for_task(model_task),
                "modelType": _type_for_task(model_task),
                "weights": str(weights),
                "classesFile": str(CLASSES_FILE) if model_task == "internal_components" else "model.names",
                "classes": list(class_labels.values()),
                "confThreshold": payload.get("confThreshold", DEFAULT_CONF),
                "imgsz": payload.get("imgsz", DEFAULT_IMGSZ),
                "device": device,
                "attemptedDevices": attempted_devices,
                "imageWidth": payload.get("imageWidth", 0),
                "imageHeight": payload.get("imageHeight", 0),
                "detections": suppress_overlapping_detections(detections),
                "rawDetectionCount": len(detections),
                "reason": "",
            }
        last_failure = failures[-1] if failures else {}
        return {
            **_empty_result(True, "YOLO inference failed on all available devices", model_task),
            "attemptedDevices": attempted_devices,
            "failures": failures,
            "stderr": str(last_failure.get("stderr") or "")[-2000:],
            "returncode": last_failure.get("returncode"),
        }
    except subprocess.TimeoutExpired:
        return _empty_result(True, "YOLO subprocess timeout", model_task)
    except Exception as exc:
        return _empty_result(True, f"YOLO error: {exc}", model_task)
    finally:
        if temp_image:
            try:
                temp_image.unlink(missing_ok=True)
            except Exception:
                pass


def format_yolo_for_prompt(result: dict[str, Any] | None) -> str:
    result = result or _empty_result(False, "no yolo result")
    model_type = result.get("modelType") or "component_presence"
    if model_type == "appearance_presence":
        header = "YOLO辅助检测模型：箱体外观目标检测模型（检测中文标识、把手、操作说明、消火栓、箱门、英文标识、装饰性箱门、铭牌）。"
        guidance = (
            "使用规则：外观YOLO只提供消火栓箱/箱门/标识/操作说明是否疑似可见的定位线索，不直接等于合规或不合规；"
            "如果未检出消火栓、箱门、中文标识或操作说明，只能作为回到原图专项核验的风险线索，不能直接证明对应目标缺失；"
            "最终仍以原图清晰可见证据为准。"
        )
    else:
        header = "YOLO辅助检测模型：内部组件存在检测模型（检测手轮、接口、控制器、栓体、水带、水枪、软管、阀门）。"
        guidance = (
            "使用规则：YOLO只说明对应内部组件疑似可见，不直接等于合规或不合规；"
            "若YOLO检出水带/水枪/手轮/接口等组件，应作为排除“缺失”类误报的证据线索；"
            "YOLO未检出不能直接判定组件缺失；最终以原图清晰可见证据为准。"
        )
    if not result.get("enabled"):
        return f"{header}\n{guidance}\n状态：未启用或不可用（{result.get('reason', '')}）"
    if result.get("reason"):
        return f"{header}\n{guidance}\n状态：运行异常（{result.get('reason')}），本次不能把零检测解释为组件不存在。"
    detections = result.get("detections") or []
    if not detections:
        if model_type == "appearance_presence":
            return f"{header}\n{guidance}\n检测结果：未检出高于阈值的箱体外观目标框。"
        return f"{header}\n{guidance}\n检测结果：未检出高于阈值的内部组件框。"
    compact = compact_detections_for_prompt(detections)
    detected_labels = {str(item.get("label") or "") for item in compact}
    lines = [
        header,
        guidance,
        "检测结果已做同类去重和嵌套框压缩；以下是给复核模型使用的目标级摘要，不提供带文字标注图，避免文字覆盖影响判断。",
        "目标摘要：",
    ]
    if model_type == "appearance_presence" and ({"消火栓", "箱门", "装饰性箱门"} & detected_labels) and "中文标识" not in detected_labels:
        lines.append("外观风险提示：YOLO已检出消火栓/箱门类目标，但未检出中文标识；请回到原图重点核验箱门上是否清晰标注中文“消火栓”。若原图也未见清晰中文“消火栓”字样，应输出隐患标签“室内消火栓箱门未清晰标注中文“消火栓”字样”，不能直接判合格。")
    if model_type == "appearance_presence" and ({"消火栓", "箱门", "装饰性箱门"} & detected_labels) and "操作说明" not in detected_labels:
        lines.append("外观风险提示：YOLO已检出消火栓/箱门类目标，但未检出操作说明；这不是缺失证据，必须由操作说明专项复核回到原图确认箱体正面或箱门主要区域是否存在操作步骤/使用方法说明。")
    for index, item in enumerate(compact[:10], 1):
        lines.append(
            f"{index}. 目标={item['label']}；候选框数={item['count']}；最高置信度={item['confidence']:.2f}；主框bbox_norm_xyxy={item['bboxNorm']}"
        )
    return "\n".join(lines)
