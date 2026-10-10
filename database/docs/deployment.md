# Raspberry Pi Host Deployment

## 1. Overview

This document records the initial setup of the Raspberry Pi host intended for the team's PostgreSQL development database.

The Raspberry Pi is primarily a personal server. Team access will be limited to explicitly authorized project services.

## 2. Environment

| Component | Configuration |
|---|---|
| Device | Raspberry Pi 5 (8GB) |
| Operating System | Ubuntu Server 24.04 LTS (64-bit) |
| Hostname | `pi5-server` |
| Administrator | `piadmin` |
| Network | Wi-Fi |
| Remote Management | SSH public-key authentication |
| SSH Client | MobaXterm Personal 23.4 |

## 3. Installation and Initialization

Ubuntu Server was installed using Raspberry Pi Imager.

During setup:
- A personal administrator account was configured.
- SSH was enabled.
- An Ed25519 public key was installed for remote authentication.
- The hostname was configured as `pi5-server`.

### First Boot Verification

Command:

```bash
cloud-init status --wait
```

Observed result:

```text
status: done
```

Status: **Passed**

## 4. Network and SSH Connectivity

The host was successfully discovered over the local Wi-Fi network.

Windows SSH connectivity was tested using:

```powershell
Test-NetConnection pi5-server.local -Port 22
```

Observed result:

```text
TcpTestSucceeded : True
```

Remote login through MobaXterm was also successful.

Status: **Passed**

## 5. System Initialization

System maintenance and hardware inspection were performed using:

```bash
sudo apt update
sudo apt full-upgrade -y
sudo apt autoremove -y
```

Environment inspection commands:

```bash
whoami
hostnamectl
cat /etc/os-release
uname -m
free -h
df -h /
```

System package updates were reported as completed. Detailed output values should be recorded in the deployment verification log.

## 6. Current Progress

| Task | Status |
|---|---|
| Ubuntu installation | Completed |
| First boot initialization | Verified |
| Wi-Fi connectivity | Verified |
| SSH connectivity | Verified |
| System updates | Completed |
| Host security configuration | In verification |
| Docker installation | Pending |
| PostgreSQL deployment | Pending |

## 7. Next Steps

- [ ] Complete host security verification
- [ ] Install and verify Docker Engine and Compose
- [ ] Deploy PostgreSQL with persistent storage
- [ ] Provision developer and integration databases
- [ ] Verify database permissions and persistence
- [ ] Configure restricted remote database access
