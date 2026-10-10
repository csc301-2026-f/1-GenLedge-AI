# Task: Install PostgreSQL on Ubuntu Using Docker

Install and configure PostgreSQL on a fresh Ubuntu 24.04 machine using Docker Compose.

Assume this is a brand-new machine with Docker freshly installed and no existing data or configuration to preserve.

## 1. Verify Docker

- Verify that Docker Engine and the Docker Compose plugin are working.
- If Docker is not working, diagnose and fix the installation before proceeding.
- Verify that containers can pull images from Docker Hub.

## 2. Deploy PostgreSQL

- Create a dedicated directory for the PostgreSQL configuration.
- Create a `compose.yaml` file using the official lightweight PostgreSQL Docker image.
- Configure persistent storage, automatic container restarts, and a health check.
- Store the PostgreSQL administrator password in a protected `.env` file.
- Ensure secrets are not committed to Git.
- Start the container and verify that PostgreSQL is healthy.

## 3. Create databases and user accounts

Create one database and one corresponding PostgreSQL login for each developer:

| Developer | Database and username |
|---|---|
| Daniel | `daniel` |
| Leo | `leo` |
| Steven | `steven` |
| Jeff | `jeff` |
| Michael | `michael` |
| Xiran | `xiran` |
| Cherie | `cherie` |

Also create a shared integration database named `dev` with a dedicated login named `integration`.

Requirements:

- Generate a unique, strong password for every account.
- Each developer must own their database and be able to create tables, indexes, and run migrations within it.
- Developers must not be PostgreSQL superusers or have access to one another's databases.
- The integration account must not be a superuser.
- Store credentials securely in a protected file or credential store. Never commit credentials to Git or print passwords in logs.
- Make account provisioning repeatable without resetting passwords or deleting existing data.

## 4. Security

- Do not expose PostgreSQL port `5432` publicly by default.
- Keep PostgreSQL accessible only through local connections until remote access is explicitly configured.
- Do not disable security checks or weaken authentication to make setup easier.

## 5. Verify the installation

Confirm that:

- Docker Compose starts PostgreSQL successfully.
- PostgreSQL passes its health check.
- All eight databases and corresponding logins exist.
- Each developer can connect to their own database and create tables.
- Developers cannot access one another's databases.
- The integration account has only its intended privileges.
- Data persists after the container restarts.

Execute the necessary commands, troubleshoot errors, and report the actual results. Do not claim a test passed unless it was performed.
