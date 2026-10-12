# Authentication API

The connected frontend calls these Flask routes through Vite's `/api` proxy.
The standalone demo does not use this API. See `doc/auth-implementation.md` for
database setup, account provisioning, session limits, and production notes.

| Request | Result |
| --- | --- |
| `GET /api/auth/csrf` | 200 with `csrfToken`; establishes a signed session cookie |
| `POST /api/auth/login` with `email`, `password`, optional boolean `rememberMe` | 200 with `user`; 400 for invalid input; 401 for invalid credentials |
| `GET /api/auth/me` | 200 with `user`; 401 without an active session |
| `POST /api/auth/logout` | 204; revokes the current database session |

POST requests require the `X-CSRF-Token` header from `/csrf` and return 403 when
it is absent or invalid. Error responses use `{"error":"message"}`. The user
object contains `id`, `email`, `role`, and `organizationId`. Password hashes are
never returned. The backend checks a hashed password and stores a hash of the
session token in the database so logout can revoke a copied cookie.

`GENLEDGE_BACKEND_PORT` changes the development backend listener (default
5000). The Vite proxy targets port 5000, so keep that default when using the
full-stack launcher. `SECRET_KEY`, `HOST`, `PORT`, `DATABASE`, `USER`,
`PASSWORD`, and `APP_ENV` configure
authentication; see `doc/auth-implementation.md`.
