# PostgreSQL Server Deployment

## 1. Overview

This document describes the setup and deployment of a PostgreSQL development database server hosted on a Raspberry Pi 5.

The server is intended to provide isolated development databases and a shared integration database for the project team.

The Raspberry Pi is also a personal device. Therefore, database access must be separated from operating system administration, and team members must not receive access to personal files or system management privileges.

## 2. Host Environment

| Component | Configuration |
|---|---|
| Hardware | Raspberry Pi 5 (8GB RAM) |
| Operating System | Ubuntu Server 24.04.05 LTS (64-bit) |
| Hostname | `pi5-server` |
| Architecture | ARM64 / aarch64 |
| Remote Administration | SSH with public-key authentication |
| SSH Client | MobaXterm Personal 23.4 |
| Container Runtime | Docker (pending) |
| Database | PostgreSQL (pending) |

## 3. Host Environment Setup

### 3.1 Operating System Installation

Ubuntu Server 24.04.05 LTS was installed using Raspberry Pi Imager.

Initial configuration included:

- Hostname: `pi5-server`
- Administrator account: configured for personal server administration
- SSH: enabled with public-key authentication
- Network: Wi-Fi

The administrator's private SSH key is stored on their personal computer and is not included in the project repository.

### 3.2 First Boot Verification

The initial Ubuntu configuration was verified using:

```bash
cloud-init status --wait
```

Result:

```text
status: done
```

This confirmed that cloud-init had completed its first-boot initialization.

### 3.3 Operating System Verification

The following commands were used to inspect the host environment:

```bash
whoami
hostnamectl
cat /etc/os-release
uname -m
free -h
df -h /
```

The checks covered:

- Current Linux user and hostname
- Operating system version
- CPU architecture
- Available memory
- Available storage

### 3.4 System Updates

The system package index and installed packages were updated:

```bash
sudo apt update
sudo apt full-upgrade -y
sudo apt autoremove -y
```

### 3.5 Network and SSH Verification

The following commands were used:

```bash
ip -br addr
ip route
sudo systemctl is-active ssh
```

Remote SSH access was successfully established from Windows using MobaXterm and SSH key authentication.

### 3.6 Basic Utilities

The following utilities were installed or checked:

```bash
sudo apt install -y \
  git \
  curl \
  wget \
  nano \
  htop \
  ca-certificates \
  openssl
```

## 4. Verification Status

| Check | Status |
|---|---|
| Ubuntu installation | Completed |
| SSH remote login | Passed |
| Cloud-init initialization | Passed |
| OS version and architecture | Verify recorded results |
| System package updates | Completed |
| Network and SSH service | Completed |
| Basic utilities | Completed |
| Docker Engine | Pending |
| PostgreSQL deployment | Pending |

## 5. Security Considerations

- SSH administration is reserved for the device owner.
- Team members will receive PostgreSQL credentials rather than Ubuntu administrator credentials.
- SSH private keys and database passwords must never be committed to Git.
- PostgreSQL must not be publicly exposed by default.
- Team database data will be stored separately from personal files.

## 6. Next Steps

- [x] Review SSH access restrictions
- [x] Configure and verify host firewall rules
- [ ] Install Docker Engine and Docker Compose
- [ ] Verify Docker Hub image pulling
- [ ] Deploy PostgreSQL with persistent storage
- [ ] Provision development and integration databases
- [ ] Test database access, isolation, and persistence
- [ ] Configure secure remote database access
- [ ] Document backup and recovery procedures
