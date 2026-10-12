# Raspberry Pi Host Deployment

## 1. Purpose and scope

This document records the initial host deployment for a team PostgreSQL **development/test** service on a primarily personal Raspberry Pi. Team members will later access authorized databases, **not** the Ubuntu administrative account.

**Current status (2026-10-11):** Host initialization, Docker Engine, PostgreSQL 17 deployment, database persistence, individual database provisioning, and local-network TCP access are complete. PostgreSQL TLS is configured; DBeaver has successfully connected from Windows to the Pi LAN address. Public domain access remains unverified/unsuccessful, and remote superuser login is still possible. Sections 3–10 document the original deployment stages; later changes are recorded in Sections 11–14.

Actual host output was not archived for every check. The expected examples below are **acceptance criteria**, not fabricated copies of terminal output.

## 2. Host inventory

| Item | Configuration |
|---|---|
| Hardware | Raspberry Pi 5 (8 GB) |
| OS | Ubuntu Server 24.04 LTS (64-bit) |
| Hostname | `pi5-server` |
| Administrator | `piadmin` (personal account only) |
| CPU architecture | `aarch64` / ARM64 |
| Connectivity | Wi-Fi, local network; remote admin over SSH |
| Client | Windows PowerShell / MobaXterm Personal 23.4 |
| SSH key type | Ed25519 |
| Docker / PostgreSQL | Docker Engine + Compose; `postgres:17-alpine` (deployed; see Sections 8–13) |

## 3. Installation: Ubuntu Server and first boot

### Goal
Install Ubuntu 24.04 LTS on the device and initialize one personal administrator account.

### Setup (Windows + Raspberry Pi Imager)
1. In Raspberry Pi Imager select **Raspberry Pi 5**, **Ubuntu Server 24.04 LTS (64-bit)**, and the intended microSD/SSD. **Writing erases the selected device.**
2. Configure hostname `pi5-server`, Ubuntu username `piadmin`, a strong private account password, Wi-Fi, and **SSH public-key authentication**.
3. Write and verify the image, insert the storage device into the Pi, power on and allow cloud-init to finish.
4. Do **not** publish the administrator password or private SSH key in the repository.

### SSH key setup (Windows PowerShell)
```powershell
New-Item -ItemType Directory -Force -Path "$HOME\.ssh"
ssh-keygen -t ed25519 -f "$HOME\.ssh\pi5_admin" -C "pi5-admin"
Get-Content "$HOME\.ssh\pi5_admin.pub"
```

Use the contents of **`pi5_admin.pub`** in Imager; keep `pi5_admin` (without `.pub`) on the personal Windows computer. If the files already exist, **do not overwrite** them. A strong private-key passphrase is recommended.

### Verification (Raspberry Pi terminal)
```bash
cloud-init status --wait
cloud-init status --long
whoami
hostname
cat /etc/os-release
uname -m
```

**Expected:** cloud-init `status: done` and no unaddressed errors; `piadmin`; `pi5-server`; Ubuntu `VERSION_ID="24.04"`; architecture `aarch64`.

**Result:** **PASS** (user confirmed all host deployment tests passed; `status: done` was independently reported earlier).

## 4. Network and initial remote administration

### Setup
- Configure the Pi and Windows PC on a reachable local Wi-Fi network (avoid guest/client-isolated Wi-Fi).
- Enable SSH with the public key during image customization.
- Do not configure router port-forwarding for SSH or PostgreSQL.

### Verification (Windows PowerShell)
```powershell
ping pi5-server.local
Test-NetConnection pi5-server.local -Port 22
ssh -i "$HOME\.ssh\pi5_admin" piadmin@pi5-server.local
```

**Expected:** hostname resolves and is reachable on the local network; `TcpTestSucceeded : True`; SSH login yields a `piadmin@pi5-server` shell. ICMP echo may be disabled on some networks, so a failed ping alone does not establish SSH failure.

### Verification (Pi)
```bash
ip -br addr
ip route
getent hosts ubuntu.com
```

