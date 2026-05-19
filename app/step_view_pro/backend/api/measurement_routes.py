"""
Measurement API Routes - Endpoints para herramientas de medición 3D
"""

from flask import Blueprint, jsonify, request
import logging
from typing import Dict, List

from app.step_view_pro.models import STEPFileHeader
from app.extensions import db
from app.step_view_pro.backend.measurement_tools import (
    MeasurementTools,
    measure_distance,
    measure_angle
)
from app.step_view_pro.backend.step_processor import load_step_shape

logger = logging.getLogger(__name__)
bp = Blueprint('measurement_api', __name__)


def _resolve_header(header_id):
    """Resolve STEPFileHeader by its UUID or by part_id fallback."""
    try:
        header = STEPFileHeader.query.get(header_id)
        if not header:
            header = STEPFileHeader.query.filter_by(part_id=header_id).first()
        return header
    except Exception:
        return None


def _get_file_path(header):
    """Return the STEP file path for a header via its Part relationship."""
    part = header.part if header else None
    return part.file_path if part else None


@bp.route('/distance', methods=['POST'])
def calculate_distance():
    """
    Calcula distancia entre dos puntos

    Body:
        {
            "p1": [x, y, z],
            "p2": [x, y, z]
        }

    Returns:
        {
            "type": "distance",
            "value": 123.45,
            "unit": "mm",
            "points": [[x1,y1,z1], [x2,y2,z2]],
            "measurement": {...}
        }
    """
    try:
        data = request.get_json()
        p1 = data.get('p1')
        p2 = data.get('p2')

        if not p1 or not p2:
            return jsonify({'error': 'p1 and p2 required'}), 400

        if len(p1) != 3 or len(p2) != 3:
            return jsonify({'error': 'Points must have 3 coordinates [x,y,z]'}), 400

        result = measure_distance(p1, p2)
        return jsonify(result), 200

    except Exception as e:
        logger.exception(f"Error calculating distance: {e}")
        return jsonify({'error': str(e)}), 500


@bp.route('/angle', methods=['POST'])
def calculate_angle():
    """
    Calcula ángulo entre dos vectores

    Body:
        {
            "v1": [x, y, z],
            "v2": [x, y, z]
        }

    Returns:
        {
            "type": "angle",
            "value": 45.0,
            "unit": "degrees",
            "vectors": [[x1,y1,z1], [x2,y2,z2]],
            "measurement": {...}
        }
    """
    try:
        data = request.get_json()
        v1 = data.get('v1')
        v2 = data.get('v2')

        if not v1 or not v2:
            return jsonify({'error': 'v1 and v2 required'}), 400

        if len(v1) != 3 or len(v2) != 3:
            return jsonify({'error': 'Vectors must have 3 components [x,y,z]'}), 400

        result = measure_angle(v1, v2)
        return jsonify(result), 200

    except Exception as e:
        logger.exception(f"Error calculating angle: {e}")
        return jsonify({'error': str(e)}), 500


@bp.route('/point-to-plane', methods=['POST'])
def calculate_point_to_plane():
    """
    Calcula distancia de punto a plano

    Body:
        {
            "point": [x, y, z],
            "plane_point": [x, y, z],
            "plane_normal": [nx, ny, nz]
        }
    """
    try:
        data = request.get_json()
        point = data.get('point')
        plane_point = data.get('plane_point')
        plane_normal = data.get('plane_normal')

        if not point or not plane_point or not plane_normal:
            return jsonify({'error': 'point, plane_point, and plane_normal required'}), 400

        distance = MeasurementTools.distance_point_to_plane(
            tuple(point),
            tuple(plane_point),
            tuple(plane_normal)
        )

        measurement = MeasurementTools.create_measurement(
            'DISTANCE',
            distance,
            points=[tuple(point), tuple(plane_point)],
            label=f"Distance to plane: {distance:.2f} mm"
        )

        return jsonify({
            'type': 'distance_point_to_plane',
            'value': distance,
            'unit': 'mm',
            'point': point,
            'plane_point': plane_point,
            'plane_normal': plane_normal,
            'measurement': measurement.to_dict()
        }), 200

    except Exception as e:
        logger.exception(f"Error calculating point-to-plane distance: {e}")
        return jsonify({'error': str(e)}), 500


