"""/api/auth — login, logout, me; /api/auth/projects — minimal project CRUD."""
from flask import Blueprint, jsonify, request
from flask_login import login_user, logout_user, current_user, login_required

from app.extensions import db
from app.auth.models import User, Project

bp = Blueprint('auth', __name__)


@bp.route('/login', methods=['POST'])
def login():
    body = request.get_json(silent=True) or {}
    user = User.query.filter_by(email=(body.get('email') or '').lower()).first()
    if user is None or not user.active or not user.check_password(body.get('password') or ''):
        return jsonify({'error': 'Credenciales inválidas'}), 401
    login_user(user, remember=bool(body.get('remember')))
    return jsonify(user.to_dict())


@bp.route('/logout', methods=['POST'])
def logout():
    logout_user()
    return jsonify({'ok': True})


@bp.route('/me', methods=['GET'])
def me():
    if not current_user.is_authenticated:
        return jsonify({'authenticated': False}), 200
    return jsonify({'authenticated': True, 'user': current_user.to_dict()})


@bp.route('/projects', methods=['GET'])
@login_required
def list_projects():
    rows = Project.query.filter_by(owner_id=current_user.id).order_by(Project.created_at.desc()).all()
    return jsonify({'projects': [p.to_dict() for p in rows]})


@bp.route('/projects', methods=['POST'])
@login_required
def create_project():
    body = request.get_json(silent=True) or {}
    if not (body.get('name') or '').strip():
        return jsonify({'error': 'name is required'}), 400
    p = Project(name=body['name'].strip(), description=body.get('description'), owner_id=current_user.id)
    db.session.add(p)
    db.session.commit()
    return jsonify(p.to_dict()), 201