**Expected:** Wi-Fi has an appropriate assigned address; an appropriate default route exists; DNS resolves `ubuntu.com`.

**Result:** **PASS** (the owner reported SSH login success and all remaining checks passed; port 22 was confirmed reachable earlier). Avoid committing full personal IP addresses to the team repo.

## 5. System update and hardware verification

### Setup (Pi)
```bash
sudo apt update
sudo apt full-upgrade -y
sudo apt autoremove -y
```

Inspect removals before accepting unexpected changes. Reboot if required, then reconnect through SSH.

### Verification (Pi)
```bash
nproc
free -h
df -h /
lsblk -o NAME,SIZE,TYPE,MOUNTPOINTS
cat /etc/os-release
uname -m
```

**Expected:** 4 CPU cores; approximately 8 GB physical memory (reported usable memory may be lower); sufficient free space for the planned database; expected storage device/root mount; Ubuntu 24.04, `aarch64`.

**Result:** **PASS** (owner-reported). No exact storage capacity or free-space figures have been recorded in this document.

## 6. Basic utilities

### Setup (Pi)
```bash
sudo apt install -y git curl wget nano htop ca-certificates openssl
```

### Verification (Pi)
```bash
for cmd in git curl wget nano htop openssl; do command -v "$cmd" || exit 1; done
```

**Expected:** paths for all requested executables and a zero exit status. `ca-certificates` is a package of trust certificates, not a similarly named command.

**Result:** **PASS** (owner-reported).

## 7. Deployment verification summary

| ID | Check | Expected result | Status |
|---|---|---|---|
| D-01 | User, hostname, OS, architecture | `piadmin`, `pi5-server`, 24.04, `aarch64` | PASS — owner confirmed |
| D-02 | Cloud-init | `status: done` | PASS — observed |
| D-03 | CPU, memory, root disk | 4 cores, ~8 GB, usable storage | PASS — owner confirmed |
| D-04 | Network, DNS, SSH | route/DNS work, TCP 22 reachable, SSH login succeeds | PASS — owner confirmed |
| D-05 | Package update and utilities | Update/install commands succeed; binaries available | PASS — owner confirmed |

## 8. Docker Environment Setup

### 8.1 Objective

Install and verify Docker Engine and Docker Compose on the Raspberry Pi 5 to support containerized PostgreSQL deployment.

### 8.2 Environment

- Operating System: Ubuntu Server 24.04 LTS
- Architecture: ARM64
- Administrator: `piadmin`
- Installation method: Official Docker APT repository
- Initial state: Docker not installed

### 8.3 Installation

**Step 1 — Install prerequisites**

```bash
sudo apt update
sudo apt install -y ca-certificates curl
sudo install -m 0755 -d /etc/apt/keyrings
```

**Step 2 — Configure Docker's GPG signing key**

```bash
sudo curl -fsSL https://download.docker.com/linux/ubuntu/gpg \
  -o /etc/apt/keyrings/docker.asc

sudo chmod a+r /etc/apt/keyrings/docker.asc
```

**Step 3 — Add the official Docker repository**

```bash
sudo tee /etc/apt/sources.list.d/docker.sources > /dev/null <<EOF
Types: deb
URIs: https://download.docker.com/linux/ubuntu
Suites: $(. /etc/os-release && echo "${UBUNTU_CODENAME:-$VERSION_CODENAME}")
Components: stable
Architectures: $(dpkg --print-architecture)
Signed-By: /etc/apt/keyrings/docker.asc
EOF
```

**Step 4 — Install Docker Engine and Compose**

```bash
sudo apt update

sudo apt install -y \
  docker-ce \
  docker-ce-cli \
  containerd.io \
  docker-buildx-plugin \
  docker-compose-plugin
```

### 8.4 Verification

**Verify Docker Engine**

```bash
sudo docker --version
```

Expected: A valid Docker Engine version is displayed.

Result: **PASS — Owner confirmed.**

**Verify Docker Compose**

```bash
sudo docker compose version
```

Expected: A valid Docker Compose v2 version is displayed.

Result: **PASS — Owner confirmed.**

