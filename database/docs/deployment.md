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

### 8.6 Next Phase

Deploy PostgreSQL using Docker Compose with a persistent data volume, environment-based credentials, health checks, and local-only network access.

Team remote access remains disabled until database permissions and network restrictions are independently verified.

## 9. Not in scope yet

- Docker Engine / Compose installation and Docker Hub pull test.
- PostgreSQL image, persistent volume, health check and restart policy.
- Eight databases and eight corresponding roles.
- Team networking, SQL privileges, backups and PostgreSQL verification.

Record these in subsequent deployment sections **only after actually implementing and testing them**.
