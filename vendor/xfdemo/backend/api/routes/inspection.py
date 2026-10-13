import queue
import threading

from flask import Blueprint, Response, jsonify, request, stream_with_context

from backend.modules.inspection.pipeline import get_agent
from backend.modules.inspection.utils import ndjson, strip_reasoning, trim_output
from backend.modules.history.inspection_history import append_history

inspection_bp = Blueprint("inspection", __name__)


@inspection_bp.post("/chat")
def chat():
    try:
        data = request.get_json(silent=True) or {}
        state = get_agent().invoke(data)
        report = state.get("report", "")
        usage = state.get("usage", {})
        yolo = state.get("yolo", {})
        trace = state.get("trace", {})
        history = append_history(data, report, usage, task=state.get("task", "auto"), yolo=yolo, trace=trace)
        return jsonify({"response": report, "usage": usage, "history": history, "yolo": yolo, "trace": trace})
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    except Exception as exc:
        print(f"Chat error: {exc}")
        return jsonify({"error": str(exc)}), 500


@inspection_bp.post("/chat/stream")
def chat_stream():
    try:
        data = request.get_json(silent=True) or {}
        agent = get_agent()
    except Exception as exc:
        print(f"Stream setup error: {exc}")
        return jsonify({"error": str(exc)}), 500

    @stream_with_context
    def generate():
        events: queue.Queue = queue.Queue()
        completed = object()

        def on_progress(payload):
            events.put({"type": "progress", **payload})

        def run_inspection():
            try:
                events.put({"type": "state", "status": "started"})
                state = agent.stream_checked(data, progress_callback=on_progress)
                events.put({"type": "result", "state": state})
            except Exception as exc:
                events.put({"type": "worker_error", "error": str(exc)})
            finally:
                events.put(completed)

        worker = threading.Thread(target=run_inspection, daemon=True)
        worker.start()
        try:
            state = None
            while True:
                event = events.get()
                if event is completed:
                    break
                if event.get("type") == "result":
                    state = event["state"]
                    continue
                if event.get("type") == "worker_error":
                    raise RuntimeError(event.get("error") or "检测任务执行失败")
                yield ndjson(event)

            if state is None:
                raise RuntimeError("检测任务未返回结果")
            final_text = trim_output(strip_reasoning(state.get("report", "")), max_chars=max(agent.settings.max_output_chars, 4000))
            if final_text:
                yield ndjson({"type": "delta", "delta": final_text})
            yolo = state.get("yolo", {})
            trace = state.get("trace", {})
            history = append_history(data, final_text, state.get("usage", {}), finish_reason="judge_checked", task=state.get("task", "auto"), yolo=yolo, trace=trace)
            yield ndjson({"type": "done", "response": final_text, "usage": state.get("usage", {}), "finish_reason": "judge_checked", "task": state.get("task", "auto"), "history": history, "yolo": yolo, "trace": trace})
        except ValueError as exc:
            yield ndjson({"type": "error", "error": str(exc)})
        except Exception as exc:
            print(f"Stream error: {exc}")
            yield ndjson({"type": "error", "error": str(exc)})

    response = Response(generate(), mimetype="application/x-ndjson")
    response.headers["Cache-Control"] = "no-cache"
    response.headers["X-Accel-Buffering"] = "no"
    return response
