import pytest
from sqlalchemy import create_engine, inspect, text

from app import create_app
from app.config import Config
from app.migrations import upgrade_database


def test_dotenv_values_and_process_precedence(tmp_path, monkeypatch):
    import app.config as config_module

    env_file = tmp_path / '.env'
    env_file.write_text(
        'APP_ENV=development\n'
        'SECRET_KEY=file-secret\n'
        'DB_SSLMODE=require\n',
        encoding='utf-8',
    )
    monkeypatch.setattr(config_module, 'ENV_FILE', env_file)
    for name in ('HOST', 'PORT', 'DATABASE', 'USER', 'PASSWORD'):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.delenv('SECRET_KEY', raising=False)
    values = Config()
    assert values.DATABASE_URL is None
    assert values.SECRET_KEY == 'file-secret'

    monkeypatch.setenv('HOST', 'db.example')
    monkeypatch.setenv('PORT', '5432')
    monkeypatch.setenv('DATABASE', 'from-process')
    monkeypatch.setenv('USER', 'developer')
    monkeypatch.setenv('PASSWORD', 'p@ssword')
    assert Config().DATABASE_URL == 'postgresql+psycopg://developer:p%40ssword@db.example:5432/from-process'


def test_placeholder_and_tls_validation(tmp_path, monkeypatch):
    import app.config as config_module

    monkeypatch.setattr(config_module, 'ENV_FILE', tmp_path / '.env')
    monkeypatch.setenv('HOST', 'YOUR_DB_HOST')
    monkeypatch.setenv('PORT', '5432')
    monkeypatch.setenv('DATABASE', 'db')
    monkeypatch.setenv('USER', 'user')
    monkeypatch.setenv('PASSWORD', 'pass')
    with pytest.raises(RuntimeError, match='placeholder'):
        Config()

    monkeypatch.setenv('HOST', 'host')
    monkeypatch.setenv('DB_SSLMODE', 'verify-full')
    monkeypatch.delenv('DB_SSLROOTCERT', raising=False)
    with pytest.raises(RuntimeError, match='DB_SSLROOTCERT'):
        Config()

    monkeypatch.setenv('DB_SSLROOTCERT', 'certificate.crt')
    assert Config().DB_SSLMODE == 'verify-full'


def test_postgres_connect_args(monkeypatch):
    import app.auth as auth_module

    seen = {}
    real_create_engine = auth_module.create_engine

    def capture(url, **kwargs):
        seen['url'] = url
        seen['connect_args'] = kwargs['connect_args']
        return real_create_engine('sqlite:///:memory:')

    monkeypatch.setattr(auth_module, 'create_engine', capture)

    class TestConfig:
        TESTING = True
        SECRET_KEY = 'test-secret'
        DATABASE_URL = 'postgresql+psycopg://user:password@host/db'
        DB_SSLMODE = 'verify-full'
        DB_SSLROOTCERT = 'certificate.crt'

    app = create_app(TestConfig)
    assert seen['connect_args'] == {'sslmode': 'verify-full', 'sslrootcert': 'certificate.crt'}
    app.extensions['auth_engine'].dispose()


def test_migration_rejects_existing_unversioned_tables(tmp_path):
    engine = create_engine('sqlite:///' + str(tmp_path / 'existing.sqlite3'))
    with engine.begin() as connection:
        connection.execute(text('CREATE TABLE auth_users (id VARCHAR(36) PRIMARY KEY)'))
    with pytest.raises(RuntimeError, match='schema review'):
        upgrade_database(engine)
    assert 'auth_users' in inspect(engine).get_table_names()
    engine.dispose()


def test_migration_creates_expected_auth_schema(tmp_path):
    engine = create_engine('sqlite:///' + str(tmp_path / 'fresh.sqlite3'))
    upgrade_database(engine)
    tables = set(inspect(engine).get_table_names())
    assert {'auth_organizations', 'auth_users', 'auth_sessions', 'alembic_version',
            'intake_sources', 'intake_batches', 'intake_collections', 'intake_records',
            'intake_fields', 'source_mappings', 'intake_pins'} <= tables
    upgrade_database(engine)
    with engine.connect() as connection:
        assert connection.scalar(text('SELECT version_num FROM alembic_version')) == '0003_mapping_retention'
    engine.dispose()
