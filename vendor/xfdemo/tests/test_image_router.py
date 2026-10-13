from backend.modules.inspection import router


def _result(*detections):
    return {
        "enabled": True,
        "detections": [
            {"label": label, "confidence": confidence}
            for label, confidence in detections
        ],
    }


def _install_results(monkeypatch, results):
    calls = []

    def fake_detection(_image, task):
        calls.append(task)
        return results.get(task, _result())

    monkeypatch.setattr(router, "run_yolo_detection", fake_detection)
    return calls


def test_runs_all_detectors_and_selects_strongest_device(monkeypatch):
    calls = _install_results(monkeypatch, {
        "internal_components": _result(("水带", 0.36), ("接口", 0.34)),
        "appearance": _result(),
        "outdoor_hydrant": _result(("室外消火栓", 0.91)),
        "fire_extinguisher": _result(),
    })

    intent, _result_payload, meta = router.resolve_yolo_route("data:image/jpeg;base64,test")

    assert calls == [item[0] for item in router.ROUTE_ORDER]
    assert intent.inspection_type == "outdoor_hydrant"
    assert meta["selectedTask"] == "outdoor_hydrant"


def test_low_confidence_extinguisher_cannot_trigger_branch(monkeypatch):
    _install_results(monkeypatch, {
        "fire_extinguisher": _result(
            ("灭火器", router.EXTINGUISHER_ROUTE_CONF - 0.01),
            ("灭火器压力指示器", 0.20),
        ),
    })

    intent, _result_payload, meta = router.resolve_yolo_route("data:image/jpeg;base64,test")

    assert intent.inspection_type == "unknown"
    assert meta["source"] == "yolo_no_match"


def test_pressure_indicator_alone_never_routes_to_extinguisher(monkeypatch):
    _install_results(monkeypatch, {
        "fire_extinguisher": _result(("灭火器压力指示器", 0.99)),
    })

    intent, _result_payload, _meta = router.resolve_yolo_route("data:image/jpeg;base64,test")

    assert intent.inspection_type == "unknown"


def test_no_detection_does_not_default_to_indoor(monkeypatch):
    _install_results(monkeypatch, {})

    intent, _result_payload, meta = router.resolve_yolo_route(
        "data:image/jpeg;base64,test",
        query="请检查室内消火栓内部组件",
        explicit_task="internal_components",
    )

    assert intent.inspection_type == "unknown"
    assert meta["selectedTask"] == ""


def test_close_scores_are_left_for_image_review(monkeypatch):
    _install_results(monkeypatch, {
        "outdoor_hydrant": _result(("室外消火栓", 0.66)),
        "fire_extinguisher": _result(("灭火器", 0.62)),
    })

    intent, _result_payload, meta = router.resolve_yolo_route("data:image/jpeg;base64,test")

    assert intent.inspection_type == "unknown"
    assert meta["source"] == "yolo_ambiguous"
