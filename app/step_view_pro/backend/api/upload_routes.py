"""
Upload API Routes - Endpoints para carga de archivos STEP
"""

from flask import Blueprint, jsonify, request, current_app
from werkzeug.utils import secure_filename
import os
import logging

from app.extensions import db
from app.models import Part

logger = logging.getLogger(__name__)
bp = Blueprint('upload_api', __name__)

ALLOWED_EXTENSIONS = {'.stp', '.step', '.p21'}

# Files above this threshold are parsed asynchronously via Celery so the
# HTTP request returns immediately instead of blocking for minutes.
_LARGE_FILE_BYTES = 20 * 1024 * 1024  # 20 MB


def _allowed_file(filename):
    return os.path.splitext(filename.lower())[1] in ALLOWED_EXTENSIONS


@bp.route('/', methods=['POST'])
def upload_step_file():
    """Upload a STEP file for visualization."""
    content_length = request.content_length
    max_allowed = current_app.config.get('MAX_CONTENT_LENGTH')
    logger.info(
        f"Upload request: Content-Length={content_length}, "
        f"MAX_CONTENT_LENGTH={max_allowed}"
    )

    if 'file' not in request.files:
        return jsonify({'error': 'No file provided'}), 400

    file = request.files['file']
    if not file.filename:
        return jsonify({'error': 'Empty filename'}), 400

    if not _allowed_file(file.filename):
        return jsonify({'error': 'Invalid file type. Allowed: .stp, .step, .p21'}), 400

    filename = secure_filename(file.filename)
    upload_folder = current_app.config.get('UPLOAD_FOLDER', '/app/data/uploads')
    os.makedirs(upload_folder, exist_ok=True)
    file_path = os.path.join(str(upload_folder), filename)
    file.save(file_path)

    file_size = os.path.getsize(file_path)
    file_size_mb = file_size / (1024 * 1024)
    is_large = file_size > _LARGE_FILE_BYTES

    # Create or update Part record in DB
    part_id = None
    try:
        material = request.form.get('material', 'aluminum_6061')
        part_name = request.form.get('name', filename)
        existing = Part.query.filter_by(file_path=file_path).first()
        if existing:
            part_id = str(existing.id)
        else:
            part = Part(name=part_name, file_path=file_path, material=material)
            db.session.add(part)
            db.session.commit()
            part_id = str(part.id)
    except Exception as e:
        logger.warning(f'Could not create Part record: {e}')

    # Parse STEP graph into DB — synchronous for small files, async for large ones
    header_id = None
    parsing_status = 'skipped'

    if part_id:
        if is_large:
            # Enqueue background task so the HTTP response is not held up
            try:
                from app.tasks.step_graph_tasks import parse_graph_async
                parse_graph_async.delay(file_path, part_id)
                parsing_status = 'queued'
                logger.info(
                    f"Large file ({file_size_mb:.1f} MB) — graph parse queued "
                    f"for part {part_id}"
                )
            except Exception as e:
                # Celery not available — leave header_id as None; user can trigger parse later
                parsing_status = 'deferred'
                logger.warning(f"Could not queue graph parse for {filename}: {e}")
        else:
            try:
                from app.services.step_graph_storage import parse_step_graph_for_part
                header_id = parse_step_graph_for_part(file_path, part_id)
                parsing_status = 'done'
                logger.info(f"Graph parsed for part {part_id}: header_id={header_id}")
            except Exception as e:
                parsing_status = 'failed'
                logger.warning(f"Graph storage failed for {filename}: {e}")

    return jsonify({
        'success': True,
        'filename': filename,
        'file_path': file_path,
        'file_size_mb': round(file_size_mb, 2),
        'part_id': part_id,
        'header_id': header_id,
        'parsing_status': parsing_status,
        'message': (
            f'File {filename} uploaded. Graph parsing queued in background.'
            if parsing_status == 'queued'
            else f'File {filename} uploaded successfully'
        ),
    }), 201


@bp.route('/part/<string:part_id>/update', methods=['POST'])
def update_part_filepath(part_id):
    """Update Part file_path (for fixing broken records)."""
    data = request.get_json() or {}
    file_path = data.get('file_path')
    if not file_path:
        return jsonify({'error': 'file_path required'}), 400
    try:
        part = Part.query.get(part_id)
        if not part:
            return jsonify({'error': 'Part not found'}), 404
        if data.get('name'):
            part.name = data['name']
        part.file_path = file_path
        db.session.commit()
        return jsonify({'success': True, 'part_id': part_id, 'file_path': file_path})
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500


@bp.route('/status', methods=['GET'])
def upload_status():
    """Check upload service status."""
    upload_folder = current_app.config.get('UPLOAD_FOLDER', '/app/data/uploads')
    return jsonify({
        'status': 'ok',
        'upload_folder': str(upload_folder),
        'folder_exists': os.path.exists(str(upload_folder))
    })
