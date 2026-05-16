# Getting Started

<cite>
**Referenced Files in This Document**
- [README.md](file://README.md)
- [setup.sh](file://setup.sh)
- [smoke_test.sh](file://smoke_test.sh)
- [cron_daily_query.sh](file://cron_daily_query.sh)
- [config/zxgk.example.yaml](file://config/zxgk.example.yaml)
- [config/companies.example.txt](file://config/companies.example.txt)
- [SKILL.md](file://SKILL.md)
- [captcha-solver/API.md](file://captcha-solver/API.md)
- [captcha-solver/requirements.txt](file://captcha-solver/requirements.txt)
</cite>

## Table of Contents
1. [Introduction](#introduction)
2. [Prerequisites](#prerequisites)
3. [Installation](#installation)
4. [Initial Setup](#initial-setup)
5. [First Query Execution](#first-query-execution)
6. [Environment Preparation](#environment-preparation)
7. [Troubleshooting](#troubleshooting)
8. [Manual vs Automated Setup](#manual-vs-automated-setup)
9. [Next Steps](#next-steps)

## Introduction
This guide helps you install and set up the Execution Information Query System quickly. It covers prerequisites, installation via the automated setup script, configuration of environment variables, creating company lists, running your first query, and troubleshooting common issues. Both beginners and experienced users can follow along.

## Prerequisites
Before installing, ensure your system meets the following requirements:
- Memory: At least 4 GB RAM (recommended for OCR model and browser automation)
- Operating systems: Ubuntu or macOS
- Software: Python 3.10+, npm, Docker (optional but recommended for OCR service)
- OCR service: Must be available at localhost:8001 with compatible endpoints

These requirements are enforced by the project’s scripts and configuration. The system depends on a local OCR service that recognizes captchas during browser automation.

**Section sources**
- [README.md:8-14](file://README.md#L8-L14)
- [setup.sh:16-25](file://setup.sh#L16-L25)
- [setup.sh:58-109](file://setup.sh#L58-L109)
- [config/zxgk.example.yaml:7-8](file://config/zxgk.example.yaml#L7-L8)

## Installation
There are two primary ways to install the system: automated via the setup script and manual steps. The automated approach is recommended for most users.

### Automated Installation (Recommended)
Run the installation script to automatically install dependencies, configure the virtual environment, and prepare the OCR service.

- Run the setup script:
  - On Linux/macOS, execute: bash setup.sh
  - The script checks for required tools, sets up a Python virtual environment, installs Playwright and dependencies, installs lark-cli, and handles OCR service setup.

- The script prompts you to choose how to handle the OCR service:
  - Install PaddleOCR locally (recommended)
  - Skip installation and deploy your own OCR service compatible with localhost:8001
  - Assume an existing OCR service is running at localhost:8001

- After installation completes, the script prints helpful commands for first run.

**Section sources**
- [setup.sh:1-150](file://setup.sh#L1-L150)
- [README.md:15-27](file://README.md#L15-L27)

### Manual Installation
If you prefer manual control, follow these steps:

- Install required tools:
  - Python 3.10+ and pip
  - npm (for lark-cli)
  - Optional: Docker (for OCR service)

- Create and activate a Python virtual environment:
  - Create: python3 -m venv venv
  - Activate: source venv/bin/activate

- Install dependencies:
  - Install Playwright and related packages
  - Install lark-cli globally: npm install -g @larksuite/cli

- Prepare the OCR service:
  - Option A: Install PaddleOCR locally inside captcha-solver
  - Option B: Deploy your own OCR service compatible with localhost:8001
  - Option C: Use an existing OCR service at localhost:8001

- Verify the OCR service health endpoint:
  - curl -s http://localhost:8001/health

- Authenticate with lark-cli:
  - lark-cli auth
  - Confirm authentication: lark-cli api GET '/open-apis/authen/v1/user_info' --as user

**Section sources**
- [setup.sh:27-45](file://setup.sh#L27-L45)
- [setup.sh:47-124](file://setup.sh#L47-L124)
- [captcha-solver/API.md:3-15](file://captcha-solver/API.md#L3-L15)
- [captcha-solver/requirements.txt:1-9](file://captcha-solver/requirements.txt#L1-L9)

## Initial Setup
After installation, configure the system for your environment.

### Configure Environment Variables
- Copy the example environment file and edit it:
  - cp .env.example .env
  - Add your FEISHU_APP_TOKEN to .env
  - Load the environment: source .env

- If you do not set FEISHU_APP_TOKEN, results will be stored locally in SQLite by default.

**Section sources**
- [setup.sh:126-140](file://setup.sh#L126-L140)
- [README.md:29-34](file://README.md#L29-L34)

### Create Company Lists
- Copy the example company list:
  - cp config/companies.example.txt config/companies.txt
- Edit companies.txt to include the companies you want to query (one per line). Lines starting with # are comments.

**Section sources**
- [README.md:21-27](file://README.md#L21-L27)
- [config/companies.example.txt:1-7](file://config/companies.example.txt#L1-L7)

### Configure OCR Service Endpoint
- By default, the system expects the OCR service at http://localhost:8001
- If you change the port, update config/zxgk.yaml under captcha_server

**Section sources**
- [config/zxgk.example.yaml:7-8](file://config/zxgk.example.yaml#L7-L8)

## First Query Execution
Once everything is installed and configured, run your first query.

### Quick Start Commands
- Activate the virtual environment: source venv/bin/activate
- Single company query:
  - python3 zxgk_query.py --company "XX公司" --subsite zhixing --mode text-only --output /tmp/single.json
- Batch query:
  - python3 zxgk_query.py --batch config/companies.txt --subsite zhixing --mode text-only --output /tmp/batch.json
- Full daily pipeline:
  - bash cron_daily_query.sh

**Section sources**
- [README.md:63-77](file://README.md#L63-L77)
- [cron_daily_query.sh:126-131](file://cron_daily_query.sh#L126-L131)

### Understanding Outputs
- Batch JSON files are generated per subsite and date
- SQLite database is always written locally for backup
- If FEISHU_APP_TOKEN is set and lark-cli is authenticated, results are also written to Feishu tables

**Section sources**
- [cron_daily_query.sh:138-146](file://cron_daily_query.sh#L138-L146)
- [README.md:35-44](file://README.md#L35-L44)

## Environment Preparation
Prepare your environment to ensure reliable operation.

### Verify Dependencies
- Run the smoke test to validate syntax, configuration, environment variables, and dependencies:
  - bash smoke_test.sh

- The smoke test checks:
  - Python and shell syntax
  - YAML configuration validity
  - Presence of companies.txt
  - FEISHU_APP_TOKEN presence
  - Virtual environment and installed packages
  - OCR service health endpoint
  - Batch JSON format (if present)

**Section sources**
- [smoke_test.sh:1-155](file://smoke_test.sh#L1-L155)
- [README.md:45-54](file://README.md#L45-L54)

### Feishu Authentication
- Ensure lark-cli is authenticated:
  - lark-cli auth
  - Verify: lark-cli api GET '/open-apis/authen/v1/user_info' --as user

- If not authenticated, results will still be saved locally to SQLite, but Feishu synchronization will be skipped.

**Section sources**
- [setup.sh:112-124](file://setup.sh#L112-L124)
- [cron_daily_query.sh:99-107](file://cron_daily_query.sh#L99-L107)

## Troubleshooting
Common issues and their resolutions:

### OCR Service Not Running
- Symptoms:
  - Health check fails or captcha-solver is unreachable
- Resolution:
  - Start the OCR service using Docker or bare-metal venv
  - Verify health endpoint: curl -s http://localhost:8001/health
  - If port 8001 is occupied by another process, change the port in config/zxgk.yaml and restart

**Section sources**
- [cron_daily_query.sh:48-96](file://cron_daily_query.sh#L48-L96)
- [captcha-solver/API.md:70-75](file://captcha-solver/API.md#L70-L75)

### Feishu Authentication Issues
- Symptoms:
  - Unauthorized response from Feishu API
- Resolution:
  - Re-authenticate: lark-cli auth
  - Verify: lark-cli api GET '/open-apis/authen/v1/user_info' --as user
  - Retry writing to Feishu manually if needed

**Section sources**
- [setup.sh:112-124](file://setup.sh#L112-L124)
- [SKILL.md:175-189](file://SKILL.md#L175-L189)

### Port Conflicts
- Symptoms:
  - Port 8001 already in use by another process
- Resolution:
  - Stop the conflicting process or change the OCR service port in config/zxgk.yaml
  - Restart the OCR service

**Section sources**
- [cron_daily_query.sh:49-57](file://cron_daily_query.sh#L49-L57)

### Insufficient Memory
- Symptoms:
  - OCR model download or runtime instability
- Resolution:
  - Ensure at least 4 GB RAM; free up memory or reduce concurrent tasks

**Section sources**
- [README.md:10](file://README.md#L10)
- [SKILL.md:32-35](file://SKILL.md#L32-L35)

### Missing or Incorrect Configuration
- Symptoms:
  - YAML parsing errors or missing fields
- Resolution:
  - Validate config/zxgk.yaml using the smoke test
  - Ensure companies.txt exists and is not named companies.yaml

**Section sources**
- [smoke_test.sh:40-60](file://smoke_test.sh#L40-L60)
- [smoke_test.sh:74-77](file://smoke_test.sh#L74-L77)

## Manual vs Automated Setup
Choose the approach that fits your needs:

### Automated Setup (Recommended)
- Pros:
  - Installs all dependencies automatically
  - Handles OCR service setup with guided choices
  - Checks environment and prints first-run instructions
- Cons:
  - Less control over individual steps

**Section sources**
- [setup.sh:1-150](file://setup.sh#L1-L150)

### Manual Setup
- Pros:
  - Full control over each step
  - Allows custom environments and deployments
- Cons:
  - Requires familiarity with tools and dependencies

**Section sources**
- [setup.sh:27-45](file://setup.sh#L27-L45)
- [setup.sh:47-124](file://setup.sh#L47-L124)

## Next Steps
- Run the smoke test to validate your setup: bash smoke_test.sh
- Execute a quick single-company query to verify end-to-end flow
- Schedule the daily pipeline: bash cron_daily_query.sh
- Explore storage options:
  - SQLite (default)
  - Excel
  - Feishu tables (requires FEISHU_APP_TOKEN and authentication)

**Section sources**
- [smoke_test.sh:1-155](file://smoke_test.sh#L1-L155)
- [README.md:35-44](file://README.md#L35-L44)
- [cron_daily_query.sh:169-210](file://cron_daily_query.sh#L169-L210)