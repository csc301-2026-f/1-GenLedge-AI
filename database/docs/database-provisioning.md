# PostgreSQL Database Provisioning and Verification

## 1. Purpose and Scope

This document describes how developer and integration PostgreSQL accounts were provisioned on the CSC301 GenLedge Raspberry Pi test server, and how their permissions were verified.

The Raspberry Pi is also a personal server. Team members receive **PostgreSQL credentials only**, not Ubuntu SSH, `sudo`, or Docker administration access.

**Verified scope:** local PostgreSQL role/database creation, credential authentication, SQL read/write, ownership, and database-level connection isolation. **Not yet verified:** remote team connectivity, independent backups and restoration.

## 2. Environment and Connection

| Setting | Value |
|---|---|
| Host | Raspberry Pi 5, Ubuntu Server 24.04 LTS (ARM64) |
| Host administrator | `piadmin` |
| Deployment directory | `/srv/genledge/postgres` |
| PostgreSQL image | `postgres:17-alpine` |
| Docker Compose project | `genledge-db` |
| Container service | `postgres` |
| PostgreSQL administrator | `postgres` (database superuser; not a shared team account) |
| Host port binding | `127.0.0.1:5432:5432` (local-only) |
| Persistent data | Docker named volume `genledge-db_postgres_data` |

From the Raspberry Pi Ubuntu shell:

```bash
cd /srv/genledge/postgres
sudo docker compose ps
sudo docker compose exec postgres psql -U postgres -d postgres
```

**Expected:** the container reports a healthy state and `psql` displays `postgres=#`. This uses a local in-container administrator connection, not a test of team password authentication.

**Result:** **PASS — owner confirmed.**

## 3. Provisioned Roles and Databases

| Login role | Database | Database owner | Result |
|---|---|---|---|
| `daniel` | `daniel` | `daniel` | PASS |
| `likunyu2` | `likunyu2` | `likunyu2` | PASS |
| `jeff06` | `jeff06` | `jeff06` | PASS |
| `lvlvhu` | `lvlvhu` | `lvlvhu` | PASS |
| `steven` | `steven` | `steven` | PASS |
| `xiran` | `xiran` | `xiran` | PASS |
| `integration` | `dev` | `integration` | PASS |

All seven roles and seven corresponding databases have been reported as created and verified. The expected names reflect the actual accounts supplied during setup, rather than an earlier provisional roster.

## 4. Manual Provisioning Procedure

Run the following steps **once per new role** as the PostgreSQL administrator. Replace `username` with a real role name. For `integration`, use `dev` as its database name.

### 4.1 Check for existing objects

Within `postgres=#`:

```sql
SELECT rolname FROM pg_roles WHERE rolname = 'username';
SELECT datname FROM pg_database WHERE datname = 'username';
```

**Expected for a new ordinary user:** both return `(0 rows)`. For `integration`, check `datname = 'dev'`. If an object already exists, inspect it instead of recreating or deleting it.

### 4.2 Create a restricted login role

```sql
CREATE ROLE username
WITH LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOREPLICATION;
```

**Expected:** `CREATE ROLE`.

The role is allowed to log in but is not a PostgreSQL superuser and cannot create new databases, administer roles, or use replication privileges. `NOINHERIT` is an additional control, not a replacement for database privilege auditing.

### 4.3 Assign a unique password interactively

Within `psql` (this is a `psql` meta-command, not SQL):

```text
\password username
```

**Expected:** prompts for the password and confirmation; no plaintext password is printed. Generate a unique strong password for each role, store it in an approved password manager, and share it only with the intended recipient. Do not place passwords in SQL statements, shell histories, Markdown, or Git.

For optional password generation from a separate Ubuntu terminal:

```bash
python3 -c 'import secrets; print(secrets.token_urlsafe(32))'
```

### 4.4 Create the owned database

For matching role/database names:

```sql
CREATE DATABASE username OWNER username TEMPLATE template0;
REVOKE ALL ON DATABASE username FROM PUBLIC;
```

**Expected:** `CREATE DATABASE` followed by `REVOKE`.

**Important:** `TEMPLATE template0` is part of the **same `CREATE DATABASE` statement**. Do not terminate the statement with `;` before `TEMPLATE`. Do not remove or recreate the built-in `template0` or `template1` databases.

For the integration role, use the different database name:

```sql
CREATE DATABASE dev OWNER integration TEMPLATE template0;
REVOKE ALL ON DATABASE dev FROM PUBLIC;
```

**Expected:** `CREATE DATABASE` followed by `REVOKE`.

### 4.5 Restrict public access to default databases

This was applied during the development-role setup on this fresh test instance:

```sql
REVOKE ALL ON DATABASE postgres FROM PUBLIC;
REVOKE ALL ON DATABASE template1 FROM PUBLIC;
```

**Expected:** `REVOKE` for each statement. These commands affect connections using default `PUBLIC` privileges; verify compatibility before applying them to an existing shared deployment. The `postgres` superuser retains administrative access.

**Result for sections 4.2–4.5:** **PASS — owner confirmed** for the completed target accounts and database configurations.

## 5. Role Attribute Verification

Run as `postgres`:

```sql
SELECT
    rolname,
    rolcanlogin AS login,
    rolsuper AS superuser,
    rolcreatedb AS create_db,
    rolcreaterole AS create_role,
    rolreplication AS replication
FROM pg_roles
WHERE rolname IN (
    'daniel', 'likunyu2', 'jeff06', 'lvlvhu',
    'steven', 'xiran', 'integration'
)
ORDER BY rolname;
```

**Expected:** exactly seven rows; for **every** role, `login = t` and `superuser = create_db = create_role = replication = f`.

**Result:** **PASS — owner confirmed.**

## 6. Database Ownership Verification

```sql
SELECT datname, pg_get_userbyid(datdba) AS owner
FROM pg_database
WHERE datname IN (
    'daniel', 'likunyu2', 'jeff06', 'lvlvhu',
    'steven', 'xiran', 'dev'
)
ORDER BY datname;
```

**Expected:** exactly seven rows matching the role-to-database mapping in Section 3; the `dev` database is owned by `integration`.

**Result:** **PASS — owner confirmed.**

## 7. Complete Database CONNECT Permission Audit

This read-only query compares the effective CONNECT privilege for **every listed role against all databases that permit connections** to the intended one-database-per-role policy.

```sql
WITH expected_access(username, allowed_database) AS (
    VALUES
        ('daniel', 'daniel'),
        ('likunyu2', 'likunyu2'),
        ('jeff06', 'jeff06'),
        ('lvlvhu', 'lvlvhu'),
        ('steven', 'steven'),
        ('xiran', 'xiran'),
        ('integration', 'dev')
), audit AS (
    SELECT
        e.username,
        d.datname AS database,
        has_database_privilege(e.username, d.oid, 'CONNECT') AS actual,
        (d.datname = e.allowed_database) AS expected
    FROM expected_access e
    JOIN pg_roles r ON r.rolname = e.username
    CROSS JOIN pg_database d
    WHERE d.datallowconn = true
)
SELECT *
FROM audit
WHERE actual IS DISTINCT FROM expected
ORDER BY username, database;
```

**Expected:** `(0 rows)` (no access mismatches). Each team role has CONNECT permission only for its designated database; no developer can connect to `postgres`, `template1`, or another developer's database.

**Result:** **PASS — owner confirmed.**

**Scope note:** this query skips roles that do not exist, so role presence must also be checked in Section 5. It omits databases with `datallowconn = false`, such as `template0` by default. Database CONNECT permissions do not imply freedom to access other databases' tables or the Ubuntu host.

### 7.1 Verify the built-in templates remain intact

```sql
SELECT datname, datistemplate, datallowconn
FROM pg_database
WHERE datname IN ('template0', 'template1', 'postgres')
ORDER BY datname;
```

**Expected on a normal PostgreSQL installation:** `template0` is a template with `datallowconn = f`; `template1` is a template; `postgres` is the default maintenance database. **Do not delete built-in template databases.**

### 7.2 Check PUBLIC CONNECT privileges

```sql
SELECT
    datname,
    COALESCE((
        SELECT bool_or(x.grantee = 0 AND x.privilege_type = 'CONNECT')
        FROM aclexplode(COALESCE(datacl, acldefault('d', datdba))) AS x
    ), false) AS public_connect
FROM pg_database
WHERE datallowconn = true
ORDER BY datname;
```

**Expected:** `public_connect = f` for every database that should be isolated, including `postgres`, `template1`, the developer databases, and `dev`.

**Result:** **PASS — owner confirmed.**

## 8. Unexpected Role Membership Audit

```sql
SELECT
    parent.rolname AS granted_role,
    child.rolname AS member_role
FROM pg_auth_members m
JOIN pg_roles parent ON parent.oid = m.roleid
JOIN pg_roles child ON child.oid = m.member
WHERE child.rolname IN (
    'daniel', 'likunyu2', 'jeff06', 'lvlvhu',
    'steven', 'xiran', 'integration'
);
```

**Expected:** `(0 rows)` under this project's standalone-role design.

**Result:** **PASS — owner confirmed.**

## 9. Real Password Authentication and SQL Permission Tests

