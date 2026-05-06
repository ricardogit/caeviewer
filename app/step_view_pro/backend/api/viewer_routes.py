"""
Viewer API Routes - GLB serving, progress tracking, and metadata.
/files and /geometry are handled by step_view_bridge and geometry_routes respectively.

GLB conversion runs in a daemon background thread so the HTTP request returns 202
immediately instead of blocking the Flask worker for minutes. The frontend polls
GET /model/<id>/glb until it receives 200 (GLB ready) or 500 (failed).
"""

from flask import Blueprint, jsonify, send_file, request
from datetime import datetime
import logging
import os
import threading
import time

from app.step_view_pro.models import STEPFileHeader
from app.models import Part
from app.extensions import db

try:
    from app.step_view_pro.backend.step_to_glb_converter import (
        convert_step_to_glb, PYTHONOCC_AVAILABLE as _OCC_AVAILABLE
    )
    GLB_CONVERTER_AVAILABLE = True
    OCC_AVAILABLE = _OCC_AVAILABLE
except ImportError:
    GLB_CONVERTER_AVAILABLE = False
    OCC_AVAILABLE = False
    logging.warning("step_to_glb_converter not available. GLB conversion will be disabled.")

try:
    from app.step_view_pro.backend.progress_tracker import get_progress_tracker
    PROGRESS_TRACKER_AVAILABLE = True
except ImportError:
    PROGRESS_TRACKER_AVAILABLE = False
    logging.warning("progress_tracker not available. Progress tracking will be disabled.")

logger = logging.getLogger(__name__)
bp = Blueprint('viewer_api', __name__)

# Maximum age (seconds) of a .processing sentinel before it is considered stale
# (e.g. server restarted mid-conversion).
_STALE_PROCESSING_AGE = 600  # 10 minutes


def _processing_path(glb_path: str) -> str:
    return glb_path + '.processing'


def _error_path(glb_path: str) -> str:
    return glb_path + '.error'


_MAX_STEP_MB_FOR_CONVERSION = 200  # files larger than this are rejected early

def _quality_for_file(step_path: str, complexity_score) -> str:
    """Choose tessellation quality based on file size. Larger files → coarser mesh."""
    try:
        mb = os.path.getsize(step_path) / (1024 * 1024)
    except OSError:
        mb = 0
    if mb > 50:
        return 'low'
    if mb > 15:
        return 'low'
    if complexity_score and complexity_score > 0.7:
        return 'low'
    return 'medium'


def _convert_glb_background(step_path: str, glb_path: str, quality: str) -> None:
    """Background thread: convert STEP → GLB, then replace the processing sentinel."""
    import tempfile
    processing = _processing_path(glb_path)
    error_file = _error_path(glb_path)
    glb_dir = os.path.dirname(glb_path)

    # Use a temp file with a clean .glb suffix so the converter's stem extraction
    # yields a plain UUID-like name, not 'abc.glb' (which would produce 'abc.glb.glb').
    fd, tmp_path = tempfile.mkstemp(suffix='.glb', dir=glb_dir)
    os.close(fd)

    try:
        logger.info(f"[bg] GLB conversion start: {step_path} quality={quality}")
        success, result = convert_step_to_glb(step_path, tmp_path, quality=quality)

        if not success:
            msg = result or 'Conversion returned failure'
            with open(error_file, 'w') as f:
                f.write(msg)
            logger.error(f"[bg] GLB conversion failed: {msg}")
            return

        # The converter may have written to a path different from tmp_path
        # (e.g. changed extension to .stl when trimesh is unavailable).
        actual = result if (result and os.path.exists(result)) else None
        if actual is None and os.path.exists(tmp_path):
            actual = tmp_path

        if actual is None:
            msg = f'Conversion succeeded but output file not found (expected {tmp_path})'
            with open(error_file, 'w') as f:
                f.write(msg)
            logger.error(f"[bg] {msg}")
            return

        # Reject STL output — the frontend GLTFLoader cannot parse it.
        if actual.endswith('.stl'):
            msg = ('GLB export requires trimesh. '
                   'Install: pip install trimesh numpy. '
                   'File was tessellated but saved as STL instead of GLB.')
            with open(error_file, 'w') as f:
                f.write(msg)
            logger.error(f"[bg] {msg}")
            try:
                os.remove(actual)
            except Exception:
                pass
            return

        os.replace(actual, glb_path)
        logger.info(f"[bg] GLB ready: {glb_path}")

    except Exception as exc:
        logger.error(f"[bg] GLB conversion exception: {exc}", exc_info=True)
        try:
            with open(error_file, 'w') as f:
                f.write(str(exc))
        except Exception:
            pass
    finally:
        for path in (processing, tmp_path):
            try:
                if os.path.exists(path):
                    os.remove(path)
            except Exception:
                pass


