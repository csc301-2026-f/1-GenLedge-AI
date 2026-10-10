"""Local-demo authentication over Flask's signed cookie session."""
from flask import Blueprint, jsonify, request, session

bp = Blueprint('auth', __name__, url_prefix='/api/auth')


@bp.post('/login')
def login():
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return invalid('Expected a JSON object.')
    for field in ('username', 'password'):
        if not isinstance(data.get(field), str) or not data[field].strip():
            return invalid(f'{field} must be a non-empty string.')
    remember = data.get('remember_me', False)
    if not isinstance(remember, bool):
        return invalid('remember_me must be a boolean.')
    username = data['username'].strip()
    user = dict(id='demo-user', username=username, email=username, role='Administrator')
    session.clear()
    session.permanent = remember
    session['user'] = user
    return jsonify(user=user)


def invalid(message):
    return jsonify(error=dict(code='invalid_request', message=message)), 400


@bp.get('/me')
def me():
    user = session.get('user')
    if not user:
        return jsonify(error=dict(code='unauthorized', message='Authentication required.')), 401
    return jsonify(user=user)


@bp.post('/logout')
def logout():
    session.clear()
    return jsonify(success=True)
