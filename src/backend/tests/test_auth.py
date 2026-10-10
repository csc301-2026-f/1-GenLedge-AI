from datetime import timedelta

import pytest
from app import create_app


@pytest.fixture
def app():
    class TestConfig:
        TESTING = True
        SECRET_KEY = 'test-only-secret'
        BACKEND_PORT = 5123
    return create_app(TestConfig)


@pytest.fixture
def client(app):
    return app.test_client()


def test_session_lifecycle(client):
    assert client.get('/api/auth/me').status_code == 401
    response = client.post('/api/auth/login', json={'username': ' demo ', 'password': ' secret '})
    assert response.status_code == 200
    expected = {'user': {'id': 'demo-user', 'username': 'demo', 'email': 'demo', 'role': 'Administrator'}}
    assert response.json == expected
    cookie = response.headers['Set-Cookie']
    assert 'HttpOnly' in cookie and 'SameSite=Lax' in cookie
    assert 'Expires=' not in cookie and 'Secure' not in cookie
    with client.session_transaction() as session:
        assert session['user'] == expected['user']
        assert not session.permanent
        assert 'password' not in session
    assert client.get('/api/auth/me').json == expected
    for _ in range(2):
        assert client.post('/api/auth/logout').json == {'success': True}
        response = client.get('/api/auth/me')
        assert response.status_code == 401
        assert response.json == {'error': {'code': 'unauthorized', 'message': 'Authentication required.'}}


@pytest.mark.parametrize('payload', [None, [], 'string', {}, {'username': 'u'}, {'password': 'p'},
    {'username': ' ', 'password': 'p'}, {'username': 'u', 'password': ' '},
    {'username': 1, 'password': 'p'}, {'username': 'u', 'password': False},
    {'username': 'u', 'password': 'p', 'remember_me': 'true'},
    {'username': 'u', 'password': 'p', 'remember_me': 1},
    {'username': 'u', 'password': 'p', 'remember_me': None}])
def test_bad_login(client, payload):
    response = client.post('/api/auth/login', json=payload)
    assert response.status_code == 400
    assert response.json['error']['code'] == 'invalid_request'


def test_malformed_json(client):
    response = client.post('/api/auth/login', data='{', content_type='application/json')
    assert response.status_code == 400
    assert response.json['error']['code'] == 'invalid_request'


def test_remember_and_session_replacement(app, client):
    with client.session_transaction() as session:
        session['old'] = 'discard'
    response = client.post('/api/auth/login', json={'username': 'u', 'password': 'p', 'remember_me': True})
    assert response.status_code == 200
    assert 'Expires=' in response.headers['Set-Cookie']
    assert app.permanent_session_lifetime == timedelta(days=14)
    with client.session_transaction() as session:
        assert session.permanent
        assert 'old' not in session
    client.post('/api/auth/login', json={'username': 'next', 'password': 'p'})
    with client.session_transaction() as session:
        assert not session.permanent
        assert session['user']['username'] == 'next'


def test_config(app, monkeypatch):
    assert app.config['SECRET_KEY'] == 'test-only-secret'
    assert app.config['BACKEND_PORT'] == 5123
    monkeypatch.setenv('GENLEDGE_SESSION_SECRET', 'environment-secret')
    monkeypatch.setenv('GENLEDGE_BACKEND_PORT', '5124')
    configured = create_app()
    assert configured.config['SECRET_KEY'] == 'environment-secret'
    assert configured.config['BACKEND_PORT'] == 5124