**Verify Docker service**

```bash
sudo systemctl is-active docker
sudo systemctl is-enabled docker
```

Expected:

```text
active
enabled
```

Result: **PASS — Owner confirmed.**

**Verify image pulling and container execution**

```bash
sudo docker run --rm hello-world
```

Expected output contains:

```text
Hello from Docker!
```

Result: **PASS — Owner confirmed.**

### 8.5 Deployment Status

- [x] Official Docker repository configured
- [x] Docker Engine installed
- [x] Docker Compose plugin installed
- [x] Docker service active
- [x] Docker service enabled at startup
- [x] Docker Hub image pull successful
- [x] Hello-world container executed successfully

## 9. PostgreSQL Container Deployment

### 9.1 Objective

Deploy PostgreSQL as a Docker container on the Raspberry Pi 5.

The initial deployment must provide:

- A fixed PostgreSQL major version.
- Persistent database storage using a Docker named volume.
- Administrator credentials stored outside Git.
- Local-only network access.
- Automatic container restart.
- PostgreSQL service health monitoring.

Remote team access is not enabled during this phase.

### 9.2 Deployment Environment

| Component | Configuration |
|---|---|
| Host | Raspberry Pi 5 |
| OS | Ubuntu Server 24.04 LTS (ARM64) |
| Container Runtime | Docker Engine |
| Container Orchestration | Docker Compose |
| Image | `postgres:17-alpine` |
| Deployment Directory | `/srv/genledge/postgres` |
| Compose Project | `genledge-db` |
| Database Port | `127.0.0.1:5432` |
| Volume | `postgres_data` |

### 9.3 Deployment Directory

**Setup**

```bash
sudo mkdir -p /srv/genledge/postgres
sudo chown piadmin:piadmin /srv/genledge/postgres
chmod 700 /srv/genledge/postgres

cd /srv/genledge/postgres
```

**Verification**

```bash
pwd
stat -c '%a %U %G %n' /srv/genledge/postgres
```

**Expected result**

```text
/srv/genledge/postgres
700 piadmin piadmin /srv/genledge/postgres
```

**Status:** PASS — Owner confirmed.

### 9.4 PostgreSQL Administrator Credentials

A random administrator password was generated using Python's `secrets` module and stored in a protected `.env` file.

**Setup**

```bash
cd /srv/genledge/postgres
umask 077

python3 - <<'PY'
import secrets
from pathlib import Path

password = secrets.token_urlsafe(32)

with open(".env", "x") as f:
    f.write(f"POSTGRES_PASSWORD={password}\n")

Path(".env").chmod(0o600)

print("Password file created successfully.")
PY
```

The exclusive file creation mode prevents accidentally overwriting an existing password.

**Verification**

```bash
stat -c '%a %U %G %n' .env
grep -q '^POSTGRES_PASSWORD=.' .env && echo "Password configured"
```

**Expected result**

```text
600 piadmin piadmin .env
Password configured
```

**Status:** PASS — Owner confirmed.

The actual password must never be committed to Git, included in documentation, or shared in logs.

### 9.5 Docker Compose Configuration

**Setup**

From a checkout of this repository on the Raspberry Pi, copy the tracked
configuration file to the server deployment directory:

```bash
sudo install -m 600 -o piadmin -g piadmin \
  database/compose.yaml /srv/genledge/postgres/compose.yaml
cd /srv/genledge/postgres
```

The tracked `database/compose.yaml` contains the following configuration:

```yaml
name: genledge-db

services:
  postgres:
    image: postgres:17-alpine
    restart: unless-stopped

    environment:
      POSTGRES_USER: postgres
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD:?POSTGRES_PASSWORD is required}
      POSTGRES_DB: postgres

    ports:
      - "127.0.0.1:5432:5432"

    volumes:
      - postgres_data:/var/lib/postgresql/data

    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U postgres -d postgres"]
      interval: 10s
      timeout: 5s
      retries: 5
      start_period: 30s

volumes:
  postgres_data:
```

**Verification**

