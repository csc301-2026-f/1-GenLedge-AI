# Raspberry Pi Host Security

## 1. Security objectives and scope

This Raspberry Pi is a **personal computer providing one restricted team database service**. The owner (`piadmin`) retains SSH and `sudo` access. Team members are **not** issued Linux/SSH administrator accounts. They will later receive only separately provisioned PostgreSQL accounts and tightly scoped network connectivity.

**Status (2026-10-10): The owner reports completing and passing all the host security tests described below.** Example output is an **expected result**, not a saved verbatim console log unless explicitly identified as previously observed. PostgreSQL-specific controls have **not** been implemented yet.

## 2. SSH authentication and account access

### Goal
Keep personal administrator key-based SSH access, block password-based and direct root SSH login, and restrict SSH logins to `piadmin`.

### Prerequisite (Windows PowerShell)
Verify the personal private key works **before** changing SSH configuration. Keep the original MobaXterm session open during changes.
```powershell
ssh -i "$HOME\.ssh\pi5_admin" `
  -o IdentitiesOnly=yes `
  -o PreferredAuthentications=publickey `
  -o PasswordAuthentication=no `
  -o KbdInteractiveAuthentication=no `
  piadmin@pi5-server.local
```
**Expected:** a new Ubuntu shell opens using public-key authentication, without requesting an Ubuntu SSH password (the key's passphrase, if configured, is different).

### Setup (Pi)
```bash
sudo nano /etc/ssh/sshd_config.d/01-admin-access.conf
```
Enter:
```text
PermitRootLogin no
PubkeyAuthentication yes
PasswordAuthentication no
KbdInteractiveAuthentication no
AllowUsers piadmin
```

OpenSSH commonly uses the **first obtained value** for repeated settings; other included configuration files and `Match` rules may change effective settings. Always validate them before and after a reload.

```bash
sudo sshd -t
sudo sshd -T | grep -Ei 'permitrootlogin|pubkeyauthentication|passwordauthentication|kbdinteractiveauthentication|allowusers'
sudo systemctl reload ssh
```
Only reload after `sshd -t` succeeds and `sshd -T` matches the intended policy. Keep the existing terminal open until a **second** login works.

### Verification A: effective policy (Pi)
```bash
sudo sshd -t
echo $?
sudo sshd -T | grep -Ei 'permitrootlogin|pubkeyauthentication|passwordauthentication|kbdinteractiveauthentication|allowusers'
```
**Expected:** exit code `0` for `sshd -t`; effective values:
```text
permitrootlogin no
pubkeyauthentication yes
passwordauthentication no
kbdinteractiveauthentication no
allowusers piadmin
```
If `Match` rules apply, repeat with `sudo sshd -T -C user=piadmin,host=pi5-server,addr=<actual-client-IP>` (replace placeholder with actual client address, not literal angle brackets).

### Verification B: public-key login (Windows PowerShell)
```powershell
ssh -v -i "$HOME\.ssh\pi5_admin" `
  -o IdentitiesOnly=yes `
  -o PreferredAuthentications=publickey `
  -o PasswordAuthentication=no `
  -o KbdInteractiveAuthentication=no `
  piadmin@pi5-server.local
```
**Expected:** successful shell and an authentication log line resembling `Authenticated ... using "publickey"`.

### Verification C: reject password-only login (Windows PowerShell)
```powershell
ssh -o PubkeyAuthentication=no `
  -o PreferredAuthentications=password `
  -o KbdInteractiveAuthentication=no `
  -o BatchMode=yes `
  piadmin@pi5-server.local
```
**Expected:** authentication denied, no shell. The exact failure text may vary.

### Verification D: reject root SSH login
On Pi:
```bash
sudo sshd -T -C user=root,host=pi5-server,addr=127.0.0.1 | grep permitrootlogin
```
**Expected:** `permitrootlogin no`. For IP-dependent `Match` rules, test with the actual Windows client's address as well.

On Windows:
```powershell
ssh -i "$HOME\.ssh\pi5_admin" -o IdentitiesOnly=yes -o BatchMode=yes root@pi5-server.local
```
**Expected:** authentication denied, no root shell. A denial for a single key *alone* cannot prove a global root-login prohibition; use the effective policy check too.

**Result (S-01 through S-04): PASS — owner confirmed all tests.**

## 3. SSH service and persistence

### Setup
Ubuntu 24.04 can start SSH through **systemd socket activation**. An `ssh.service` marked `disabled` is not necessarily a problem if `ssh.socket` is enabled and active. No change was required when these conditions were verified.

If the socket were unexpectedly disabled, inspect the system's actual SSH unit configuration before changing it; do not enable conflicting activation methods blindly.

### Verification (Pi)
```bash
systemctl is-active ssh
systemctl is-enabled ssh.socket
systemctl is-active ssh.socket
```
**Expected / previously observed:**
```text
active
enabled
active
```

### Full reboot verification
After all SSH and firewall tests pass:
```bash
sudo reboot
```
Reconnect from Windows:
```powershell
ssh -i "$HOME\.ssh\pi5_admin" piadmin@pi5-server.local
```
Then on Pi:
```bash
systemctl is-active ssh.socket
sudo ufw status verbose
```
**Expected:** SSH reconnects; `ssh.socket` is `active`; firewall status is `active` and rules remain in force.

