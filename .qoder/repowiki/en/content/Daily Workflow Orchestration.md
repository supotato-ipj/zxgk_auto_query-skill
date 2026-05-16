# Daily Workflow Orchestration

<cite>
**Referenced Files in This Document**
- [cron_daily_query.sh](file://cron_daily_query.sh)
- [setup.sh](file://setup.sh)
- [smoke_test.sh](file://smoke_test.sh)
- [diagnose_subsites.py](file://diagnose_subsites.py)
- [zxgk_query.py](file://zxgk_query.py)
- [writers/__init__.py](file://writers/__init__.py)
- [writers/sqlite.py](file://writers/sqlite.py)
- [writers/feishu.py](file://writers/feishu.py)
- [zxgk/backfill.py](file://zxgk/backfill.py)
- [zxgk/runner.py](file://zxgk/runner.py)
- [zxgk/cli.py](file://zxgk/cli.py)
- [config/zxgk.yaml](file://config/zxgk.yaml)
- [config/companies.txt](file://config/companies.txt)
- [README.md](file://README.md)
- [captcha-solver/main.py](file://captcha-solver/main.py)
- [captcha-solver/Dockerfile](file://captcha-solver/Dockerfile)
- [captcha-solver/docker-compose.yml](file://captcha-solver/docker-compose.yml)
</cite>

## Update Summary
**Changes Made**
- Added comprehensive documentation for the new ScreenshotBackfiller class (295 lines) that implements Phase B screenshot recovery
- Updated architecture diagrams to reflect the two-phase workflow (Phase A + Phase B)
- Enhanced troubleshooting section with backfill-specific guidance
- Added new section covering the backfill system's targeted screenshot capture and upload operations
- Updated component analysis to include the dedicated backfill workflow

## Table of Contents
1. [Introduction](#introduction)
2. [Project Structure](#project-structure)
3. [Core Components](#core-components)
4. [Architecture Overview](#architecture-overview)
5. [Detailed Component Analysis](#detailed-component-analysis)
6. [Dependency Analysis](#dependency-analysis)
7. [Performance Considerations](#performance-considerations)
8. [Troubleshooting Guide](#troubleshooting-guide)
9. [Conclusion](#conclusion)
10. [Appendices](#appendices)

## Introduction
This document explains the daily workflow orchestration for automated querying of China Enforcement Information Public Network (执行信息查询) across three subsites: "被执行人" (zhixing), "失信被执行人" (shixin), and "限制消费人员" (xgl). It covers the bash orchestrator, error handling and notifications, logging, multi-subsite execution, and end-to-end storage via SQLite and optional Feishu multi-dimensional tables. The system now includes a sophisticated two-phase workflow with dedicated screenshot backfill capabilities to address missing screenshot recovery with targeted screenshot capture and upload operations.

## Project Structure
The system is organized into:
- Orchestrator shell script driving the daily run with two-phase execution
- Core CLI for browser automation and data extraction
- Writers for local SQLite and optional Feishu integration
- Dedicated ScreenshotBackfiller for Phase B screenshot recovery
- Captcha solver service (OCR) with Docker support
- Configuration and company lists
- Diagnostics and smoke tests for validation

```mermaid
graph TB
subgraph "Orchestrator"
CRON["cron_daily_query.sh"]
SETUP["setup.sh"]
SMOKE["smoke_test.sh"]
end
subgraph "Core"
ZHQ["zxgk_query.py"]
DIAG["diagnose_subsites.py"]
RUNNER["zxgk/runner.py"]
CLI["zxgk/cli.py"]
end
subgraph "Backfill System"
BACKFILL["zxgk/backfill.py"]
end
subgraph "Writers"
WSQL["writers/sqlite.py"]
WFS["writers/feishu.py"]
WIDX["writers/__init__.py"]
end
subgraph "Support"
CFG["config/zxgk.yaml"]
COMPS["config/companies.txt"]
CAP["captcha-solver/main.py"]
DOCK["captcha-solver/docker-compose.yml"]
end
CRON --> ZHQ
CRON --> WSQL
CRON --> WFS
CRON --> BACKFILL
ZHQ --> CAP
ZHQ --> CFG
ZHQ --> COMPS
RUNNER --> BACKFILL
CLI --> BACKFILL
WFS --> CFG
DIAG --> CFG
SETUP --> CAP
SETUP --> ZHQ
SMOKE --> ZHQ
SMOKE --> CAP
```

**Diagram sources**
- [cron_daily_query.sh:1-246](file://cron_daily_query.sh#L1-L246)
- [setup.sh:1-150](file://setup.sh#L1-L150)
- [smoke_test.sh:1-155](file://smoke_test.sh#L1-L155)
- [diagnose_subsites.py:1-429](file://diagnose_subsites.py#L1-L429)
- [zxgk_query.py:1-800](file://zxgk_query.py#L1-L800)
- [writers/__init__.py:1-10](file://writers/__init__.py#L1-L10)
- [writers/sqlite.py:1-121](file://writers/sqlite.py#L1-L121)
- [writers/feishu.py:1-596](file://writers/feishu.py#L1-L596)
- [zxgk/backfill.py:1-296](file://zxgk/backfill.py#L1-L296)
- [zxgk/runner.py:1-278](file://zxgk/runner.py#L1-L278)
- [zxgk/cli.py:1-321](file://zxgk/cli.py#L1-L321)
- [config/zxgk.yaml:1-102](file://config/zxgk.yaml#L1-L102)
- [config/companies.txt:1-6](file://config/companies.txt#L1-L6)
- [captcha-solver/main.py:1-215](file://captcha-solver/main.py#L1-L215)
- [captcha-solver/docker-compose.yml:1-13](file://captcha-solver/docker-compose.yml#L1-L13)

**Section sources**
- [README.md:1-122](file://README.md#L1-L122)
- [cron_daily_query.sh:1-246](file://cron_daily_query.sh#L1-L246)
- [config/zxgk.yaml:1-102](file://config/zxgk.yaml#L1-L102)

## Core Components
- Orchestrator: [cron_daily_query.sh](file://cron_daily_query.sh) performs mutual exclusion, sentinel checks, pre-flight verification, runs three subsite queries, aggregates summaries, optionally backfills screenshots via Phase B, and cleans old artifacts.
- Core CLI: [zxgk_query.py](file://zxgk_query.py) encapsulates browser automation, captcha solving, query execution, pagination, screenshot capture, and structured output.
- Writers: [writers/sqlite.py](file://writers/sqlite.py) writes batch results to a local SQLite database; [writers/feishu.py](file://writers/feishu.py) writes to Feishu tables and optionally uploads screenshots.
- ScreenshotBackfiller: [zxgk/backfill.py](file://zxgk/backfill.py) implements Phase B screenshot recovery system that queries missing screenshots and performs targeted re-capture and upload operations.
- BatchRunner: [zxgk/runner.py](file://zxgk/runner.py) manages the core batch execution workflow with WAF awareness and progress tracking.
- CLI Integration: [zxgk/cli.py](file://zxgk/cli.py) provides command-line interface with backfill mode support and argument parsing.
- Captcha solver: [captcha-solver/main.py](file://captcha-solver/main.py) exposes health and solve endpoints; supports Docker deployment via [docker-compose.yml](file://captcha-solver/docker-compose.yml).
- Configuration: [config/zxgk.yaml](file://config/zxgk.yaml) defines subsites, browser, WAF, screenshots, Feishu mapping, and defaults; [config/companies.txt](file://config/companies.txt) lists companies to query.
- Diagnostics and validation: [diagnose_subsites.py](file://diagnose_subsites.py) probes DOM structures; [smoke_test.sh](file://smoke_test.sh) validates environment and outputs.

**Section sources**
- [cron_daily_query.sh:1-246](file://cron_daily_query.sh#L1-L246)
- [zxgk_query.py:1-800](file://zxgk_query.py#L1-L800)
- [writers/sqlite.py:1-121](file://writers/sqlite.py#L1-L121)
- [writers/feishu.py:1-596](file://writers/feishu.py#L1-L596)
- [zxgk/backfill.py:1-296](file://zxgk/backfill.py#L1-L296)
- [zxgk/runner.py:1-278](file://zxgk/runner.py#L1-L278)
- [zxgk/cli.py:1-321](file://zxgk/cli.py#L1-L321)
- [config/zxgk.yaml:1-102](file://config/zxgk.yaml#L1-L102)
- [config/companies.txt:1-6](file://config/companies.txt#L1-L6)
- [diagnose_subsites.py:1-429](file://diagnose_subsites.py#L1-L429)
- [smoke_test.sh:1-155](file://smoke_test.sh#L1-L155)

## Architecture Overview
The workflow is a multi-stage pipeline orchestrated by a single shell script, with robust error handling and optional Feishu integration. The system now operates in two distinct phases: Phase A (initial data collection) and Phase B (screenshot backfill).

```mermaid
sequenceDiagram
participant Cron as "Scheduler"
participant Orchestrator as "cron_daily_query.sh"
participant Venv as "Python venv"
participant Captcha as "captcha-solver"
participant CLI as "zxgk_query.py"
participant Runner as "BatchRunner"
participant Backfill as "ScreenshotBackfiller"
participant SQLite as "writers/sqlite.py"
participant Feishu as "writers/feishu.py"
Cron->>Orchestrator : Invoke daily
Orchestrator->>Venv : Activate environment
Orchestrator->>Captcha : Health check (localhost : 8001)
alt Not healthy
Orchestrator->>Captcha : Launch via Docker or venv
end
Orchestrator->>CLI : Run subsite queries (zhixing, shixin, xgl)
CLI->>Runner : Execute batch queries
Runner->>Captcha : Solve captchas
Runner-->>Orchestrator : Batch JSON per subsite
Orchestrator->>SQLite : Write results (always)
alt Feishu configured
Orchestrator->>Feishu : Write raw tables + cross-ref
end
Orchestrator->>Orchestrator : Aggregate summary JSON
Orchestrator->>Feishu : Wait for computation (30s)
Orchestrator->>Backfill : Phase B screenshot backfill
Backfill->>Feishu : Query missing screenshots
Backfill->>Captcha : Solve captchas for re-capture
Backfill->>Backfill : Search companies and capture screenshots
Backfill->>Feishu : Upload missing screenshots
Orchestrator->>Orchestrator : Cleanup old artifacts
```

**Diagram sources**
- [cron_daily_query.sh:1-246](file://cron_daily_query.sh#L1-L246)
- [zxgk_query.py:1-800](file://zxgk_query.py#L1-L800)
- [zxgk/runner.py:1-278](file://zxgk/runner.py#L1-L278)
- [zxgk/backfill.py:1-296](file://zxgk/backfill.py#L1-L296)
- [writers/sqlite.py:1-121](file://writers/sqlite.py#L1-L121)
- [writers/feishu.py:1-596](file://writers/feishu.py#L1-L596)
- [captcha-solver/main.py:1-215](file://captcha-solver/main.py#L1-L215)

## Detailed Component Analysis

### Orchestrator: cron_daily_query.sh
Responsibilities:
- Mutual exclusion via lock directory and sentinel file
- Pre-flight checks: captcha-solver health, lark-cli auth
- Per-subsite execution with independent failure handling
- Local SQLite backup and optional Feishu writes
- Summary aggregation and Phase B screenshot backfill
- Artifact cleanup and logging

Key behaviors:
- Locking prevents concurrent runs; sentinel avoids re-execution on the same day
- Subsite runner function executes CLI, logs to both terminal and file, writes SQLite, conditionally Feishu
- Summary JSON consolidates counts and statuses across subsites
- Optional backfill waits for Feishu computation then re-queries missing screenshots using the dedicated ScreenshotBackfiller

```mermaid
flowchart TD
Start(["Start"]) --> Lock["Create lock dir<br/>Exit if exists"]
Lock --> Sentinel["Check daily sentinel<br/>Exit if exists"]
Sentinel --> Preflight["Pre-flight checks:<br/>captcha-solver health<br/>lark-cli auth"]
Preflight --> RunSubsites["Run subsites:<br/>zhixing → shixin → xgl"]
RunSubsites --> SQLiteWrite["Write SQLite"]
SQLiteWrite --> FeishuCheck{"Feishu configured?"}
FeishuCheck --> |Yes| FeishuWrite["Write Feishu raw + cross-ref"]
FeishuCheck --> |No| SkipFeishu["Skip Feishu"]
FeishuWrite --> Summary["Generate summary JSON"]
SkipFeishu --> Summary
Summary --> BackfillCheck{"Feishu configured?"}
BackfillCheck --> |Yes| WaitCompute["Wait 30s for Feishu compute"]
BackfillCheck --> |No| Done
WaitCompute --> Backfill["Execute ScreenshotBackfiller.run()"]
Backfill --> Cleanup["Cleanup old artifacts"]
Cleanup --> Done(["Done"])
```

**Diagram sources**
- [cron_daily_query.sh:16-246](file://cron_daily_query.sh#L16-L246)

**Section sources**
- [cron_daily_query.sh:16-246](file://cron_daily_query.sh#L16-L246)

### Core CLI: zxgk_query.py
Responsibilities:
- Browser lifecycle management with stealth and cleanup
- Navigation to subsites, WAF detection, retries
- Captcha extraction and solving via external service
- Form submission, result parsing, pagination, and de-duplication by viewId
- Screenshot capture and optional upload mapping
- Structured JSON output for downstream writers
- Backfill mode support for targeted screenshot recovery

Design highlights:
- Modular classes: BrowserManager, CaptchaSolver, QueryEngine, DetailScreenshot, ScreenshotBackfiller
- Robust error handling: WAF blocked, navigation errors, captcha unavailable
- Extensive logging and signal handlers for graceful shutdown
- Dedicated backfill mode for Phase B screenshot recovery

```mermaid
classDiagram
class BrowserManager {
+bool headless
+dict config
+launch()
+navigate(subsite)
+close()
-_cleanup_orphans()
}
class CaptchaSolver {
+str server_url
+health_check() bool
+get_captcha(page) str
+solve(b64) (str, float)
+refresh(page) void
}
class QueryEngine {
+int max_retries
+str subsite
+query(company) list
-_submit() void
-_dismiss_dialogs() void
-_collect_all_pages() list
}
class DetailScreenshot {
+capture_all(records) map
-_capture_one(view_id, idx, case_no) str
}
class ScreenshotBackfiller {
+str batch_id
+int max_per_session
+run() void
+find_missing_screenshots() list
+backfill_batch(records) void
}
class BatchRunner {
+run(companies) dict
+_write_feishu(records, screenshot_map) void
+_save_result(company, records, screenshot_map) void
}
BrowserManager --> CaptchaSolver : "uses"
BrowserManager --> QueryEngine : "provides page"
QueryEngine --> CaptchaSolver : "calls"
QueryEngine --> DetailScreenshot : "optional"
ScreenshotBackfiller --> BrowserManager : "uses"
BatchRunner --> QueryEngine : "uses"
BatchRunner --> DetailScreenshot : "optional"
```

**Diagram sources**
- [zxgk_query.py:175-772](file://zxgk_query.py#L175-L772)
- [zxgk/backfill.py:12-296](file://zxgk/backfill.py#L12-L296)
- [zxgk/runner.py:15-278](file://zxgk/runner.py#L15-L278)

**Section sources**
- [zxgk_query.py:175-772](file://zxgk_query.py#L175-L772)
- [zxgk/backfill.py:12-296](file://zxgk/backfill.py#L12-L296)
- [zxgk/runner.py:15-278](file://zxgk/runner.py#L15-L278)

### ScreenshotBackfiller: Phase B Screenshot Recovery System
**New Component** - The ScreenshotBackfiller class implements a sophisticated two-phase workflow designed to recover missing screenshots from the Feishu case master table.

Responsibilities:
- Query Feishu case master table for records with empty screenshot fields
- Extract real viewIds from raw table DuplexLink relationships
- Group missing records by company for efficient batch processing
- Navigate to zhixing subsite, search companies, and solve captchas
- Capture screenshots for missing records and upload to Feishu
- Update case master table with uploaded screenshot file tokens

Key Features:
- **Targeted Recovery**: Only processes records with missing screenshots, avoiding unnecessary work
- **ViewId Resolution**: Uses DuplexLink relationships to get accurate viewIds from raw records
- **Company Grouping**: Processes companies in batches to minimize repeated navigation
- **Robust Error Handling**: Handles captcha failures, search failures, and upload errors gracefully
- **Progress Tracking**: Maintains success/failure counters and logs detailed progress

```mermaid
flowchart TD
Start(["ScreenshotBackfiller.run()"]) --> FindMissing["find_missing_screenshots()"]
FindMissing --> CheckRecords{"Any missing records?"}
CheckRecords --> |No| Skip["Skip backfill"]
CheckRecords --> |Yes| GroupByCompany["Group by company"]
GroupByCompany --> InitBrowser["Initialize BrowserManager"]
InitBrowser --> Navigate["Navigate to zhixing"]
Navigate --> ProcessCompanies["Process companies in order"]
ProcessCompanies --> SearchCompany["Search company and solve captcha"]
SearchCompany --> LoopRecords["Loop missing records for company"]
LoopRecords --> CaptureDetail["_capture_detail(view_id)"]
CaptureDetail --> UploadMedia["Upload to Feishu media"]
UploadMedia --> UpdateRecord["Update case master record"]
UpdateRecord --> NextRecord["Next record"]
NextRecord --> |More| LoopRecords
NextRecord --> |None| NextCompany["Next company"]
NextCompany --> |More| ProcessCompanies
NextCompany --> |None| Complete["Complete backfill"]
Skip --> End(["End"])
Complete --> End
```

**Diagram sources**
- [zxgk/backfill.py:286-296](file://zxgk/backfill.py#L286-L296)
- [zxgk/backfill.py:60-116](file://zxgk/backfill.py#L60-L116)
- [zxgk/backfill.py:118-191](file://zxgk/backfill.py#L118-L191)

**Section sources**
- [zxgk/backfill.py:1-296](file://zxgk/backfill.py#L1-L296)

### Writers: SQLite and Feishu
- SQLite writer: [writers/sqlite.py](file://writers/sqlite.py) writes per-subsite tables, supports storing screenshot paths or binary data, and migrates schema on demand.
- Feishu writer: [writers/feishu.py](file://writers/feishu.py) writes raw tables, optionally updates cross-references in the case master table, and uploads screenshots to the master table. It uses lark-cli for API calls and media uploads.

```mermaid
sequenceDiagram
participant Orchestrator as "cron_daily_query.sh"
participant SQLite as "writers/sqlite.py"
participant Feishu as "writers/feishu.py"
Orchestrator->>SQLite : Write batch JSON to SQLite
alt Feishu configured
Orchestrator->>Feishu : Write raw tables
Orchestrator->>Feishu : Cross-reference case master
Orchestrator->>Feishu : Upload screenshots
else
Orchestrator->>Orchestrator : Skip Feishu
end
```

**Diagram sources**
- [writers/sqlite.py:37-100](file://writers/sqlite.py#L37-L100)
- [writers/feishu.py:154-478](file://writers/feishu.py#L154-L478)

**Section sources**
- [writers/sqlite.py:1-121](file://writers/sqlite.py#L1-L121)
- [writers/feishu.py:1-596](file://writers/feishu.py#L1-L596)

### Captcha Solver Service
- [captcha-solver/main.py](file://captcha-solver/main.py) exposes health and solve endpoints, validates images, and logs requests.
- Deployment: [docker-compose.yml](file://captcha-solver/docker-compose.yml) and [Dockerfile](file://captcha-solver/Dockerfile) enable containerized OCR with PaddleOCR.

```mermaid
graph TB
Client["Browser/CLI"] --> API["/health and /solve endpoints"]
API --> OCR["PaddleOCR model"]
API --> Logger["Logging"]
```

**Diagram sources**
- [captcha-solver/main.py:107-215](file://captcha-solver/main.py#L107-L215)
- [captcha-solver/docker-compose.yml:1-13](file://captcha-solver/docker-compose.yml#L1-L13)
- [captcha-solver/Dockerfile:1-22](file://captcha-solver/Dockerfile#L1-L22)

**Section sources**
- [captcha-solver/main.py:1-215](file://captcha-solver/main.py#L1-L215)
- [captcha-solver/docker-compose.yml:1-13](file://captcha-solver/docker-compose.yml#L1-L13)
- [captcha-solver/Dockerfile:1-22](file://captcha-solver/Dockerfile#L1-L22)

### Diagnostics and Validation
- [diagnose_subsites.py](file://diagnose_subsites.py) probes DOM structures, captures table info, pagination, and attempts a test search with OCR.
- [smoke_test.sh](file://smoke_test.sh) validates Python/Shell syntax, YAML config, environment variables, venv, and recent batch JSON format.

**Section sources**
- [diagnose_subsites.py:1-429](file://diagnose_subsites.py#L1-L429)
- [smoke_test.sh:1-155](file://smoke_test.sh#L1-L155)

## Dependency Analysis
- Orchestrator depends on:
  - Python virtual environment and activated packages
  - Captcha solver service availability
  - Feishu CLI authentication (optional)
  - Configuration and company list files
- Core CLI depends on:
  - Playwright Chromium installation
  - Captcha solver service
  - Feishu app token (optional)
  - ScreenshotBackfiller for Phase B operations
- Writers depend on:
  - SQLite for local persistence
  - Feishu APIs via lark-cli (optional)
- ScreenshotBackfiller depends on:
  - Feishu case master table structure
  - DuplexLink relationships between raw and case tables
  - Browser automation for re-capturing screenshots

```mermaid
graph LR
CRON["cron_daily_query.sh"] --> ZHQ["zxgk_query.py"]
CRON --> WSQL["writers/sqlite.py"]
CRON --> WFS["writers/feishu.py"]
CRON --> BACKFILL["zxgk/backfill.py"]
ZHQ --> CAP["captcha-solver/main.py"]
ZHQ --> CFG["config/zxgk.yaml"]
ZHQ --> COMPS["config/companies.txt"]
ZHQ --> RUNNER["zxgk/runner.py"]
RUNNER --> BACKFILL
BACKFILL --> WFS
WFS --> CFG
```

**Diagram sources**
- [cron_daily_query.sh:1-246](file://cron_daily_query.sh#L1-L246)
- [zxgk_query.py:1-800](file://zxgk_query.py#L1-L800)
- [writers/sqlite.py:1-121](file://writers/sqlite.py#L1-L121)
- [writers/feishu.py:1-596](file://writers/feishu.py#L1-L596)
- [zxgk/backfill.py:1-296](file://zxgk/backfill.py#L1-L296)
- [zxgk/runner.py:1-278](file://zxgk/runner.py#L1-L278)
- [config/zxgk.yaml:1-102](file://config/zxgk.yaml#L1-L102)
- [config/companies.txt:1-6](file://config/companies.txt#L1-L6)
- [captcha-solver/main.py:1-215](file://captcha-solver/main.py#L1-L215)

**Section sources**
- [cron_daily_query.sh:1-246](file://cron_daily_query.sh#L1-L246)
- [zxgk_query.py:1-800](file://zxgk_query.py#L1-L800)
- [writers/sqlite.py:1-121](file://writers/sqlite.py#L1-L121)
- [writers/feishu.py:1-596](file://writers/feishu.py#L1-L596)
- [zxgk/backfill.py:1-296](file://zxgk/backfill.py#L1-L296)
- [zxgk/runner.py:1-278](file://zxgk/runner.py#L1-L278)
- [config/zxgk.yaml:1-102](file://config/zxgk.yaml#L1-L102)
- [config/companies.txt:1-6](file://config/companies.txt#L1-L6)
- [captcha-solver/main.py:1-215](file://captcha-solver/main.py#L1-L215)

## Performance Considerations
- Concurrency and isolation:
  - Mutual exclusion via lock directory prevents overlapping runs; sentinel avoids redundant executions on the same day.
- Resource limits:
  - Captcha solver Docker service sets memory limit; adjust as needed for your environment.
- Browser and network:
  - Headless mode reduces overhead; viewport and stealth settings improve compatibility.
- Retry and throttling:
  - WAF retry and cooldown parameters reduce blocking; screenshot intervals prevent rate limiting.
- Storage:
  - SQLite provides zero-dependency local persistence; consider BLOB storage for screenshots if disk space allows.
- Monitoring:
  - Daily summary JSON and detailed logs facilitate quick diagnostics.
- **Phase B Optimization**:
  - Company grouping minimizes repeated navigation and captcha solving
  - Session-based processing reduces browser startup overhead
  - Configurable max_per_session prevents overwhelming the system

## Troubleshooting Guide
Common issues and resolutions:
- Captcha solver not running:
  - Orchestrator attempts Docker and falls back to venv; verify port 8001 and process conflicts.
- Feishu not configured:
  - Lark-cli auth check sets a flag; Feishu steps are skipped; configure token and tables to enable.
- WAF blocked:
  - CLI detects absence of captcha element and retries with cooldown; review navigation selectors and extra waits.
- No results:
  - CLI returns non-zero exit code; verify company names and subsite-specific fields (e.g., province selection for shixin).
- OCR failures:
  - Low-confidence predictions trigger captcha refresh; ensure captcha-solver health and image quality.
- **Phase B Issues**:
  - Missing screenshots: Verify Feishu case master table has records with empty screenshot fields
  - ViewId resolution failures: Check DuplexLink relationships between raw and case tables
  - Company search failures: Ensure companies still exist in the system and haven't been removed
  - Upload failures: Verify Feishu media storage capacity and file permissions
- Diagnostics:
  - Use [diagnose_subsites.py](file://diagnose_subsites.py) to probe DOM structures and test search flow.
- Smoke testing:
  - Use [smoke_test.sh](file://smoke_test.sh) to validate environment, configs, and recent batch JSON.

**Section sources**
- [cron_daily_query.sh:48-96](file://cron_daily_query.sh#L48-L96)
- [zxgk_query.py:297-324](file://zxgk_query.py#L297-L324)
- [writers/feishu.py:29-33](file://writers/feishu.py#L29-L33)
- [smoke_test.sh:106-143](file://smoke_test.sh#L106-L143)

## Conclusion
The daily workflow orchestration integrates a robust shell orchestrator, a resilient browser automation core, and pluggable storage writers. The system now features a sophisticated two-phase approach with dedicated screenshot backfill capabilities that address critical missing screenshot recovery needs. It ensures reliability through mutual exclusion, sentinel checks, WAF-aware retries, and optional Feishu integration. With diagnostics and smoke tests, operators can maintain and troubleshoot the system effectively while optimizing performance and resource usage.

## Appendices

### Practical Cron Job Configuration
- Schedule the orchestrator to run daily at a chosen time:
  - Example: run at 02:15 UTC for Beijing-time morning processing
  - Command: [cron_daily_query.sh](file://cron_daily_query.sh)
- Ensure environment:
  - Source virtual environment and set required variables before invoking the script
  - Confirm Feishu token if enabling Feishu writes

### Environment Setup
- Install prerequisites and dependencies:
  - Use [setup.sh](file://setup.sh) to install Python venv, Playwright Chromium, lark-cli, and optional PaddleOCR
- Configure:
  - Copy and edit [config/zxgk.yaml](file://config/zxgk.yaml) and [config/companies.txt](file://config/companies.txt)
  - Set environment variable FEISHU_APP_TOKEN for Feishu integration

**Section sources**
- [setup.sh:1-150](file://setup.sh#L1-L150)
- [config/zxgk.yaml:1-102](file://config/zxgk.yaml#L1-L102)
- [config/companies.txt:1-6](file://config/companies.txt#L1-L6)

### Monitoring Approaches
- Logs:
  - Orchestrator writes to a dated log file and prints summary location
- Summaries:
  - Daily summary JSON aggregated per subsite for downstream AI consumption
- Health checks:
  - Captcha solver health endpoint and lark-cli auth check included in orchestrator
- **Phase B Monitoring**:
  - Detailed logging of missing screenshot counts and recovery progress
  - Success/failure counters for targeted recovery operations

**Section sources**
- [cron_daily_query.sh:35-40](file://cron_daily_query.sh#L35-L40)
- [cron_daily_query.sh:166-210](file://cron_daily_query.sh#L166-L210)
- [captcha-solver/main.py:107-109](file://captcha-solver/main.py#L107-L109)

### Backup and Recovery
- Local backup:
  - SQLite database serves as primary local backup; consider periodic off-machine copies
- Cleanup policy:
  - Orchestrator removes old progress, single-company JSON, summary JSON, batch JSON, and screenshots older than thresholds
- Recovery:
  - Re-run orchestrator to regenerate missing summaries and backfill screenshots if Feishu was enabled
- **Phase B Recovery**:
  - ScreenshotBackfiller automatically handles partial failures and continues with remaining records
  - Progress tracking enables resuming interrupted backfill operations

**Section sources**
- [writers/sqlite.py:37-100](file://writers/sqlite.py#L37-L100)
- [cron_daily_query.sh:233-239](file://cron_daily_query.sh#L233-L239)
- [zxgk/backfill.py:142-191](file://zxgk/backfill.py#L142-L191)

### Customization and Extension
- Add new subsites:
  - Extend [config/zxgk.yaml](file://config/zxgk.yaml) subsites section with name, CSS selector, and extra wait seconds
- Modify storage:
  - Use [writers/sqlite.py](file://writers/sqlite.py) or implement a new writer module under [writers/](file://writers/)
- Integrate new outputs:
  - Extend orchestrator to call additional writers or post-processing scripts
- Diagnose DOM changes:
  - Use [diagnose_subsites.py](file://diagnose_subsites.py) to probe and update selectors
- **Extend Backfill Capabilities**:
  - Modify ScreenshotBackfiller to handle additional screenshot types or different storage systems
  - Adjust company grouping logic for different processing patterns
  - Customize error handling and retry strategies for specific environments

**Section sources**
- [config/zxgk.yaml:28-42](file://config/zxgk.yaml#L28-L42)
- [writers/__init__.py:1-10](file://writers/__init__.py#L1-L10)
- [diagnose_subsites.py:25-48](file://diagnose_subsites.py#L25-L48)
- [zxgk/backfill.py:12-296](file://zxgk/backfill.py#L12-L296)

### Two-Phase Workflow Details
**Phase A (Initial Collection)**:
- Executes batch queries across all three subsites
- Captures screenshots during initial data collection
- Writes raw tables to Feishu with cross-references
- Generates comprehensive batch JSON for downstream processing

**Phase B (Screenshot Recovery)**:
- Queries Feishu case master table for missing screenshots
- Resolves real viewIds from DuplexLink relationships
- Performs targeted re-captures and uploads
- Updates case master records with recovered screenshots
- Provides granular progress tracking and error reporting

**Section sources**
- [cron_daily_query.sh:213-228](file://cron_daily_query.sh#L213-L228)
- [zxgk/backfill.py:12-296](file://zxgk/backfill.py#L12-L296)
- [writers/feishu.py:44-85](file://writers/feishu.py#L44-L85)