```bash
cd /srv/genledge/postgres
sudo docker compose config --quiet
echo $?
```

**Expected result**

```text
0
```

Verify the network binding:

```bash
grep -F '127.0.0.1:5432:5432' compose.yaml
```

**Expected result**

```text
      - "127.0.0.1:5432:5432"
```

**Status:** PASS — Owner confirmed.

Do not share the unredacted output of `docker compose config`, as it may contain resolved environment variables and sensitive credentials.

### 9.6 Container Startup

**Setup**

```bash
cd /srv/genledge/postgres
sudo docker compose up -d
```

Docker Compose downloads the PostgreSQL image, creates the configured named volume, and starts the container.

**Verification**

```bash
sudo docker compose ps
```

**Expected result**

The PostgreSQL container is running and reaches the `healthy` state.

**Status:** PASS — Owner confirmed.

### 9.7 Health Verification

**Verification**

```bash
sudo docker compose exec -T postgres \
  pg_isready -U postgres -d postgres
```

**Expected result**

```text
/var/run/postgresql:5432 - accepting connections
```

**Status:** PASS — Owner confirmed.

This confirms PostgreSQL is accepting connection attempts. Authentication and SQL read/write permissions require separate verification.

### 9.8 Network Binding Verification

**Verification**

```bash
sudo ss -ltnp | grep ':5432 '
```

**Expected result**

PostgreSQL is published on:

```text
127.0.0.1:5432
```

It must not be published on all host interfaces:

```text
0.0.0.0:5432
[::]:5432
```

**Status:** PASS — Owner confirmed.

### 9.9 Persistent Storage Configuration

The PostgreSQL data directory is backed by a Docker named volume:

```yaml
volumes:
  - postgres_data:/var/lib/postgresql/data
```

**Verification**

```bash
sudo docker volume ls
```

**Expected result**

The volume list includes:

```text
genledge-db_postgres_data
```

This verifies that the named volume exists. Persistence across container recreation will be tested separately.

**Status:** Volume configured; data persistence test pending.

### 9.10 Deployment Verification Summary

| Test | Expected Result | Status |
|---|---|---|
| Deployment directory | Owner `piadmin`, permission `700` | PASS |
| Administrator password file | Exists, permission `600` | PASS |
| Compose configuration | Valid configuration | PASS |
| Container startup | PostgreSQL container running | PASS |
| Health check | `healthy` / accepting connections | PASS |
| Network binding | Localhost only | PASS |
| Docker volume | Persistent volume configured | PASS |
| SQL read/write | Successfully execute SQL | Pending |
| Container recreation persistence | Data survives recreation | Pending |
| Developer databases | Separate developer databases created | Pending |
| Database role isolation | Unauthorized access rejected | Pending |

### 9.11 Next Steps

- [ ] Verify SQL connectivity and read/write operations.
- [ ] Verify data persistence after container recreation.
- [ ] Create separate developer databases and roles.
- [ ] Configure the shared integration database.
- [ ] Verify database-level permission isolation.
- [ ] Configure restricted remote access for authorized team members.

## 10. PostgreSQL Functional Verification

### 10.1 Objective

Verify that the PostgreSQL instance supports SQL read/write operations and preserves database contents across container recreation.

### 10.2 SQL Connection

**Command**

```bash
cd /srv/genledge/postgres
sudo docker compose exec postgres psql -U postgres -d postgres
```

**Expected result**

```text
postgres=#
```

**Status:** PASS — Owner confirmed.

This test uses a local connection inside the PostgreSQL container. External TCP password authentication is not covered by this test.

### 10.3 Create a Test Table

**SQL**

```sql
CREATE TABLE public.deployment_verification (
    id INTEGER PRIMARY KEY,
    message TEXT NOT NULL
);
```

**Expected result**

```text
CREATE TABLE
```

**Status:** PASS — Owner confirmed.

### 10.4 Insert Test Data

**SQL**

```sql
INSERT INTO public.deployment_verification (id, message)
VALUES (1, 'PostgreSQL persistence test');
```

**Expected result**

