"""
Files API — list, detail, delete STEP files.
In CAPP this lived in step_view_bridge.py; here it's a first-class endpoint.
"""
import os
import logging
from flask import Blueprint, jsonify, current_app
from app.models import Part
from app.models.step_storage import STEPFileHeader
from app.extensions import db

logger = logging.getLogger(__name__)
bp = Blueprint('files_api', __name__)


# Small files found on disk are parsed when adopted (as an upload would); bigger ones only get
# their Part row, so listing never blocks on a long parse.
_ADOPT_PARSE_BYTES = 2 * 1024 * 1024


def _adopt_disk_files():
    """Register STEP files sitting in the upload folder without a Part row (copied in by hand,
    or left over from a reset database), so every listed file has a real id. Before this they
    were listed with a fake id (``name_stp``) that every viewer route rejected."""
    upload_folder = str(current_app.config.get('UPLOAD_FOLDER', 'data/uploads'))
    if not os.path.isdir(upload_folder):
        return
    try:
        known = {os.path.abspath(p) for (p,) in db.session.query(Part.file_path)
                 .filter(Part.file_path.isnot(None)).all()}
    except Exception as e:
        db.session.rollback()
        logger.warning(f"Could not read registered files: {e}")
        return
    from app.step_view_pro.backend.api.upload_routes import register_step_file, ALLOWED_EXTENSIONS
    for fname in sorted(os.listdir(upload_folder)):
        fpath = os.path.abspath(os.path.join(upload_folder, fname))
        if os.path.splitext(fname.lower())[1] not in ALLOWED_EXTENSIONS or fpath in known                 or not os.path.isfile(fpath):
            continue
        try:
            part_id, _, status = register_step_file(fpath, sync_parse_bytes=_ADOPT_PARSE_BYTES, queue_large=False)
            logger.info(f"Adopted {fname} from disk as part {part_id} (graph: {status})")
        except Exception as e:
            db.session.rollback()
            logger.warning(f"Could not adopt {fname}: {e}")


@bp.route('/files', methods=['GET'])
def list_files():
    """Return all uploaded STEP files."""
    files = []
    _adopt_disk_files()

    try:
        parts = Part.query.filter(Part.file_path.isnot(None)).order_by(Part.created_at.desc()).all()
        for part in parts:
            file_size_mb = 0
            if part.file_path and os.path.exists(part.file_path):
                try:
                    file_size_mb = round(os.path.getsize(part.file_path) / (1024 * 1024), 2)
                except Exception:
                    pass

            header_id = str(part.id)
            try:
                hdr = STEPFileHeader.query.filter_by(part_id=part.id).first()
                if not hdr:
                    hdr = STEPFileHeader(
                        part_id=part.id,
                        file_name=part.name,
                        original_filename=os.path.basename(part.file_path) if part.file_path else part.name,
                    )
                    db.session.add(hdr)
                    db.session.commit()
                header_id = str(hdr.id)
                entity_count = hdr.entity_count or 0
            except Exception as e:
                logger.warning(f"Could not resolve header for part {part.id}: {e}")
                db.session.rollback()
                entity_count = 0

            display_name = os.path.basename(part.file_path) if part.file_path else part.name
            files.append({
                'id': str(part.id),
                'header_id': header_id,
                'original_filename': display_name,
                'filename': display_name,
                'file_name': display_name,
                'entity_count': entity_count,
                'file_size_mb': file_size_mb,
                'source': 'upload',
                'created_at': part.created_at.isoformat() if part.created_at else None,
            })
    except Exception as e:
        logger.error(f"Error listing files: {e}")
        return jsonify({'error': str(e)}), 500

    return jsonify({'files': files, 'total': len(files)}), 200


@bp.route('/files/<string:file_id>', methods=['DELETE'])
def delete_file(file_id):
    """Delete a STEP file and its DB records."""
    try:
        part = Part.query.filter_by(id=file_id).first()
        if not part:
            return jsonify({'error': 'File not found'}), 404

        # Remove from disk
        if part.file_path and os.path.exists(part.file_path):
            try:
                os.remove(part.file_path)
            except Exception as e:
                logger.warning(f"Could not remove file {part.file_path}: {e}")

        # Remove GLB cache
        try:
            from flask import current_app
            glb_dir = os.path.join(str(current_app.config.get('UPLOAD_FOLDER', 'data/uploads')), 'glb_cache')
            for ext in ('', '.processing', '.error'):
                glb = os.path.join(glb_dir, f"{part.file_hash or part.id}.glb{ext}")
                if os.path.exists(glb):
                    os.remove(glb)
        except Exception:
            pass

        db.session.delete(part)
        db.session.commit()
        return jsonify({'success': True, 'deleted_id': file_id}), 200
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error deleting file {file_id}: {e}")
        return jsonify({'error': str(e)}), 500
