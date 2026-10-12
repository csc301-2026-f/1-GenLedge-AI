# Raspberry Pi Host Deployment

## 1. Purpose and scope

This document records the initial host deployment for a team PostgreSQL **development/test** service on a primarily personal Raspberry Pi. Team members will later access authorized databases, **not** the Ubuntu administrative account.

**Status (2026-10-10): Host initialization and host verification completed; all applicable tests below reported passed by the device owner. Docker and PostgreSQL are not yet deployed.**

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
| Docker / PostgreSQL | Not installed/deployed in this phase |

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

Create the configuration file:

```bash
nano /srv/genledge/postgres/compose.yaml
```

Configuration:

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

## 11. Not in scope yet

- Eight databases and eight corresponding roles.
- Team networking, SQL privileges, backups and PostgreSQL verification.

Record these in subsequent deployment sections **only after actually implementing and testing them**.
