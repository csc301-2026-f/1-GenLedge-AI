# Authentication implementation and verification

## Local setup (PowerShell)

From the repository root:

```powershell
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r src/backend/requirements-dev.txt
cd src/backend
..\..\.venv\Scripts\python.exe -m flask --app main auth-init-db
..\..\.venv\Scripts\python.exe -m flask --app main auth-create-user --email analyst@example.com --organization Acme --role Analyst
```

The command prompts twice for a password of 12–1024 characters. There are no
default accounts or public registration endpoints. Organization names select an
existing organization or create one. Only trusted administrators should run this CLI.
The default role is Analyst; Administrator can be selected explicitly.

Start the application using the existing start scripts with dependencies available
to their Python/Node commands, or start each service separately:

```powershell
# backend terminal, from src/backend
..\..\.venv\Scripts\python.exe main.py
# frontend terminal, from src/frontend
pnpm install
pnpm dev
```

Use http://127.0.0.1:5173 consistently. Vite proxies /api to Flask on port 5000,
so the browser uses same-origin cookies without permissive CORS.

Without DATABASE_URL, development uses src/backend/instance/auth.sqlite3 (ignored
by Git). Set a stable SECRET_KEY to keep sessions across backend restarts; otherwise
development uses a temporary random key and emits a warning. Never commit secrets.

## PostgreSQL and deployment

Before running Flask commands, set environment variables in the same terminal:

```powershell
$env:DATABASE_URL = 'postgresql+psycopg://USER:PASSWORD@HOST:5432/DATABASE'
$env:SECRET_KEY = '<random secret from your secret manager>'
$env:APP_ENV = 'production'
```

Use HTTPS in production. Production requires DATABASE_URL and SECRET_KEY and uses
Secure, HttpOnly, SameSite=Lax cookies. Serve /api under the same origin as the UI;
the Vite proxy is for development only. Do not deploy the debug development server.
auth-init-db creates missing auth tables; it is not a schema migration system.
Subsequent schema changes need reviewed database migrations.

## API and session behavior

- GET /api/auth/csrf returns csrfToken and establishes a signed cookie.
- POST /api/auth/login accepts email, password, rememberMe (boolean, optional).
- GET /api/auth/me returns user or 401.
- POST /api/auth/logout deletes the database session and clears the cookie.
- All auth POSTs require X-CSRF-Token from /csrf; successful login rotates it.
- User responses contain id, email, role, organizationId; never password hashes.
- Normal sessions use a browser session cookie with a 12-hour server-side limit.
  Browser session restoration may retain session cookies after browser restart.
- Remember me uses a persistent cookie and a fixed 14-day server-side limit.
- The cookie holds a random bearer token; the database stores its SHA-256 hash.
  Expired sessions and disabled accounts cannot access /me. Relogin revokes the
  previous session in that browser. Logout invalidates copied cookies too.
- Passwords use Werkzeug salted password hashing and verification.

Other feature APIs must apply login_required and require_organization(resource.organization_id)
from app.auth.service. Obtain the organization from the stored resource, not only
from a client-supplied field. g.user contains the authenticated identity. Role policy
for other modules is not implemented by this login module.

## Verification

```powershell
# from src/backend
..\..\.venv\Scripts\python.exe -m pytest tests
# from src/frontend
pnpm exec tsc --noEmit
pnpm build
```

Manual smoke test: initialize the DB and provision an account; wrong passwords
must show an error; correct credentials open Sources; refreshing restores login;
logout returns to Sign In and refresh stays signed out. Check Remember me for a
persistent cookie. Missing or incorrect CSRF tokens must return 403.

Production follow-up: configure shared login rate limiting at the gateway or in
the application before public exposure; add password reset/account administration,
auditing and versioned schema migrations when their requirements are agreed.
No PostgreSQL deployment or production credentials are provisioned by this change.