```text
INSERT 0 1
```

**Status:** PASS — Owner confirmed.

### 10.5 Verify SQL Read Operations

**SQL**

```sql
SELECT * FROM public.deployment_verification;
```

**Expected result**

```text
 id |            message
----+------------------------------
  1 | PostgreSQL persistence test
(1 row)
```

**Status:** PASS — Owner confirmed.

Exit the SQL console using `\q`.

### 10.6 Container Recreation

**Commands**

```bash
cd /srv/genledge/postgres

sudo docker compose down
sudo docker compose up -d
sudo docker compose ps
```

**Expected result**

The PostgreSQL container is recreated and returns to a healthy running state.

Important: `docker compose down` preserves named volumes by default. Do not use `docker compose down -v`, as this removes managed volumes.

**Status:** PASS — Owner confirmed.

### 10.7 Data Persistence Verification

**Command**

```bash
sudo docker compose exec -T postgres \
  psql -U postgres -d postgres \
  -c "SELECT * FROM public.deployment_verification;"
```

**Expected result**

```text
 id |            message
----+------------------------------
  1 | PostgreSQL persistence test
(1 row)
```

The original record must remain accessible after container recreation.

**Status:** PASS — Owner confirmed.

### 10.8 Test Data Cleanup

**Command**

```bash
sudo docker compose exec -T postgres \
  psql -U postgres -d postgres \
  -c "DROP TABLE public.deployment_verification;"
```

**Expected result**

```text
DROP TABLE
```

**Status:** PASS — Owner confirmed.

### 10.9 Verification Summary

| Test | Expected Result | Status |
|---|---|---|
| Local SQL connection | Connection successful | PASS |
| Table creation | `CREATE TABLE` | PASS |
| Insert operation | `INSERT 0 1` | PASS |
| Select operation | Expected record returned | PASS |
| Container recreation | Container running and healthy | PASS |
| Data persistence | Record retained after recreation | PASS |
| Cleanup | `DROP TABLE` | PASS |

All Phase 5 verification tests passed, as confirmed by the server owner.

### 10.10 Limitations

The following have not yet been verified:

- Authentication using individual developer credentials.
- Database-level authorization and isolation.
- Remote database connectivity.
- Backup and restoration from an independent backup.

Container volume persistence is not equivalent to a verified backup and recovery mechanism.

### 10.11 Next Steps

- [ ] Provision individual developer databases and roles.
- [ ] Provision the shared integration database.
- [ ] Configure minimum required privileges.
- [ ] Verify authorized database access.
- [ ] Verify unauthorized cross-database access is rejected.
- [ ] Prepare repeatable provisioning scripts.
- [ ] Configure secure remote team connectivity.

## 11. Deployment progression after initial verification

The earlier sections intentionally retain the **original** local-only deployment configuration and stage-specific acceptance results. Those earlier port bindings, pending items, and scope statements are historical, not a description of the current deployment. Subsequent implementation and verification are recorded below. Do not retroactively mark an earlier test as failed because the intended configuration later changed.

### 11.1 Updated PostgreSQL provisioning

**Objective**

Provision independent development databases and roles without granting Ubuntu SSH or Docker privileges to team members.

**Implementation**

- Individual role/database pairs: `daniel/daniel`, `likunyu2/likunyu2`, `jeff06/jeff06`, `lvlvhu/lvlvhu`, `steven/steven`, and `xiran/xiran`.
- Shared integration role/database pair: `integration/dev`.
- `postgres` is reserved for local PostgreSQL administration.
- Developer roles were configured without superuser, database creation, role creation, or replication privileges; individual databases are owned by their intended roles.
- Access to unrelated databases was restricted. Database privilege/membership audits and selected login tests were reported successful during provisioning.
- Database-only identities do **not** provide Ubuntu login, SSH, sudo, or Docker control.

**Verification**

```bash
cd /srv/genledge/postgres
sudo docker compose exec -T postgres \
  psql -U postgres -d postgres -c "\du"
sudo docker compose exec -T postgres \
  psql -U postgres -d postgres -c "SELECT datname, pg_get_userbyid(datdba) AS owner FROM pg_database ORDER BY datname;"
```

