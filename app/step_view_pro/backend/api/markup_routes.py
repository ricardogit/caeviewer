"""
Markup API Routes - Endpoints para persistencia de anotaciones 2D (markup canvas)
"""

from flask import Blueprint, jsonify, request
import logging

from app.step_view_pro.models import STEPFileHeader
from app.extensions import db

logger = logging.getLogger(__name__)
bp = Blueprint('markup_api', __name__)


def _resolve_header(header_id):
    """Resolve STEPFileHeader by UUID or part_id fallback."""
    try:
        h = STEPFileHeader.query.get(header_id)
        if not h:
            h = STEPFileHeader.query.filter_by(part_id=header_id).first()
        return h
    except Exception:
        return None


@bp.route('/<string:header_id>/list', methods=['GET'])
def list_markups(header_id):
    """Returns saved markup strokes for a file."""
    header = _resolve_header(header_id)
    if not header or not header.markups:
        return jsonify({'strokes': [], 'total': 0}), 200

    strokes = header.markups.get('strokes', [])
    return jsonify({'strokes': strokes, 'total': len(strokes)}), 200


@bp.route('/<string:header_id>/save', methods=['POST'])
def save_markups(header_id):
    """Saves markup strokes for a file (overwrites existing)."""
    data = request.get_json() or {}
    strokes = data.get('strokes', [])

    header = _resolve_header(header_id)
    if not header:
        return jsonify({'error': 'File not found'}), 404

    try:
        header.markups = {'strokes': strokes}
        db.session.commit()
        return jsonify({'success': True, 'total': len(strokes)}), 200
    except Exception as e:
        db.session.rollback()
        logger.exception(f"Error saving markups: {e}")
        return jsonify({'error': str(e)}), 500


@bp.route('/<string:header_id>/clear', methods=['DELETE'])
def clear_markups(header_id):
    """Clears all markup strokes for a file."""
    header = _resolve_header(header_id)
    if not header:
        return jsonify({'error': 'File not found'}), 404

    try:
        header.markups = {'strokes': []}
        db.session.commit()
        return jsonify({'success': True}), 200
    except Exception as e:
        db.session.rollback()
        logger.exception(f"Error clearing markups: {e}")
        return jsonify({'error': str(e)}), 500


logger.info("[OK] Markup API routes loaded")
