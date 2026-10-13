from flask import Blueprint, jsonify, request

from backend.modules.dataset.service import as_int, list_ultra_strict_samples, send_dataset_image

dataset_bp = Blueprint("dataset", __name__)


@dataset_bp.get("/dataset/ultra-strict/samples")
def ultra_strict_samples():
    split = request.args.get("split", "train")
    if split not in {"train", "val", "all", "quarantine"}:
        split = "train"
    page = as_int(request.args.get("page"), 1, 1, 100000)
    page_size = as_int(request.args.get("page_size"), 24, 1, 80)
    verdict_filter = request.args.get("verdict", "")
    scope_filter = request.args.get("scope", "")
    defect_filter = request.args.get("defect", "")
    query = request.args.get("q", "")
    return jsonify(list_ultra_strict_samples(split, page, page_size, verdict_filter, scope_filter, defect_filter, query))


@dataset_bp.get("/dataset/image")
def dataset_image():
    raw_path = request.args.get("path", "")
    if not raw_path:
        return jsonify({"error": "missing image path"}), 400
    try:
        return send_dataset_image(raw_path)
    except ValueError:
        return jsonify({"error": "image path is outside allowed dataset root"}), 403
    except FileNotFoundError:
        return jsonify({"error": "image not found"}), 404
