"""
PMI API Routes - Endpoints para Product Manufacturing Information
"""

from flask import Blueprint, jsonify, request
import logging

from app.step_view_pro.models import STEPFileHeader
from app.extensions import db
from app.step_view_pro.backend.pmi_parser import extract_pmi_for_file

logger = logging.getLogger(__name__)
bp = Blueprint('pmi_api', __name__)


@bp.route('/<string:header_id>/extract', methods=['POST'])
def extract_pmi(header_id):
    """Extrae PMI de un archivo STEP"""
    logger.info(f"POST /pmi/{header_id}/extract")

    try:
        header = _resolve_header(header_id)
        resolved_id = str(header.id) if header else header_id
        result = extract_pmi_for_file(resolved_id)
        return jsonify(result), 200

    except Exception as e:
        logger.exception(f"Error extracting PMI: {e}")
        return jsonify({'error': str(e)}), 500


def _resolve_header(header_id):
    """Resolve header by UUID or by part_id fallback."""
    try:
        header = STEPFileHeader.query.get(header_id)
        if not header:
            header = STEPFileHeader.query.filter_by(part_id=header_id).first()
        return header
    except Exception:
        return None


@bp.route('/<string:header_id>/list', methods=['GET'])
def list_pmi(header_id):
    """Lista todas las anotaciones PMI"""
    pmi_type = request.args.get('type')

    header = _resolve_header(header_id)
    if not header or not header.pmi_annotations:
        return jsonify({'annotations': []}), 200

    annotations = header.pmi_annotations.get('annotations', [])

    if pmi_type:
        annotations = [a for a in annotations if a.get('pmi_type') == pmi_type]

    return jsonify({
        'total': len(annotations),
        'annotations': annotations,
        'annotations_by_type': header.pmi_annotations.get('annotations_by_type', {})
    }), 200


@bp.route('/<string:header_id>/stats', methods=['GET'])
def get_pmi_stats(header_id):
    """Obtiene estadísticas de PMI"""
    header = _resolve_header(header_id)

    if not header or not header.pmi_annotations:
        return jsonify({'total_annotations': 0}), 200

    return jsonify({
        'total_annotations': header.pmi_annotations.get('total_annotations', 0),
        'annotations_by_type': header.pmi_annotations.get('annotations_by_type', {})
    }), 200


logger.info("[OK] PMI API routes loaded")