**Expected result:** All seven named non-admin roles exist and own their respective development databases; sensitive credentials are not displayed.

**Status:** **PASS — owner-reported provisioning and isolation tests.** Additional current DBeaver testing for `integration` is still pending.

## 12. Remote connectivity and TLS configuration

### 12.1 Objective

Enable encrypted PostgreSQL client connections for the development team while retaining personal Ubuntu administrator access separately. This section describes **local-network TCP access completed so far**, not completed internet exposure.

### 12.2 Current environment

| Component | Current configuration |
|---|---|
| Image | `postgres:17-alpine` |
| Compose deployment | `/srv/genledge/postgres/compose.yaml` |
| LAN address observed | `192.168.30.43` (verify before reuse; DHCP may change) |
| Docker TCP publishing | `192.168.30.43:5432:5432` (replaced earlier localhost-only binding) |
| PostgreSQL listen address | `*` (reported configured) |
| TLS | `ssl=on`, minimum TLS 1.2 (reported configured) |
| Certificate hostname | `301db.dbestserv.com` |
| Certificate location (volume) | `/var/lib/postgresql/data/server.crt` |
| Private key location (volume) | `/var/lib/postgresql/data/server.key` |
| Database URL (LAN test) | `jdbc:postgresql://192.168.30.43:5432/dev?sslmode=require` |
| Intended public URL | `jdbc:postgresql://301db.dbestserv.com:5432/dev?sslmode=verify-full` (**not yet functional**) |

### 12.3 TLS certificate preparation

**Setup (Pi)**

A self-signed TLS certificate was generated for `301db.dbestserv.com` using OpenSSL. It was copied into the PostgreSQL named-volume-backed data directory and assigned to `postgres` inside the container.

**Verification**

```bash
cd /srv/genledge/postgres
sudo openssl x509 -in tls/server.crt -noout -subject -dates -ext subjectAltName
sudo docker compose exec -T postgres \
  stat -c '%a %U %G %n' \
  /var/lib/postgresql/data/server.crt \
  /var/lib/postgresql/data/server.key
```

**Expected result:** Certificate subject/SAN contains `DNS:301db.dbestserv.com`; `server.crt` is `644 postgres postgres` and `server.key` is `600 postgres postgres` within the container.

**Result:** **PASS — observed certificate metadata, certificate/private-key match, and container file permissions.** Container image did not include the `openssl` CLI; that error is not itself a TLS failure. Actual DBeaver session TLS remains to be verified with `pg_stat_ssl`.

### 12.4 PostgreSQL startup settings

**Current configuration (relevant portion of `compose.yaml`)**

```yaml
services:
  postgres:
    image: postgres:17-alpine
    ports:
      - "192.168.30.43:5432:5432"
    command:
      - postgres
      - -c
      - listen_addresses=*
      - -c
      - ssl=on
      - -c
      - ssl_cert_file=/var/lib/postgresql/data/server.crt
      - -c
      - ssl_key_file=/var/lib/postgresql/data/server.key
      - -c
      - ssl_min_protocol_version=TLSv1.2
      - -c
      - password_encryption=scram-sha-256
```

This is an excerpt; the actual file also retains the `environment`, healthcheck, and persistent volume from Section 9. `POSTGRES_PASSWORD` continues to be injected from a protected `.env` file.

**Verification**

```bash
cd /srv/genledge/postgres
sudo docker compose config --quiet
sudo docker compose ps
sudo docker compose exec -T postgres \
  psql -U postgres -d postgres -c "SHOW ssl;"
sudo docker compose exec -T postgres \
  psql -U postgres -d postgres -c "SHOW listen_addresses;"
```

**Expected result:** Valid Compose configuration, healthy PostgreSQL container, `ssl = on`, and `listen_addresses = *`.

**Status:** **Configured; running service and LAN reachability owner-confirmed.** Do not treat TLS certificate validation by a remote client as complete until the DBeaver verification below passes.