@bp.route('/area', methods=['POST'])
def calculate_area():
    """
    Calcula área de una superficie

    Body:
        {
            "header_id": "uuid",
            "shape_index": 0  # Índice de la forma en el assembly
        }

    Returns:
        {
            "type": "area",
            "value": 1234.56,
            "unit": "mm²",
            "measurement": {...}
        }
    """
    try:
        data = request.get_json()
        header_id = data.get('header_id')
        shape_index = data.get('shape_index', 0)

        if not header_id:
            return jsonify({'error': 'header_id required'}), 400

        # Cargar shape desde archivo STEP
        header = _resolve_header(header_id)
        if not header:
            return jsonify({'error': 'File not found'}), 404

        file_path = _get_file_path(header)
        if not file_path:
            return jsonify({'error': 'File path not available'}), 404

        shape = load_step_shape(file_path, shape_index)
        if not shape:
            return jsonify({'error': 'Could not load shape'}), 500

        area = MeasurementTools.compute_area_from_shape(shape)

        measurement = MeasurementTools.create_measurement(
            'AREA',
            area,
            unit='mm²',
            label=f"Surface area: {area:.2f} mm²"
        )

        return jsonify({
            'type': 'area',
            'value': area,
            'unit': 'mm²',
            'shape_index': shape_index,
            'measurement': measurement.to_dict()
        }), 200

    except Exception as e:
        logger.exception(f"Error calculating area: {e}")
        return jsonify({'error': str(e)}), 500


@bp.route('/volume', methods=['POST'])
def calculate_volume():
    """
    Calcula volumen de un sólido

    Body:
        {
            "header_id": "uuid",
            "shape_index": 0
        }

    Returns:
        {
            "type": "volume",
            "value": 12345.67,
            "unit": "mm³",
            "measurement": {...}
        }
    """
    try:
        data = request.get_json()
        header_id = data.get('header_id')
        shape_index = data.get('shape_index', 0)

        if not header_id:
            return jsonify({'error': 'header_id required'}), 400

        header = _resolve_header(header_id)
        if not header:
            return jsonify({'error': 'File not found'}), 404

        file_path = _get_file_path(header)
        if not file_path:
            return jsonify({'error': 'File path not available'}), 404

        shape = load_step_shape(file_path, shape_index)
        if not shape:
            return jsonify({'error': 'Could not load shape'}), 500

        volume = MeasurementTools.compute_volume_from_shape(shape)

        measurement = MeasurementTools.create_measurement(
            'VOLUME',
            volume,
            unit='mm³',
            label=f"Volume: {volume:.2f} mm³"
        )

        return jsonify({
            'type': 'volume',
            'value': volume,
            'unit': 'mm³',
            'shape_index': shape_index,
            'measurement': measurement.to_dict()
        }), 200

    except Exception as e:
        logger.exception(f"Error calculating volume: {e}")
        return jsonify({'error': str(e)}), 500


@bp.route('/bbox', methods=['POST'])
def calculate_bounding_box():
    """
    Calcula bounding box de una geometría

    Body:
        {
            "header_id": "uuid",
            "shape_index": 0
        }

    Returns:
        {
            "type": "bbox",
            "min": [xmin, ymin, zmin],
            "max": [xmax, ymax, zmax],
            "dimensions": [dx, dy, dz],
            "center": [cx, cy, cz],
            "diagonal": 123.45
        }
    """
    try:
        data = request.get_json()
        header_id = data.get('header_id')
        shape_index = data.get('shape_index', 0)

        if not header_id:
            return jsonify({'error': 'header_id required'}), 400

        header = _resolve_header(header_id)
        if not header:
            return jsonify({'error': 'File not found'}), 404

        file_path = _get_file_path(header)
        if not file_path:
            return jsonify({'error': 'File path not available'}), 404

        shape = load_step_shape(file_path, shape_index)
        if not shape:
            return jsonify({'error': 'Could not load shape'}), 500

        bbox = MeasurementTools.compute_bounding_box(shape)
        bbox['type'] = 'bbox'
        bbox['shape_index'] = shape_index

        return jsonify(bbox), 200

    except Exception as e:
        logger.exception(f"Error calculating bounding box: {e}")
        return jsonify({'error': str(e)}), 500


@bp.route('/center-of-mass', methods=['POST'])
def calculate_center_of_mass():
    """
    Calcula centro de masa de un sólido

    Body:
        {
            "header_id": "uuid",
            "shape_index": 0
        }

    Returns:
        {
            "type": "center_of_mass",
            "center": [x, y, z],
            "unit": "mm"
        }
    """
    try:
        data = request.get_json()
        header_id = data.get('header_id')
        shape_index = data.get('shape_index', 0)

        if not header_id:
            return jsonify({'error': 'header_id required'}), 400

        header = _resolve_header(header_id)
        if not header:
            return jsonify({'error': 'File not found'}), 404

        file_path = _get_file_path(header)
        if not file_path:
            return jsonify({'error': 'File path not available'}), 404

        shape = load_step_shape(file_path, shape_index)
        if not shape:
            return jsonify({'error': 'Could not load shape'}), 500

        center = MeasurementTools.compute_center_of_mass(shape)

        return jsonify({
            'type': 'center_of_mass',
            'center': list(center),
            'unit': 'mm',
            'shape_index': shape_index
        }), 200

    except Exception as e:
        logger.exception(f"Error calculating center of mass: {e}")
        return jsonify({'error': str(e)}), 500


