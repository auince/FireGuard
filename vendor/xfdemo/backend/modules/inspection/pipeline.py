import time
from typing import Any, Callable

from backend.infrastructure.ai.model_client import create_model_client
from backend.infrastructure.vision.yolo_detector import run_yolo_detection
from backend.modules.inspection.messages import (
    apply_bend_review,
    apply_missing_equipment_visibility_review,
    apply_operation_instruction_review,
    apply_outlet_direction_review,
    build_bend_verify_messages,
    build_judge_messages,
    build_messages,
    build_missing_equipment_verify_messages,
    build_operation_instruction_verify_messages,
    build_outlet_direction_verify_messages,
    parse_bend_verify,
    parse_missing_equipment_verify,
    parse_operation_instruction_verify,
    parse_outlet_direction_verify,
)
from backend.modules.inspection.parser import (
    detect_task,
    has_bend_candidate,
    has_structured_report,
    labels_from_report,
    pick_primary_structured_report,
    report_fields_for_trace,
    sanitize_final_report,
)
from backend.modules.inspection.output_formatter import format_public_report
from backend.modules.inspection.postprocess import enforce_report_scope, guarded_format_judge_json
from backend.config.settings import get_settings
from backend.modules.inspection.trace import build_trace_summary, trace_stage
from backend.modules.inspection.registry import get_branch
from backend.modules.inspection.intent import resolve_intent
from backend.modules.inspection.router import resolve_yolo_route, route_trace_payload
from backend.modules.inspection.types import InspectionState, Settings
from backend.modules.inspection.utils import normalize_image, strip_reasoning, trim_output
from backend.modules.inspection.yolo_context import apply_yolo_backstop, missing_equipment_fallback_labels, yolo_labels_for_trace, MISSING_EQUIPMENT_LABELS


ProgressCallback = Callable[[dict[str, Any]], None]

UNKNOWN_REPORT = """一、检测结论：无法判断
当前图片未能可靠确认检测对象属于室内消火栓、室外消火栓或灭火器，请补充主体完整、清晰且无遮挡的现场图片后重新检测。

二、涉及法律法规
该功能建设中

三、整改建议
请重新拍摄消防设施主体及其关键部位，确保设备轮廓、标识和组件清晰可见。"""


def expected_scope_for_branch(branch_key: str, task: str) -> str:
    if branch_key == "outdoor_hydrant":
        return "室外消火栓"
    if branch_key == "fire_extinguisher":
        return "灭火器"
    return "箱体外观" if task == "appearance" else "内部组件"


def emit_progress(callback: ProgressCallback | None, **payload: Any) -> None:
    if callback:
        callback(payload)


def prepare_input(state: InspectionState) -> InspectionState:
    query = (state.get("query") or "").strip()
    image = normalize_image(state.get("image"))
    if not image:
        raise ValueError("Image is required")
    if not query:
        query = "请检测图片中的消防设施"
    # The product has no user-entered question or manual branch selection.
    task = "auto"
    return {"query": query, "image": image, "task": task, "messages": build_messages(query=query, image=image, task=task)}


def _probe_for_intent(
    route_meta: dict[str, Any],
    inspection_type: str,
    scope_hint: str,
) -> tuple[dict[str, Any], str]:
    preferred_task = {
        "outdoor_hydrant": "outdoor_hydrant",
        "fire_extinguisher": "fire_extinguisher",
    }.get(inspection_type)
    if inspection_type == "indoor_hydrant":
        preferred_task = (
            scope_hint
            if scope_hint in {"appearance", "internal_components"}
            else "internal_components"
        )

    probes = list(route_meta.get("probes") or [])
    probe = next(
        (item for item in probes if item.get("task") == preferred_task),
        None,
    )
    if not probe and inspection_type == "indoor_hydrant":
        indoor = [
            item
            for item in probes
            if item.get("inspectionType") == "indoor_hydrant"
        ]
        probe = max(indoor, key=lambda item: float(item.get("score") or 0), default=None)
    return (probe or {}).get("result") or {}, str((probe or {}).get("task") or preferred_task or "")


