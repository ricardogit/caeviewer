"""Alembic chain on an empty database: ``upgrade head`` builds the models' schema (no autogenerate diff)
and ``downgrade base`` removes every table again.

Uses its own database ``<TEST_DATABASE_URL name>_migrations`` (created if missing, schema reset each run);
skipped without a local PostgreSQL.
"""
import os

import pytest

MIGRATIONS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'migrations')


@pytest.fixture(scope='module')
def app():
    psycopg2 = pytest.importorskip('psycopg2')
    from config.config import TestingConfig
    original = TestingConfig.SQLALCHEMY_DATABASE_URI
    base, name = str(original).replace('postgresql+psycopg2://', 'postgresql://').rsplit('/', 1)
    name = f'{name}_migrations'
    try:
        conn = psycopg2.connect(base + '/postgres', connect_timeout=3)
    except Exception as e:                                       # no local Postgres
        pytest.skip(f'PostgreSQL not available: {e}')
    conn.autocommit = True
    with conn.cursor() as cur:
        cur.execute('SELECT 1 FROM pg_database WHERE datname = %s', (name,))
        if cur.fetchone() is None:
            cur.execute(f'CREATE DATABASE "{name}"')
    conn.close()

    TestingConfig.SQLALCHEMY_DATABASE_URI = base.replace('postgresql://', 'postgresql+psycopg2://') + '/' + name
    try:
        from app import create_app
        app = create_app('testing')
    finally:
        TestingConfig.SQLALCHEMY_DATABASE_URI = original
    with app.app_context():
        _reset_schema()
    yield app
    with app.app_context():
        _reset_schema()


def _reset_schema():
    from sqlalchemy import text
    from app.extensions import db
    assert db.engine.url.database.endswith('_migrations'), db.engine.url   # never wipe a real database
    db.session.remove()
    with db.engine.begin() as conn:
        conn.execute(text('DROP SCHEMA public CASCADE; CREATE SCHEMA public'))


def _tables():
    from sqlalchemy import inspect
    from app.extensions import db
    return set(inspect(db.engine).get_table_names())


def test_upgrade_head_on_empty_db_matches_models_and_downgrades_to_base(app):
    import flask_migrate
    from alembic.autogenerate import compare_metadata
    from alembic.migration import MigrationContext
    from app.extensions import db

    with app.app_context():
        flask_migrate.upgrade(directory=MIGRATIONS)
        assert set(db.metadata.tables) <= _tables()
        with db.engine.connect() as conn:
            diff = compare_metadata(MigrationContext.configure(conn), db.metadata)
        assert diff == [], diff

        flask_migrate.downgrade(directory=MIGRATIONS, revision='base')
        assert _tables() == {'alembic_version'}