### 12.5 PostgreSQL host-based authentication (`pg_hba.conf`)

**Observed authentication rules (before any later, unverified edits):**

- Local Unix-socket and container-loopback rules used `trust`.
- Broad TCP rule: `host all all all scram-sha-256`.
- Existing broad `host` rule requires password authentication but **does not require TLS**.

A later attempt to restrict TCP access for the `postgres` superuser has **not passed verification**: the owner was still able to authenticate as `postgres` through DBeaver over the LAN.

**Verification**

```bash
sudo docker compose exec -T postgres \
  psql -U postgres -d postgres -c \
  "SELECT line_number, type, database, user_name, address, auth_method, error FROM pg_hba_file_rules ORDER BY line_number;"
```

**Expected result:** No parse errors, and any newly added refusal rules appear before broad authorizing rules. Separately test from DBeaver: remote `postgres` login must fail while ordinary developer login works.

**Status:** **OPEN SECURITY ISSUE** — remote `postgres` connection succeeded in the latest owner-reported test. Do not claim the restriction is active. Mandatory TLS remains deferred.

### 12.6 DBeaver LAN connection

**Setup (Windows)**

- PostgreSQL connection via host `192.168.30.43`, TCP port `5432`.
- No SSH tunnel and no VPN.
- For a normal developer test, choose database `dev` with role `integration` and SSL mode `require`.
- `sslmode=require` encrypts the connection but does not provide full hostname verification. The certificate was issued for `301db.dbestserv.com`, not the LAN IP.

**Verification (Windows PowerShell)**

```powershell
Test-NetConnection 192.168.30.43 -Port 5432
```

**Expected/observed:** `TcpTestSucceeded : True`.

**Verification (DBeaver SQL Editor; repeat as `integration` rather than `postgres`)**

```sql
SELECT current_user, current_database();
SELECT ssl, version, cipher
FROM pg_stat_ssl
WHERE pid = pg_backend_pid();
```

**Expected result:** `integration`, `dev`, and `ssl = true` with an accepted TLS version and nonempty cipher.

**Status:** **PARTIAL PASS** — DBeaver successfully connected to the Pi LAN endpoint using `postgres`. An `integration` DBeaver session and its actual TLS session attributes have **not yet been confirmed**.

## 13. Public domain connectivity (in progress)

### 13.1 Objective

Allow authorized development clients to use `301db.dbestserv.com:5432` without Tailscale or an SSH tunnel, subject to adequate network and database security controls.

### 13.2 Domain and network checks

- The Pi-reported outward-facing IPv4 and the DNS A record for `301db.dbestserv.com` were reported to match.
- The router WAN/public address match was also reported confirmed.
- The specific external TCP 5432 router-forwarding rule has not been independently verified as active and correct.
- A DBeaver connection attempt to `301db.dbestserv.com:5432` failed with `Connection refused: getsockopt`.
- DBeaver LAN connection to `192.168.30.43:5432` subsequently succeeded.
- Public connectivity must be tested from a genuinely external network; NAT loopback behavior can affect tests from home Wi-Fi.

**Verification (Windows, external network such as mobile hotspot)**

```powershell
Resolve-DnsName 301db.dbestserv.com -Type A
Test-NetConnection 301db.dbestserv.com -Port 5432
```

**Expected result:** Domain resolves to the intended public IPv4 and `TcpTestSucceeded : True`. A positive TCP test verifies reachability, **not** database authentication or TLS identity.

**Status:** **NOT VERIFIED / FAILED DURING HOME-NETWORK TEST.** Do not label public DBeaver access as operational.

### 13.3 Outstanding security requirements