@bp.route('/model/<string:model_id>/glb', methods=['GET'])
def get_model_glb(model_id):
    """
    Serve the cached GLB for a model.

    On first request the conversion starts in a daemon background thread and this
    endpoint returns HTTP 202 immediately. The frontend should retry every
    ``retry_after`` seconds (5 s default) until it receives a 200 with the GLB
    binary or a 5xx error.
    """
    try:
        # Resolve Part — accept both part.id and STEPFileHeader.id
        part = Part.query.filter_by(id=model_id).first()
        if not part:
            header = STEPFileHeader.query.filter_by(id=model_id).first()
            if header:
                part = header.part

        if not part:
            return jsonify({'error': 'Part not found'}), 404

        from flask import current_app
        glb_dir = os.path.join(
            str(current_app.config.get('UPLOAD_FOLDER', 'data/uploads')), 'glb_cache'
        )
        os.makedirs(glb_dir, exist_ok=True)

        glb_filename = f"{part.file_hash or part.id}.glb"
        glb_path = os.path.join(glb_dir, glb_filename)

        # ── 1. Already converted → serve immediately ──────────────────────────
        if os.path.exists(glb_path):
            return send_file(
                glb_path,
                mimetype='model/gltf-binary',
                as_attachment=False,
                download_name=f"{part.name or 'model'}.glb"
            )

        # ── 2. Previous attempt failed → report error ──────────────────────────
        error_file = _error_path(glb_path)
        if os.path.exists(error_file):
            try:
                with open(error_file) as f:
                    error_msg = f.read().strip()
            except Exception:
                error_msg = 'Conversion failed (see server logs)'
            return jsonify({'error': 'GLB conversion failed', 'message': error_msg}), 500

        # ── 3. Conversion in progress → tell client to retry ──────────────────
        processing = _processing_path(glb_path)
        if os.path.exists(processing):
            age = time.time() - os.path.getmtime(processing)
            if age < _STALE_PROCESSING_AGE:
                return jsonify({
                    'status': 'processing',
                    'message': 'Model is being prepared, please retry shortly.',
                    'retry_after': 5,
                }), 202
            # Sentinel is stale — fall through to restart conversion
            logger.warning(f"Stale .processing file ({age:.0f}s old), restarting conversion")
            try:
                os.remove(processing)
            except Exception:
                pass

        # ── 4. Validate source STEP file ──────────────────────────────────────
        if not part.file_path or not os.path.exists(part.file_path):
            return jsonify({
                'error': 'STEP file not found on disk',
                'path': part.file_path,
            }), 404

        if not GLB_CONVERTER_AVAILABLE:
            return jsonify({'error': 'GLB conversion not available (pythonocc not installed)'}), 503

        if not OCC_AVAILABLE:
            return jsonify({
                'error': 'pythonocc-core not installed',
                'message': (
                    'OpenCASCADE (pythonocc-core) is required for STEP → GLB conversion. '
                    'Install via conda: conda install -c conda-forge pythonocc-core=7.7.2 trimesh numpy '
                    'and restart the server using that conda environment.'
                ),
            }), 503

        # ── 5. Reject files that are too large to tessellate safely ──────────
        try:
            step_mb = os.path.getsize(part.file_path) / (1024 * 1024)
        except OSError:
            step_mb = 0
        if step_mb > _MAX_STEP_MB_FOR_CONVERSION:
            return jsonify({
                'error': 'File too large for browser visualization',
                'message': (
                    f'The STEP file is {step_mb:.0f} MB. '
                    f'Browser GLB visualization supports files up to {_MAX_STEP_MB_FOR_CONVERSION} MB. '
                    'Large assemblies can be broken into sub-assemblies for visualization.'
                ),
            }), 422

        # ── 6. Start background conversion ────────────────────────────────────
        quality = _quality_for_file(part.file_path, part.complexity_score)

        # Create sentinel atomically so concurrent requests don't spawn two threads
        try:
            fd = os.open(processing, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.close(fd)
        except FileExistsError:
            # Another request just created it — tell client to poll
            return jsonify({
                'status': 'processing',
                'message': 'Model is being prepared, please retry shortly.',
                'retry_after': 5,
            }), 202

        step_path = part.file_path
        thread = threading.Thread(
            target=_convert_glb_background,
            args=(step_path, glb_path, quality),
            daemon=True,
            name=f"glb-{str(part.id)[:8]}",
        )
        thread.start()

        file_size_mb = os.path.getsize(step_path) / (1024 * 1024)
        logger.info(
            f"GLB conversion queued in background: {os.path.basename(step_path)} "
            f"({file_size_mb:.1f} MB, quality={quality})"
        )

        return jsonify({
            'status': 'processing',
            'message': (
                f'Converting {os.path.basename(step_path)} ({file_size_mb:.1f} MB) '
                f'— first load takes 30-120 s. Retrying automatically.'
            ),
            'retry_after': 5,
        }), 202

    except Exception as e:
        logger.error(f"Error in get_model_glb: {e}", exc_info=True)
        return jsonify({'error': 'Internal server error', 'message': str(e)}), 500


@bp.route('/progress/<string:job_id>', methods=['GET'])
def get_conversion_progress(job_id):
    """Poll GLB conversion progress."""
    if not PROGRESS_TRACKER_AVAILABLE:
        return jsonify({'error': 'Progress tracking not available'}), 503
    try:
        tracker = get_progress_tracker()
        progress_data = tracker.get_progress(job_id)
        if not progress_data:
            return jsonify({'error': 'Job not found'}), 404
        return jsonify(progress_data), 200
    except Exception as e:
        logger.error(f"Error getting progress for job {job_id}: {e}")
        return jsonify({'error': 'Internal server error', 'message': str(e)}), 500


@bp.route('/model/<string:model_id>/metadata', methods=['GET'])
def get_model_metadata(model_id):
    """Return Part metadata by part_id or STEPFileHeader.id."""
    try:
        part = Part.query.filter_by(id=model_id).first()
        if not part:
            header = STEPFileHeader.query.filter_by(id=model_id).first()
            if header:
                part = header.part

        if not part:
            return jsonify({'error': 'Part not found'}), 404

        file_size_mb = None
        if part.file_path and os.path.exists(part.file_path):
            file_size_mb = os.path.getsize(part.file_path) / (1024 * 1024)

        header_id = None
        try:
            step_header = STEPFileHeader.query.filter_by(part_id=part.id).first()
            if step_header:
                header_id = str(step_header.id)
        except Exception:
            pass

        return jsonify({
            'file_name': part.name,
            'file_size_mb': round(file_size_mb, 2) if file_size_mb else None,
            'complexity_score': part.complexity_score,
            'upload_date': part.created_at.isoformat() if part.created_at else None,
            'header_id': header_id,
            'part_number': part.part_number,
            'material': part.material,
            'bounding_box': part.bounding_box,
            'estimated_volume': part.estimated_volume,
            'estimated_weight': part.estimated_weight,
        }), 200

    except Exception as e:
        logger.error(f'Error getting model metadata: {e}', exc_info=True)
        return jsonify({'error': 'Failed to get metadata', 'message': str(e)}), 500


@bp.route('/health', methods=['GET'])
def health_check():
    """Health check."""
    return jsonify({
        'service': 'step_view_pro',
        'version': '1.0.0',
        'status': 'healthy',
        'timestamp': datetime.utcnow().isoformat()
    }), 200


logger.info("[OK] Viewer API routes loaded (/model/*/glb, /progress/*, /model/*/metadata, /health)")
