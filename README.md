# GenLedge Connector

## Partner Intro

GenLedge is an AI-powered ERP platform that automates business operations such as invoice processing, delivery tracking, and payments. Our team is building an independent data pipeline from scratch. The partner provides project direction, requirements, priorities, and feedback. Daniel is our team's primary liaison; partner contact names and emails are to be added.

## Description about the project

GenLedge Connector helps data and operations analysts prepare ERP data for reporting with less manual work. An AI agent proposes data mappings and transformations, which users review and approve before loading data into a separate reporting database. This helps teams answer questions about vendor performance, deliveries, and payments.

## Key Features

Planned MVP features:

1. Secure sign-in to access organizational data.
2. File uploads or database connections to import source data.
3. Automatic discovery of source tables and fields.
4. AI-generated mappings and transformations.
5. Mapping review and editing before approval.
6. Pipeline execution to transform and load data for analytics.
7. Pipeline scheduling and run monitoring.

## Instructions

Intended user workflow:

1. Sign in and upload a file or connect a source database.
2. Review the discovered data structure and specify the target dataset.
3. Generate mappings with the AI agent, then review and edit them.
4. Approve and run the pipeline; check the results in the target database.
5. Schedule future runs and review run history for failures.

Account provisioning, supported file formats, and exact interface steps will be confirmed during implementation.

## Development requirements

The planned stack uses React, Vite, TypeScript, and React Flow for the frontend; Node.js, Fastify, PostgreSQL, and Prisma for the backend; LangGraph.js with Claude or OpenAI for the agent; and Python for data processing.

Local setup requires installing project dependencies, configuring database connections and AI credentials, initializing the database, and starting the frontend and backend. Runtime versions, environment variables, and exact commands will be added once verified in the repository.

## Deployment and Github Workflow

The team uses a private GitHub repository with branches, commits, and pull requests, with teammate review before merging. Notion tracks task ownership and progress. Branch conventions, reviewers, and merge ownership remain to be confirmed.

Hosting tools and release steps are still being determined. The partner provides direction and feedback. This workflow supports shared development and review of data-processing changes.

## Coding Standards and Guidelines

Proposed guidelines: use consistent formatting, descriptive names, and clearly scoped functions. Review code through pull requests, validate inputs, and keep credentials outside source control.

## Licenses

The selected planning option allows the team to reference the work in resumes and interviews. The team will not share the code or software unless the partner agrees. The team will use its own schemas, test data, and implementation.

## Deployed URL / Access Instructions

Deployment URL and account access details: to be added. The [Figma demo](https://www.figma.com/make/5FBkZzoaCpGV83S88IPkY1/--------CSC301-D1-Demo?p=f&t=dNeXPEpMKdHMtUZw-0) provides a design reference.

## D3 Improvement Highlight

To be updated with completed improvements since D2 and where reviewers can find them; these changes are not recorded in the planning document.