**Result (S-05): PASS — owner confirmed all verification steps, including reboot test.**

## 4. Personal files and administrator privileges

### Goal
Prevent other ordinary Linux users from traversing the personal home directory while preserving `piadmin`'s `sudo` privileges.

### Setup (Pi)
```bash
sudo chmod 700 /home/piadmin
```
The home directory remains accessible to the owner and to root. File permissions do **not** isolate data from root or a fully privileged container.

### Verification (Pi)
```bash
stat -c '%a %U %G %n' /home/piadmin
whoami
sudo whoami
sudo -l
getent group sudo
getent group docker
```
**Expected:**
- `700 piadmin piadmin /home/piadmin` (owner/group may need investigation if actually different).
- `whoami` → `piadmin`; `sudo whoami` → `root`.
- `sudo -l` lists the intended administrator permissions (for full sudo, typically `(ALL : ALL) ALL`).
- `sudo` and `docker` groups contain **no unauthorized team accounts**; `docker` group may not exist before Docker installation.

**Result (S-06): PASS — owner confirmed all checks.**

## 5. UFW host firewall

### Goal
Deny unsolicited incoming connections by default, retain personal SSH access, and allow outbound access. PostgreSQL has **not** been deployed or opened at this stage.

### Setup (Pi)
**Before enabling the firewall**, explicitly allow SSH:
```bash
sudo ufw allow 22/tcp
sudo ufw default deny incoming
sudo ufw default allow outgoing
sudo ufw enable
```
Keep the existing SSH connection open, then verify a new login in another window.

### Verification A: rules (Pi)
```bash
sudo ufw status verbose
```
**Previously observed:**
```text
Status: active
Logging: on (low)
Default: deny (incoming), allow (outgoing), disabled (routed)

22/tcp       ALLOW IN    Anywhere
22/tcp (v6)  ALLOW IN    Anywhere (v6)
```
Actual output has columns/headings and may differ slightly in spacing. This is a host UFW rule list; it does **not** prove Docker-published ports will be blocked.

### Verification B: new SSH connection (Windows PowerShell)
```powershell
Test-NetConnection pi5-server.local -Port 22
ssh -i "$HOME\.ssh\pi5_admin" piadmin@pi5-server.local
```
**Expected:** `TcpTestSucceeded : True` and successful new private-key SSH login.

### Verification C: startup persistence (Pi, after reboot)
```bash
sudo ufw status verbose
```
**Expected:** `Status: active`, incoming `deny`, outgoing `allow`, SSH rule retained.

**Result (S-07): PASS — UFW configuration was directly observed earlier; owner confirms subsequent new-login and persistence tests passed.**

**Security limitation:** `22/tcp ALLOW IN Anywhere` permits reachable hosts to *attempt* SSH authentication; it does not grant a shell. Later it may be narrowed to trusted networks. Docker port publishing has independent firewall implications and must be reviewed during database deployment.

## 6. Team access policy — planned, not yet deployed

- No team member receives the `piadmin` password, private SSH key, `sudo`, or Docker administration privileges.
- Team members will access PostgreSQL through their own scoped **database roles**, not host SSH shells.
- Database access will be network-restricted (e.g., controlled private VPN), with no public 5432 exposure by default.
- Database isolation, privileges, health, persistence, credentials and remote connectivity must be tested during PostgreSQL deployment.
- A separate restricted file-sharing service will be required if the project later needs document uploads; database permissions do not grant file-sharing access.

## 7. Secret management

- Windows private key: `$HOME\.ssh\pi5_admin`, never committed to Git; `.pub` may be distributed to authorized hosts.
- Ubuntu administrator password and any SSH key passphrase: personal password manager.
- Future database passwords: root-protected server-side secret files / credential store, backed up securely outside the team repository.
- Git tracks only non-sensitive deployment configuration, templates, verification methods and sanitized results.
- `.gitignore` does not remove secrets already committed to Git history; any exposed credentials must be rotated.

## 8. Host security verification summary

| ID | Check | Expected result | Status |
|---|---|---|---|
| S-01 | SSH syntax and effective settings | Syntax valid, key-only `piadmin` policy | PASS — owner confirmed |
| S-02 | Admin key login | Successful public-key authentication | PASS — owner confirmed |
| S-03 | Password-only SSH | Rejected | PASS — owner confirmed |
| S-04 | Root SSH | Prohibited by policy; login denied | PASS — owner confirmed |
| S-05 | SSH socket + reboot | Active/enabled; reconnect succeeds | PASS — owner confirmed |
| S-06 | Permissions and sudo | Home `700`, admin sudo, no unexpected privileged team users | PASS — owner confirmed |
| S-07 | UFW rules + new login + reboot | Active, default incoming deny, SSH access retained | PASS — owner confirmed |

> **Scope note:** These host security checks do not certify PostgreSQL isolation, VPN restrictions, Docker behavior, backups, or the absence of vulnerabilities. Those require additional tests after deployment.