class InspectionAgent:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.model = create_model_client(settings, provider=settings.first_provider)
        self.judge_model = create_model_client(
            settings,
            provider=settings.judge_provider,
            api_key=settings.judge_api_key,
            base_url=settings.judge_base_url,
            model=settings.judge_model,
        )
        self.direction_model = create_model_client(
            settings,
            provider=settings.direction_review_provider,
            api_key=settings.direction_review_api_key,
            base_url=settings.direction_review_base_url,
            model=settings.direction_review_model,
        )

    def prepare(self, data: dict[str, Any]) -> InspectionState:
        return prepare_input({
            "query": (data or {}).get("query", ""),
            "image": (data or {}).get("image"),
            "task": (data or {}).get("task", ""),
        })

    def invoke(
        self,
        data: dict[str, Any],
        progress_callback: ProgressCallback | None = None,
    ) -> InspectionState:
        pipeline_started = time.perf_counter()
        emit_progress(
            progress_callback,
            stage="prepare",
            status="running",
            label="正在准备检测任务",
            detail="校验图片并建立本次可追溯任务",
        )
        prepared = self.prepare(data)
        stages: list[dict[str, Any]] = []
        image = prepared.get("image")
        emit_progress(
            progress_callback,
            stage="prepare",
            status="complete",
            label="检测任务已准备",
            elapsedMs=int((time.perf_counter() - pipeline_started) * 1000),
        )

        intent, yolo_result, route_meta = resolve_yolo_route(
            image,
            progress_callback=progress_callback,
        )
        route_review_usage: dict[str, int] = {}
        if intent.inspection_type == "unknown":
            emit_progress(
                progress_callback,
                stage="route_review",
                status="running",
                label="正在确认消防设施类型",
                detail="目标检测证据不足或存在冲突，正在根据原图确认主体设备",
            )
            stage_started = time.perf_counter()
            reviewed_intent, review_meta = resolve_intent(self.judge_model, "", image)
            route_review_usage = dict(review_meta.get("usage") or {})
            stages.append(trace_stage(
                "image_type_review",
                "图像主体类型复核",
                stage_started,
                status="ok" if reviewed_intent.inspection_type != "unknown" else "warn",
                inspectionType=reviewed_intent.inspection_type,
                confidence=reviewed_intent.confidence,
                evidence=reviewed_intent.evidence,
                rawOutput=review_meta.get("rawOutput", ""),
                error=review_meta.get("error", ""),
                usage=route_review_usage,
            ))
            if reviewed_intent.inspection_type != "unknown":
                intent = reviewed_intent
                yolo_result, reviewed_task = _probe_for_intent(
                    route_meta,
                    intent.inspection_type,
                    intent.scope_hint,
                )
                route_meta.update({
                    "source": "yolo_vlm_confirmed",
                    "selectedTask": reviewed_task,
                    "selectedReason": intent.evidence,
                })
                emit_progress(
                    progress_callback,
                    stage="route_review",
                    status="complete",
                    label=f"已确认{intent.display_name}",
                    detail=intent.evidence,
                    elapsedMs=review_meta.get("latencyMs", 0),
                )
            else:
                prepared["inspection_type"] = "unknown"
                prepared["inspection_name"] = "无法判断"
                prepared["intent"] = route_trace_payload(intent, route_meta)
                trace = {
                    "version": "image-only-router-v3",
                    "inspectionType": "unknown",
                    "inspectionName": "无法判断",
                    "stages": stages,
                    "summary": {
                        "result": "图像证据不足，未进入任何专业检测分支",
                        "usage": route_review_usage,
                    },
                }
                emit_progress(
                    progress_callback,
                    stage="route_review",
                    status="complete",
                    label="当前图片无法确认检测对象",
                    detail="未进入室内消火栓、室外消火栓或灭火器报告分支",
                    elapsedMs=review_meta.get("latencyMs", 0),
                )
                return {
                    **prepared,
                    "task": "unknown",
                    "raw_report": UNKNOWN_REPORT,
                    "structured_report": UNKNOWN_REPORT,
                    "report": UNKNOWN_REPORT,
                    "usage": route_review_usage,
                    "yolo": yolo_result,
                    "trace": trace,
                }

        branch = get_branch(intent.inspection_type)
        requested_task = str(prepared.get("task") or "auto")
        prepared["inspection_type"] = intent.inspection_type
        prepared["inspection_name"] = branch.name
        prepared["intent"] = route_trace_payload(intent, route_meta)
        route_task = str(route_meta.get("selectedTask") or branch.default_task)
        judge_task = route_task
        expected_scope = expected_scope_for_branch(branch.key, route_task)
        prepared["task"] = requested_task if branch.key == "indoor_hydrant" else route_task
        prepared["messages"] = build_messages(
            query=prepared["query"],
            image=image,
            task=route_task,
            branch_key=branch.key,
            yolo_result=yolo_result,
        )
        stages.append({
            "id": "intent_router",
            "name": "yolo_router",
            "title": "目标识别与任务分流",
            "status": "ok" if route_meta.get("source") != "rule_fallback" else "warn",
            "durationMs": route_meta.get("latencyMs", 0),
            "inspectionType": intent.inspection_type,
            "inspectionName": branch.name,
            "scopeHint": intent.scope_hint,
            "confidence": intent.confidence,
            "source": intent.source,
            "output": intent.evidence,
            "usage": {},
            "selectedTask": route_task,
            "selectedReason": route_meta.get("selectedReason", ""),
            "probes": prepared["intent"].get("probes", []),
            "branch": {
                "defaultTask": branch.default_task,
                "yoloTask": judge_task,
                "promptProfile": branch.prompt_profile,
                "reviewers": list(branch.reviewers),
            },
        })
        for probe in route_meta.get("probes") or []:
            stages.append({
                "name": f"route_probe_{probe.get('task')}",
                "title": {
                    "internal_components": "室内组件定位",
                    "appearance": "室内箱体定位",
                    "outdoor_hydrant": "室外消火栓定位",
                    "fire_extinguisher": "灭火器定位",
                }.get(probe.get("task"), "目标定位"),
                "status": "ok" if probe.get("matched") else "skipped",
                "durationMs": probe.get("durationMs", 0),
                "detectionCount": probe.get("detectionCount", 0),
                "labels": probe.get("labels", []),
                "reason": probe.get("reason", ""),
                "matched": bool(probe.get("matched")),
                "adopted": probe.get("task") == route_task,
                "usage": {},
            })
        emit_progress(
            progress_callback,
            stage="route",
            status="complete",
            label=f"已进入{branch.name}检测任务",
            detail=route_meta.get("selectedReason", ""),
            elapsedMs=route_meta.get("latencyMs", 0),
            inspectionType=branch.key,
        )

        emit_progress(
            progress_callback,
            stage="analysis",
            status="running",
            label=f"正在分析{branch.name}现场状态",
            detail="结合原图与目标定位线索生成初步判断",
            inspectionType=branch.key,
        )
        stage_started = time.perf_counter()
        first = self.model.invoke(prepared["messages"])
        raw_report = trim_output(strip_reasoning(first.content), self.settings.max_output_chars)
        # 多段报告中取主要报告
        raw_report = pick_primary_structured_report(raw_report)
        stages.append(trace_stage(
            "qwen_first",
            "QwenVL \u521d\u68c0",
            stage_started,
            output=report_fields_for_trace(raw_report),
            usage=first.usage,
        ))
        first_duration_ms = stages[-1]["durationMs"]
        emit_progress(
            progress_callback,
            stage="analysis",
            status="complete",
            label="初步分析已完成",
            detail="正在进入证据复核",
            elapsedMs=first_duration_ms,
            usage=first.usage,
            throughput=stages[-1].get("throughput", {}),
        )
        final_report = raw_report
        usage = merge_usage(route_review_usage, first.usage)
        reviewed_text = ""

        # YOLO chooses the indoor branch, while the established indoor flow
        # still decides appearance vs. internal components from the first VLM
        # report and reruns the matching detector when needed.
        if image and branch.key == "indoor_hydrant":
            judge_task = detect_task("", requested_task, raw_report)
            if judge_task == "auto":
                judge_task = "internal_components" if "内部" in raw_report else "appearance"
            expected_scope = expected_scope_for_branch(branch.key, judge_task)
            desired_type = "appearance_presence" if judge_task == "appearance" else "component_presence"
            current_type = str(yolo_result.get("modelType") or "")
            if current_type != desired_type:
                stage_started = time.perf_counter()
                aligned_result = run_yolo_detection(image, task=judge_task)
                stages.append(trace_stage(
                    "yolo_appearance_align" if judge_task == "appearance" else "yolo_internal_align",
                    "YOLO 范围对齐复跑（箱体外观）" if judge_task == "appearance" else "YOLO 范围对齐复跑（内部组件）",
                    stage_started,
                    status="skipped" if aligned_result.get("skipped") else (
                        "warn" if aligned_result.get("reason") else (
                            "ok" if aligned_result.get("enabled") else "warn"
                        )
                    ),
                    detectionCount=len(aligned_result.get("detections") or []),
                    labels=yolo_labels_for_trace(aligned_result),
                    reason=aligned_result.get("reason", ""),
                    imageSize={
                        "width": aligned_result.get("imageWidth", 0),
                        "height": aligned_result.get("imageHeight", 0),
                    },
                    modelScope=aligned_result.get("modelScope", ""),
                    adopted=True,
                ))
                yolo_result = aligned_result
            prepared["task"] = judge_task

        effective_task = judge_task
        if image:
            emit_progress(
                progress_callback,
                stage="review",
                status="running",
                label=f"正在复核{branch.name}检测证据",
                detail="核对初步结论与原图证据的一致性",
            )
            stage_started = time.perf_counter()
            judge_messages = build_judge_messages(
                prepared.get("query", ""),
                image,
                raw_report,
                judge_task,
                yolo_result=yolo_result,
                branch_key=branch.key,
            )
            reviewed = self.judge_model.invoke(judge_messages)
            reviewed_text = trim_output(strip_reasoning(reviewed.content), self.settings.max_output_chars)
            formatted_review = guarded_format_judge_json(
                reviewed_text,
                raw_report,
                expected_scope=expected_scope,
            )
            if formatted_review:
                final_report = formatted_review
                # 判断模型是否输出了结构化报告
            elif has_structured_report(reviewed_text):
                # 清洗并纠正报告
                final_report = sanitize_final_report(reviewed_text)
            else:
                final_report = raw_report
            usage = merge_usage(usage, reviewed.usage)
            # 提取日志字段
            final_fields = report_fields_for_trace(final_report)
            # 找出可能需要兜底的缺失标签
            fallback_labels = missing_equipment_fallback_labels(final_fields.get("labels") or [], yolo_labels_for_trace(yolo_result))
            stages.append(trace_stage(
                "judge_review",
                "\u4e8c\u6b21\u590d\u6838\u7efc\u5408\u5224\u65ad",
                stage_started,
                output=final_fields,
                rawOutput=trim_output(reviewed_text, 900),
                fallback="missing_equipment" if fallback_labels else "",
                fallbackLabels=fallback_labels,
                usage=reviewed.usage,
            ))
            emit_progress(
                progress_callback,
                stage="review",
                status="complete",
                label="综合证据复核已完成",
                elapsedMs=stages[-1]["durationMs"],
                usage=reviewed.usage,
                throughput=stages[-1].get("throughput", {}),
            )

        final_report = sanitize_final_report(final_report)
        scope_changed = False

        missing_review_candidates: list[str] = []
        specialist_context_report = raw_report if not scope_changed else final_report
        if image and branch.key == "indoor_hydrant":
            emit_progress(
                progress_callback,
                stage="specialist",
                status="running",
                label="正在核验关键隐患",
                detail="仅对已触发的室内专项进行针对性校验",
            )
        if image and branch.key == "indoor_hydrant" and effective_task == "appearance":
            stage_started = time.perf_counter()
            operation_messages = build_operation_instruction_verify_messages(
                image,
                prepared.get("query", ""),
                specialist_context_report,
                final_report,
                yolo_result=yolo_result,
            )
            operation_result = self.direction_model.invoke(operation_messages)
            operation_text = trim_output(
                strip_reasoning(operation_result.content),
                self.settings.max_output_chars,
            )
            operation_data = parse_operation_instruction_verify(operation_text)
            updated_report = apply_operation_instruction_review(final_report, operation_data)
            usage = merge_usage(usage, operation_result.usage)
            yolo_operation_visible = "操作说明" in set(yolo_labels_for_trace(yolo_result))
            stages.append(trace_stage(
                "operation_instruction_review",
                "操作说明专项复核",
                stage_started,
                status="ok" if operation_data else "warn",
                output=report_fields_for_trace(updated_report),
                rawOutput=trim_output(operation_text, 600),
                yoloOperationInstructionVisible=yolo_operation_visible,
                changed=updated_report != final_report,
                supported=bool(
                    (operation_data or {}).get("instruction_missing_supported")
                    or (operation_data or {}).get("instruction_unclear_supported")
                ),
                needsManualReview=bool((operation_data or {}).get("needs_manual_review")),
                usage=operation_result.usage,
            ))
            final_report = updated_report

        if image and branch.key == "indoor_hydrant" and effective_task == "internal_components":
            # 读取隐患标签
            candidate_reports = [final_report]
            if not scope_changed:
                candidate_reports.insert(0, raw_report)
            for label in [item for report in candidate_reports for item in labels_from_report(report)]:
                # 定义哪些标签属于组件缺失
                if label in MISSING_EQUIPMENT_LABELS and label not in missing_review_candidates:
                    missing_review_candidates.append(label)
        if image and branch.key == "indoor_hydrant" and effective_task == "internal_components" and missing_review_candidates:
            stage_started = time.perf_counter()
            verify_messages = build_missing_equipment_verify_messages(
                image,
                prepared.get("query", ""),
                specialist_context_report,
                final_report,
                missing_review_candidates,
            )
            verify_result = self.judge_model.invoke(verify_messages)
            verify_text = trim_output(strip_reasoning(verify_result.content), self.settings.max_output_chars)
            verify_data = parse_missing_equipment_verify(verify_text)
            updated_report = apply_missing_equipment_visibility_review(final_report, verify_data, missing_review_candidates)
            usage = merge_usage(usage, verify_result.usage)
            stages.append(trace_stage(
                "missing_visibility_review",
                "\u6c34\u67aa/\u6c34\u5e26\u7f3a\u5931\u4e13\u9879\u590d\u6838",
                stage_started,
                status="ok" if verify_data else "warn",
                output=report_fields_for_trace(updated_report),
                rawOutput=trim_output(verify_text, 600),
                candidateLabels=missing_review_candidates,
                changed=updated_report != final_report,
                usage=verify_result.usage,
            ))
            final_report = updated_report

        bend_label = "消防软管卷盘供水管道折弯严重"
        bend_candidate = has_bend_candidate(raw_report, reviewed_text, final_report)
        if image and branch.key == "indoor_hydrant" and effective_task == "internal_components" and (
            bend_candidate or bend_label in labels_from_report(final_report)
        ):
            stage_started = time.perf_counter()
            bend_messages = build_bend_verify_messages(
                image,
                prepared.get("query", ""),
                specialist_context_report,
                final_report,
            )
            bend_result = self.direction_model.invoke(bend_messages)
            bend_text = trim_output(strip_reasoning(bend_result.content), self.settings.max_output_chars)
            bend_data = parse_bend_verify(bend_text)
            updated_report = apply_bend_review(final_report, bend_data)
            usage = merge_usage(usage, bend_result.usage)
            stages.append(trace_stage(
                "bend_review",
                "供水软管严重折弯专项复核",
                stage_started,
                status="ok" if bend_data else "warn",
                output=report_fields_for_trace(updated_report),
                rawOutput=trim_output(bend_text, 600),
                candidateDetected=bend_candidate,
                changed=updated_report != final_report,
                supported=bool((bend_data or {}).get("severe_bend_supported")),
                usage=bend_result.usage,
            ))
            final_report = updated_report

        # 使用 YOLO 结果对报告进行最后兜底
        direction_label = "室内消火栓栓口方向错误"
        yolo_components = set(yolo_labels_for_trace(yolo_result))
        direction_candidate = direction_label in labels_from_report(final_report)
        direction_components_visible = "接口" in yolo_components and bool({"栓体", "阀门"} & yolo_components)
        if image and branch.key == "indoor_hydrant" and effective_task == "internal_components" and (
            direction_candidate or direction_components_visible
        ):
            stage_started = time.perf_counter()
            direction_messages = build_outlet_direction_verify_messages(
                image,
                prepared.get("query", ""),
                specialist_context_report,
                final_report,
                yolo_result=yolo_result,
            )
            direction_result = self.direction_model.invoke(direction_messages)
            direction_text = trim_output(strip_reasoning(direction_result.content), self.settings.max_output_chars)
            direction_data = parse_outlet_direction_verify(direction_text)
            updated_report = apply_outlet_direction_review(final_report, direction_data)
            usage = merge_usage(usage, direction_result.usage)
            stages.append(trace_stage(
                "outlet_direction_review",
                "栓口方向专项复核",
                stage_started,
                status="ok" if direction_data else "warn",
                output=report_fields_for_trace(updated_report),
                rawOutput=trim_output(direction_text, 600),
                candidateDetected=direction_candidate,
                componentTriggered=direction_components_visible,
                changed=updated_report != final_report,
                supported=bool((direction_data or {}).get("wrong_direction_supported")),
                needsManualReview=bool((direction_data or {}).get("needs_manual_review")),
                usage=direction_result.usage,
            ))
            final_report = updated_report

        if image and branch.key == "indoor_hydrant":
            emit_progress(
                progress_callback,
                stage="specialist",
                status="complete",
                label="关键隐患核验已完成",
                detail="专项结果只修正其负责的标签与证据",
            )

        emit_progress(
            progress_callback,
            stage="report",
            status="running",
            label="正在生成检测报告",
            detail="整理最终标签、对应证据与巡检建议",
        )
        final_report = apply_yolo_backstop(final_report, raw_report, yolo_result)
        final_report = enforce_report_scope(final_report, expected_scope)
        trace = {
            "version": "image-only-router-branch-judge-v3",
            "inspectionType": intent.inspection_type,
            "inspectionName": branch.name,
            "stages": stages,
            "summary": build_trace_summary(raw_report, final_report, yolo_result, stages),
        }
        public_report = format_public_report(final_report, yolo_result=yolo_result)
        emit_progress(
            progress_callback,
            stage="report",
            status="complete",
            label="检测报告已生成",
            detail=f"本次任务总耗时 {int((time.perf_counter() - pipeline_started) * 1000)}ms",
            elapsedMs=int((time.perf_counter() - pipeline_started) * 1000),
            usage=usage,
            throughput=trace["summary"].get("usage", {}),
        )
        return {
            **prepared,
            "raw_report": raw_report,
            "structured_report": final_report,
            "report": public_report,
            "usage": usage,
            "yolo": yolo_result,
            "trace": trace,
        }

    def stream_checked(
        self,
        data: dict[str, Any],
        progress_callback: ProgressCallback | None = None,
    ) -> InspectionState:
        return self.invoke(data, progress_callback=progress_callback)

    def stream(self, messages: list[dict[str, Any]]):
        return self.model.stream(messages)


def merge_usage(left: dict[str, int], right: dict[str, int]) -> dict[str, int]:
    merged = dict(left or {})
    for key, value in (right or {}).items():
        if isinstance(value, int):
            merged[key] = merged.get(key, 0) + value
    return merged


_agent_cache: tuple[Settings, InspectionAgent] | None = None


def get_agent() -> InspectionAgent:
    global _agent_cache
    settings = get_settings()
    if _agent_cache and _agent_cache[0] == settings:
        return _agent_cache[1]
    agent = InspectionAgent(settings)
    _agent_cache = (settings, agent)
    return agent


class _SimpleCompiledGraph:
    def __init__(self, func: Any) -> None:
        self.func = func

    def invoke(self, state: InspectionState) -> InspectionState:
        return self.func(state)


def create_prepare_graph():
    return _SimpleCompiledGraph(prepare_input)


def create_inspection_graph(model: Any):
    def invoke_plain(state: InspectionState) -> InspectionState:
        prepared = prepare_input(state)
        response = model.invoke(prepared["messages"])
        return {**prepared, "report": trim_output(strip_reasoning(response.content), 1200), "usage": response.usage}

    return _SimpleCompiledGraph(invoke_plain)
