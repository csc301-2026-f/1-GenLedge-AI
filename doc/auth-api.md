# Local demo authentication API

Flask routes: `src/backend/app/auth/routes.py`; registered by `create_app`.
All responses are JSON. This demo accepts any non-empty string username and password; it does not verify identity or email and has no registration or database.

| Request | Result |
| --- | --- |
| `POST /api/auth/login` with `{"username":"demo","password":"example","remember_me":false}` | 200, `{"user":{"id":"demo-user","username":"demo","email":"demo","role":"Administrator"}}`, session cookie |
| `GET /api/auth/me` with cookie | 200, same user object; 401 without a valid session |
| `POST /api/auth/logout` | 200, `{"success":true}`; clears session, also succeeds when already signed out |

Username is trimmed. Email mirrors username for the demo UI. Missing/blank/non-string credentials, malformed/non-object JSON and non-boolean remember_me return 400 with `{"error":{"code":"invalid_request","message":"..."}}`. Unauthenticated me returns `{"error":{"code":"unauthorized","message":"Authentication required."}}`.

Cookies use HttpOnly, SameSite=Lax and Secure=false for local HTTP. Login replaces the previous session. The default is a browser-session cookie; remember_me=true creates a 14-day permanent session. Passwords are neither stored nor returned. Logout cannot revoke a stolen signed cookie server-side.

`GENLEDGE_BACKEND_PORT` is an integer (default 5000); `main.py` binds to 127.0.0.1. `GENLEDGE_SESSION_SECRET` sets the signing key, falling back to the explicitly insecure `insecure-local-demo-only` for first-time local use. Production requires a strong private secret and a different identity/session design. Do not use this demo as production authentication.

Run from `src/backend`: `python -m pytest tests`; start with `python main.py`. Test dependencies are in requirements-dev.txt. The factory retains config_object overrides. Frontend requests must include cookies, using relative /api URLs through the proxy supplied in Plan 3.

## Manual smoke check

Start main.py with a free non-default GENLEDGE_BACKEND_PORT. With one cookie jar: me must return 401; login must return 200 and set a cookie; me must return that user; logout must return success; me must return 401. Stop the server afterward.