@bp.route('/moments-of-inertia', methods=['POST'])
def calculate_moments_of_inertia():
    """
    Calcula momentos de inercia

    Body:
        {
            "header_id": "uuid",
            "shape_index": 0
        }

    Returns:
        {
            "type": "moments_of_inertia",
            "Ixx": 123.45,
            "Iyy": 234.56,
            "Izz": 345.67,
            "Ixy": 12.34,
            "Ixz": 23.45,
            "Iyz": 34.56
        }
    """
    try:
        data = request.get_json()
        header_id = data.get('header_id')
        shape_index = data.get('shape_index', 0)

        if not header_id:
            return jsonify({'error': 'header_id required'}), 400

        header = _resolve_header(header_id)
        if not header:
            return jsonify({'error': 'File not found'}), 404

        file_path = _get_file_path(header)
        if not file_path:
            return jsonify({'error': 'File path not available'}), 404

        shape = load_step_shape(file_path, shape_index)
        if not shape:
            return jsonify({'error': 'Could not load shape'}), 500

        moments = MeasurementTools.compute_moments_of_inertia(shape)
        moments['type'] = 'moments_of_inertia'
        moments['shape_index'] = shape_index

        return jsonify(moments), 200

    except Exception as e:
        logger.exception(f"Error calculating moments of inertia: {e}")
        return jsonify({'error': str(e)}), 500


@bp.route('/<string:header_id>/save', methods=['POST'])
def save_measurement(header_id):
    """
    Guarda una medición en la base de datos

    Body:
        {
            "measurement": {
                "measurement_type": "DISTANCE",
                "value": 123.45,
                "unit": "mm",
                "points": [[x1,y1,z1], [x2,y2,z2]],
                "label": "Distance measurement"
            }
        }
    """
    try:
        data = request.get_json()
        measurement_data = data.get('measurement')

        if not measurement_data:
            return jsonify({'error': 'measurement data required'}), 400

        header = _resolve_header(header_id)
        if not header:
            return jsonify({'error': 'File not found'}), 404

        # Inicializar measurements si no existe
        if not header.measurements:
            header.measurements = {'measurements': []}

        # Agregar nueva medición
        measurements_list = header.measurements.get('measurements', [])
        measurements_list.append(measurement_data)

        header.measurements = {'measurements': measurements_list}
        db.session.commit()

        return jsonify({
            'success': True,
            'total_measurements': len(measurements_list)
        }), 200

    except Exception as e:
        logger.exception(f"Error saving measurement: {e}")
        db.session.rollback()
        return jsonify({'error': str(e)}), 500


@bp.route('/<string:header_id>/list', methods=['GET'])
def list_measurements(header_id):
    """
    Lista todas las mediciones guardadas

    Query params:
        type: Filtrar por tipo (DISTANCE, ANGLE, AREA, VOLUME, BBOX)

    Returns:
        {
            "total": 5,
            "measurements": [...]
        }
    """
    try:
        measurement_type = request.args.get('type')

        header = _resolve_header(header_id)
        if not header or not header.measurements:
            return jsonify({'total': 0, 'measurements': []}), 200

        measurements = header.measurements.get('measurements', [])

        if measurement_type:
            measurements = [m for m in measurements if m.get('measurement_type') == measurement_type]

        return jsonify({
            'total': len(measurements),
            'measurements': measurements
        }), 200

    except Exception as e:
        logger.exception(f"Error listing measurements: {e}")
        return jsonify({'error': str(e)}), 500


@bp.route('/<string:header_id>/clear', methods=['DELETE'])
def clear_measurements(header_id):
    """
    Elimina todas las mediciones guardadas
    """
    try:
        header = _resolve_header(header_id)
        if not header:
            return jsonify({'error': 'File not found'}), 404

        header.measurements = {'measurements': []}
        db.session.commit()

        return jsonify({'success': True}), 200

    except Exception as e:
        logger.exception(f"Error clearing measurements: {e}")
        db.session.rollback()
        return jsonify({'error': str(e)}), 500


logger.info("[OK] Measurement API routes loaded")
