"""Authentication (Flask-Login, session cookie).

``AUTH_REQUIRED`` (env, default false) gates every /api/* route except
/api/auth/*. It stays off until the frontend has a login page, so the
current UI keeps working.
"""
import click
from flask import jsonify, request
from flask_login import LoginManager, current_user

login_manager = LoginManager()


def init_auth(app):
    from app.auth.api import bp
    from app.auth.models import User
    from app.extensions import db

    login_manager.init_app(app)
    app.register_blueprint(bp, url_prefix='/api/auth')

    @login_manager.user_loader
    def _load(user_id):
        try:
            return db.session.get(User, user_id)
        except Exception:
            return None

    @login_manager.unauthorized_handler
    def _unauth():
        return jsonify({'error': 'Authentication required'}), 401

    @app.before_request
    def _guard():
        if not app.config.get('AUTH_REQUIRED'):
            return None
        p = request.path
        if p.startswith('/api/') and not p.startswith('/api/auth/') and request.method != 'OPTIONS':
            if not current_user.is_authenticated:
                return jsonify({'error': 'Authentication required'}), 401
        return None

    @app.cli.command('create-user')
    @click.argument('email')
    @click.option('--name', default=None)
    @click.option('--role', default='engineer', type=click.Choice(['admin', 'engineer', 'viewer']))
    @click.password_option()
    def create_user(email, name, role, password):
        """Create a user: flask create-user ana@example.com --role admin"""
        if User.query.filter_by(email=email.lower()).first():
            raise click.ClickException('User already exists')
        u = User(email=email.lower(), name=name, role=role)
        u.set_password(password)
        db.session.add(u)
        db.session.commit()
        click.echo(f'Created {u.email} ({u.role})')
