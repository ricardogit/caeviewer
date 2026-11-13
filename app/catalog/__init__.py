"""Hub tool catalog (Engineering Hub, H1d).

    flask catalog seed [--prune]   # upsert seed_data.CATALOG by slug
"""
import click
from flask.cli import AppGroup


def init_catalog(app):
    from app.catalog.api import bp
    app.register_blueprint(bp, url_prefix='/api/catalog', strict_slashes=False)

    group = AppGroup('catalog', help='Hub tool catalog')

    @group.command('seed')
    @click.option('--prune', is_flag=True, help='Disable rows whose slug is no longer in seed_data')
    def seed(prune):
        """Insert/update the catalog from app/catalog/seed_data.py (idempotent)."""
        from app.extensions import db
        from app.catalog.seed_data import seed_catalog
        click.echo(seed_catalog(db, prune=prune))

    app.cli.add_command(group)
