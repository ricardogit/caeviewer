"""AI analysis endpoints for the CAE module."""
from flask import Blueprint, jsonify, request

bp = Blueprint("cae_ai", __name__)


@bp.route("/ai/analyze", methods=["POST"])
def analyze():
    """
    POST /api/cae/ai/analyze
    Body: { "values": [...], "field_type": "nodal"|"elemental", "threshold_ratio": 0.9 }
    Returns hotspot indices, statistics, and risk classification.
    """
    data = request.get_json(force=True, silent=True)
    if not data or "values" not in data:
        return jsonify({"error": 'Missing "values" in request body'}), 400

    values = data["values"]
    if not values:
        return jsonify({"error": "Empty values array"}), 400

    threshold_ratio = float(data.get("threshold_ratio", 0.9))
    field_type = data.get("field_type", "nodal")

    try:
        from app.cae.services.ai_service import analyze_field
        result = analyze_field(values, field_type, threshold_ratio)
        return jsonify(result), 200
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500