The following commands run from the Raspberry Pi Ubuntu shell in `/srv/genledge/postgres`, **not** inside the PostgreSQL administrator's `psql` session.

### 9.1 Authorized login

Example for `likunyu2`:

```bash
sudo docker compose exec postgres \
  psql -h 127.0.0.1 -U likunyu2 -d likunyu2 -W
```

**Expected:** accepts the correct password and opens a `psql` session (normally `likunyu2=>`).

In that session:

```sql
SELECT current_user, current_database();
```

**Expected:** `likunyu2 | likunyu2`.

For `integration`:

```bash
sudo docker compose exec postgres \
  psql -h 127.0.0.1 -U integration -d dev -W
```

**Expected:** successful login; `SELECT current_user, current_database();` returns `integration | dev`.

**Result:** **PASS — owner confirmed** for the team accounts and integration account, including actual password-based local TCP connections.

### 9.2 Create, read, write, and remove an owned table

Run while logged in as the account being tested, in **its own** database:

```sql
CREATE TABLE public.permission_test (
    id INTEGER PRIMARY KEY,
    message TEXT NOT NULL
);
INSERT INTO public.permission_test VALUES (1, 'Permission test');
SELECT * FROM public.permission_test;
DROP TABLE public.permission_test;
```

**Expected:** `CREATE TABLE`, `INSERT 0 1`, one matching row, then `DROP TABLE`.

**Result:** **PASS — owner confirmed** for the tested developer and integration connections.

### 9.3 Denied cross-database connection

After exiting `psql` with `\q`, try a different role's database. Example:

```bash
sudo docker compose exec postgres \
  psql -h 127.0.0.1 -U likunyu2 -d jeff06 -W
```

Use the correct password for `likunyu2`.

**Expected:** connection rejected with an error such as `FATAL: permission denied for database "jeff06"`.

Integration isolation examples:

```bash
sudo docker compose exec postgres \
  psql -h 127.0.0.1 -U integration -d daniel -W

sudo docker compose exec postgres \
  psql -h 127.0.0.1 -U daniel -d dev -W
```

**Expected:** both attempts rejected despite correct passwords.

**Result:** **PASS — owner confirmed.**

## 10. Security Boundaries and Credential Handling

- PostgreSQL `postgres` remains the administrative superuser and is **not shared** with the team.
- Team PostgreSQL roles are **not Linux user accounts** and do not grant shell, SSH, `sudo`, or Docker privileges.
- Each team role has a distinct, strong password. Passwords and private SSH keys are excluded from Git and project documentation.
- Credential delivery to each team member should use a private, trusted channel or approved password manager, not a public chat or repository issue.
- PostgreSQL is currently published on `127.0.0.1:5432` only. Team access from other devices has **not** yet been opened or verified.
- The database data volume provides persistence, not independent backup/recovery.
- Changes to privileges should be followed by both catalog-based tests and real authentication tests.

## 11. Verification Summary

| Check | Expected result | Verified status |
|---|---|---|
| All seven login roles exist | Seven target roles found | PASS — owner confirmed |
| All seven databases exist | Seven target databases found | PASS — owner confirmed |
| Restricted role flags | LOGIN enabled; privileged flags disabled | PASS — owner confirmed |
| Database ownership | Owner matches role; `dev` owned by `integration` | PASS — owner confirmed |
| PUBLIC CONNECT restriction | No unintended PUBLIC grants | PASS — owner confirmed |
| Role membership | No unintended memberships | PASS — owner confirmed |
| Full CONNECT permission audit | `(0 rows)` of mismatches | PASS — owner confirmed |
| Authorized local TCP login | Login with correct account password succeeds | PASS — owner confirmed |
| SQL create/insert/select/drop | All operations succeed in own database | PASS — owner confirmed |
| Unauthorized database login | Rejected | PASS — owner confirmed |
| Restricted remote team connectivity | Authorized network-only access | NOT YET TESTED |
| Independent backup and restore | Successful restoration from backup | NOT YET TESTED |

All completed checks above are recorded on the basis of the server owner's confirmation of the expected outcomes; full raw terminal transcripts are not included in this document.

## 12. Operations and Next Steps

1. **Secure team connectivity:** choose a private network access method (for example, Tailscale with narrowly scoped device/port permissions). Do not expose TCP 5432 publicly or grant team SSH access.
2. **Client-side validation:** test each authorized member's connection from their own machine, verify TLS/network settings as appropriate, and re-test forbidden connections.
3. **Credential management:** distribute only the relevant account credential to each member and establish a rotation/revocation procedure.
4. **Backup and restore:** produce independent PostgreSQL backups and test a full restore before storing important project data.
5. **Documentation:** add connection and recovery guides, keeping secrets and private network details out of Git.

