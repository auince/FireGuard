from flask import Blueprint, jsonify, request

from backend.modules.dataset.service import as_int
from backend.modules.history.inspection_history import inspection_monitor_stats

monitor_bp = Blueprint("monitor", __name__)


@monitor_bp.get("/monitor/inspection-stats")
def inspection_stats():
    limit = as_int(request.args.get("limit"), 200, 1, 2000)
    return jsonify(inspection_monitor_stats(limit))
