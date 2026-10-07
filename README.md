# GenLedge Connector

## Partner Intro

GenLedge is an AI-powered ERP platform that automates business operations such as invoice processing, delivery tracking, and payments. Our team is building an independent data pipeline from scratch. The partner provides project direction, requirements, priorities, and feedback. Daniel is our team's primary liaison; partner contact names and emails are to be added.

## Description about the project

GenLedge Connector helps data and operations analysts prepare ERP data for reporting with less manual work. An AI agent proposes data mappings and transformations, which users review and approve before loading data into a separate reporting database. This helps teams answer questions about vendor performance, deliveries, and payments.

## Key Features

The current frontend prototype demonstrates the planned MVP workflow:

1. Secure sign-in to access organizational data.
2. File uploads or database connections to import source data.
3. Automatic discovery of source tables and fields.
4. AI-generated routing and source-to-target mappings.
5. Human review and editing of mappings before approval.
6. Pipeline transform-and-load progress.
7. Pipeline scheduling and run monitoring.

The prototype currently uses mocked data and interactions. The Flask backend is a scaffold and is not connected to the frontend yet.

## Instructions

The current prototype can be run locally by installing the frontend and backend dependencies, then starting both services.

1. Install Node.js and pnpm, and install Python 3.
2. Install frontend dependencies:

   ```bash
   cd src/frontend
   pnpm install
   ```

3. Install backend dependencies:

   ```bash
   cd ../backend
   python -m pip install -r requirements-dev.txt
   ```

   On Windows, use `py -3` instead of `python` when needed.

4. From the repository root, start both services:

   ```bash
   # macOS, Linux, WSL, or Git Bash
   ./src/start-app.sh
   ```

   ```bat
   :: Windows Command Prompt or PowerShell
   src\start-app.bat
   ```

5. Open the frontend at `http://127.0.0.1:5173`. The Flask placeholder runs at `http://127.0.0.1:5000`.

To build the frontend, run `pnpm build` from `src/frontend/`. Vite writes the browser-ready output to the ignored `compiled/` directory. To run the backend smoke test, run `python -m pytest tests` from `src/backend/`.

Account provisioning, supported production file formats, deployment access, and production credentials will be confirmed during implementation.

## Development requirements

The frontend uses React, Vite, and TypeScript. The backend uses a Flask modular-monolith structure in Python. PostgreSQL is planned for control-plane data, LangGraph is planned for AI-assisted mapping, and a Python worker is planned for pipeline execution. AWS Glue remains a possible future execution option for larger workloads.

## Deployment and Github Workflow

The team uses a private GitHub repository with branches, commits, and pull requests. Development work is organized into focused branches, reviewed by teammates, and merged into `main` after the relevant frontend build and backend test checks pass. The `src/start-app` scripts provide a repeatable local workflow; hosting and production release steps remain to be determined.

## Coding Standards and Guidelines

Use consistent formatting, descriptive names, validated inputs, and clearly scoped functions. Keep credentials outside source control and review changes through pull requests.

## Licenses

The selected planning option allows the team to reference the work in resumes and interviews. The team will not share the code or software unless the partner agrees. The team will use its own schemas, test data, and implementation.

## Deployed URL / Access Instructions

Deployment URL and account access details are not available yet. The [Figma demo](https://www.figma.com/make/5FBkZzoaCpGV83S88IPkY1/--------CSC301-D1-Demo?p=f&t=dNeXPEpMKdHMtUZw-0) provides the current design reference.

## D3 Improvement Highlight

Since D1, the project has been organized around a React/Vite frontend and a Flask modular backend. The frontend screens were split into feature folders, the backend capability packages and app entrypoint were scaffolded, and cross-platform `start-app` scripts were added for local development. Detailed architecture and startup notes are in `doc/`.