- [ ] Correct and verify the HBA policy so the `postgres` superuser cannot authenticate from externally forwarded TCP connections; preserve a separate local administrative recovery path.
- [ ] Audit all developer password hashes for SCRAM-SHA-256 and rotate weak or exposed credentials.
- [ ] Test the `integration` login against database `dev` from DBeaver.
- [ ] Verify the active client connection is TLS-encrypted using `pg_stat_ssl`.
- [ ] Configure DBeaver with `sslmode=verify-full`, the correct hostname, and the trusted public certificate before using a public network.
- [ ] Revisit server-side `hostssl` policy; TLS is available but is **not currently mandatory** for all TCP clients.
- [ ] Verify Docker's published-port behavior and router security; ordinary UFW policy alone does not necessarily filter Docker-published ports.
- [ ] Verify domain-to-public-IP routing and TCP 5432 from a truly external network.
- [ ] Maintain offline/encrypted database backups and perform a restoration test.

**Caution:** Do not enable or leave a public TCP 5432 forward active before the remote-admin authentication issue and essential credentials are resolved. Docker-published ports can bypass ordinary UFW input filtering.

## 14. Environment variables and repository hygiene

### 14.1 Objective

Keep administrator secrets out of Docker Compose YAML, source control, and team documentation. Preserve the established `.env` method from Section 9.4.

### 14.2 Server-side `.env`

**Location:** `/srv/genledge/postgres/.env`

**Format** (placeholder only; never commit or paste the actual value):

```dotenv
POSTGRES_PASSWORD=REPLACE_WITH_EXISTING_STRONG_ADMIN_PASSWORD
```

**Verification**

```bash
cd /srv/genledge/postgres
stat -c '%a %U %G %n' .env
grep -q '^POSTGRES_PASSWORD=.' .env && echo 'Password configured'
sudo docker compose config --quiet
```

**Expected result:** `.env` mode `600`, password variable present, and Compose configuration valid. Do **not** share unredacted `docker compose config` output: secrets may be expanded.

**Status:** **PASS — existing protected `.env` previously created and verified.** Changing `.env` alone will not rotate a password inside an already initialized PostgreSQL data volume.

### 14.3 Template and Git ignore rules

**Suggested `.env.example`** (safe to commit):

```dotenv
POSTGRES_PASSWORD=REPLACE_WITH_A_STRONG_PASSWORD
```

**Suggested `.gitignore`:**

```gitignore
.env
.env.*
!.env.example
```

This file pattern excludes `.env` and local variants but permits `.env.example`. Check tracked files separately: `.gitignore` does not retroactively untrack a secret already committed.

### 14.4 Application-side configuration (future)

The backend's database connection environment should be stored **separately** from the server administrator `.env` and use a least-privileged database identity.

```dotenv
DB_HOST=301db.dbestserv.com
DB_PORT=5432
DB_NAME=dev
DB_USER=integration
DB_PASSWORD=REPLACE_WITH_INTEGRATION_PASSWORD
DB_SSLMODE=verify-full
```

This is a future configuration example, **not** evidence that public-domain connectivity or certificate validation already works. The client must also trust the appropriate public certificate and match the certificate hostname. Do not commit database URLs containing real passwords. If embedding passwords into a URL, percent-encode reserved characters.

### 14.5 Consolidated current acceptance status

| Check | Current status |
|---|---|
| Host/SSH, Docker Engine and PostgreSQL container | PASS |
| SQL read/write and named-volume persistence | PASS |
| Seven developer role/database pairs and isolation | PASS — owner-reported provisioning checks |
| TLS certificate installed in persistent PostgreSQL data directory | PASS |
| PostgreSQL SSL-enabled Compose settings | Configured and running — owner-reported |
| Windows to Pi LAN TCP 5432 | PASS (`Test-NetConnection`) |
| DBeaver connection via LAN | PASS with `postgres` (security gap) |
| DBeaver normal user and session TLS validation | PENDING |
| Remote TCP superuser denial | **FAIL — remote `postgres` login succeeded** |
| Domain DNS matches outward public IPv4 | PASS — owner-reported |
| Domain DBeaver TCP 5432 access | NOT WORKING / unverified externally |
| Public router forwarding and TLS hostname verification | PENDING |
| Independent restore verification | PENDING |

**Next actions:** Resolve the remote-superuser HBA rule, validate normal-account SSL connections, and investigate external router connectivity without exposing SSH or committing credentials.

