"""Opt-in PostgreSQL check in a disposable schema owned by the current role."""
import os
import uuid

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.engine import make_url

from app import create_app


@pytest.mark.skipif(not os.environ.get('TEST_DATABASE_URL'), reason='Set TEST_DATABASE_URL to run against a developer-owned PostgreSQL database')
def test_postgres_auth_flow_in_disposable_schema():
    url = make_url(os.environ['TEST_DATABASE_URL'])
    if not url.drivername.startswith('postgresql'):
        pytest.fail('TEST_DATABASE_URL must use PostgreSQL')

    sslmode = os.environ.get('DB_SSLMODE', 'require')
    if sslmode not in {'require', 'verify-ca', 'verify-full'}:
        pytest.fail('DB_SSLMODE must be require, verify-ca, or verify-full')
    root_cert = os.environ.get('DB_SSLROOTCERT')
    if sslmode in {'verify-ca', 'verify-full'} and not root_cert:
        pytest.fail('DB_SSLROOTCERT is required for certificate verification')
    connect_args = {'sslmode': sslmode}
    if root_cert:
        connect_args['sslrootcert'] = root_cert

    schema = 'auth_test_' + uuid.uuid4().hex
    admin_engine = create_engine(url, connect_args=connect_args)
    with admin_engine.begin() as connection:
        identity = connection.execute(text(
            'SELECT current_user, current_database(), '
            '(SELECT ssl FROM pg_stat_ssl WHERE pid = pg_backend_pid())'
        )).one()
        if identity[0] == 'postgres' or identity[0] != identity[1]:
            pytest.fail('Use a developer-owned database with a role matching its database name')
        assert identity[2] is True
        connection.execute(text(f'CREATE SCHEMA "{schema}"'))

    forbidden_database = os.environ.get('TEST_FORBIDDEN_DATABASE')
    if forbidden_database:
        forbidden_engine = create_engine(url.set(database=forbidden_database), connect_args=connect_args)
        try:
            with pytest.raises(OperationalError):
                with forbidden_engine.connect():
                    pass
        finally:
            forbidden_engine.dispose()

    test_args = dict(connect_args, options=f'-csearch_path={schema}')

    class TestConfig:
        TESTING = True
        SECRET_KEY = 'postgres-integration-test-secret'
        DATABASE_URL = url.render_as_string(hide_password=False)
        DB_SSLMODE = sslmode
        DB_SSLROOTCERT = root_cert
        SESSION_COOKIE_SECURE = False

    app = None
    try:
        app = create_app(TestConfig)
        app.extensions['auth_engine'].dispose()
        scoped_engine = create_engine(url, connect_args=test_args)
        app.extensions['auth_engine'] = scoped_engine
        from sqlalchemy.orm import sessionmaker
        from app.migrations import upgrade_database
        app.extensions['auth_database'] = sessionmaker(scoped_engine)
        app.extensions['auth_migrate'] = lambda: upgrade_database(scoped_engine)

        runner = app.test_cli_runner()
        assert runner.invoke(args=['auth-init-db']).exit_code == 0
        assert runner.invoke(
            args=['auth-create-user', '--email', 'test@example.com', '--organization', 'Test Org'],
            input='testing-password-123\ntesting-password-123\n',
        ).exit_code == 0

        client = app.test_client()
        token = client.get('/api/auth/csrf').json['csrfToken']
        login = client.post('/api/auth/login', json={
            'email': 'test@example.com', 'password': 'testing-password-123'
        }, headers={'X-CSRF-Token': token})
        assert login.status_code == 200
        assert client.get('/api/auth/me').status_code == 200
        token = client.get('/api/auth/csrf').json['csrfToken']
        assert client.post('/api/auth/logout', headers={'X-CSRF-Token': token}).status_code == 204
        assert client.get('/api/auth/me').status_code == 401
    finally:
        if app:
            app.extensions['auth_engine'].dispose()
        with admin_engine.begin() as connection:
            connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        admin_engine.dispose()
