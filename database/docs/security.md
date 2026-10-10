# Raspberry Pi Host Security

## 1. Security Objectives

The Raspberry Pi is primarily a personal server and additionally hosts team development services.

The security configuration aims to:

- Preserve full administrative access for the device owner.
- Restrict SSH access to the administrator.
- Prevent project members from accessing personal files or system administration functions.
- Provide team members with separate PostgreSQL credentials.
- Avoid storing sensitive credentials in Git.

## 2. SSH Access Control

The intended SSH configuration is:

```text
PermitRootLogin no
PubkeyAuthentication yes
PasswordAuthentication no
KbdInteractiveAuthentication no
AllowUsers piadmin
```

Verification:

```bash
sudo sshd -t
sudo sshd -T
```

Additional authentication tests:

- [ ] Public-key login succeeds
- [ ] Password-only login is rejected
- [ ] Root SSH login is disabled
- [ ] Effective SSH configuration matches the intended policy

## 3. SSH Service Availability

The following states were observed:

```text
ssh.service: active
ssh.socket: enabled
ssh.socket: active
```

SSH socket activation is enabled and currently active.

- [x] SSH socket enabled
- [x] SSH socket active
- [ ] SSH login confirmed after a full host reboot

## 4. Linux Account and File Permissions

The administrator's home directory was configured with restricted permissions:

```bash
sudo chmod 700 /home/piadmin
```

Verification commands:

```bash
stat -c '%a %U %G %n' /home/piadmin
sudo -l
sudo whoami
```

- [ ] Home directory ownership and permissions independently verified
- [ ] Administrator sudo permissions verified

## 5. Host Firewall

UFW was configured with the following commands:

```bash
sudo ufw allow 22/tcp
sudo ufw default deny incoming
sudo ufw default allow outgoing
sudo ufw enable
```

Observed verification:

```text
Status: active
Logging: on (low)
Default: deny (incoming), allow (outgoing), disabled (routed)

22/tcp      ALLOW IN    Anywhere
22/tcp (v6) ALLOW IN    Anywhere (v6)
```

Verification:

- [x] Firewall enabled
- [x] Default incoming traffic denied
- [x] Default outgoing traffic allowed
- [x] SSH TCP 22 allowed
- [x] IPv6 SSH TCP 22 allowed
- [ ] New SSH session tested after enabling UFW

## 6. Team Access Policy

Team members will not receive administrator SSH credentials.

PostgreSQL users will be provisioned with independent credentials and restricted database privileges.

Remote database access has not yet been enabled.

Docker port publishing must be independently reviewed before exposing PostgreSQL to authorized networks.

## 7. Secret Management

SSH private keys, administrator passwords, PostgreSQL passwords, and other sensitive configuration values must not be committed to Git.

Only non-sensitive configuration templates and documented deployment procedures should be stored in the team repository.
