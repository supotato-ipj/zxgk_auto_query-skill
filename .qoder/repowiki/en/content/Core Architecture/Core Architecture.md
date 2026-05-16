# Core Architecture

<cite>
**Referenced Files in This Document**
- [README.md](file://README.md)
- [SKILL.md](file://SKILL.md)
- [zxgk_query.py](file://zxgk_query.py)
- [diagnose_subsites.py](file://diagnose_subsites.py)
- [cron_daily_query.sh](file://cron_daily_query.sh)
- [setup.sh](file://setup.sh)
- [smoke_test.sh](file://smoke_test.sh)
- [config/zxgk.example.yaml](file://config/zxgk.example.yaml)
- [writers/__init__.py](file://writers/__init__.py)
- [writers/sqlite.py](file://writers/sqlite.py)
- [writers/excel.py](file://writers/excel.py)
- [writers/feishu.py](file://writers/feishu.py)
- [writers/feishu_build.py](file://writers/feishu_build.py)
- [captcha-solver/main.py](file://captcha-solver/main.py)
</cite>

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
This document describes the Execution Information Query System’s core architecture, focusing on the browser automation pipeline, CAPTCHA solving subsystem, multi-subsite navigation patterns, and the extensible output writer ecosystem. It explains how CLI commands orchestrate Playwright-driven queries against the China Enforcement Information Public Network, how OCR-based CAPTCHA resolution is integrated, and how results are persisted locally and optionally synchronized to Feishu. It also documents system boundaries, integration patterns with external services, error handling strategies, and performance characteristics.

## Project Structure
The system is organized into cohesive modules:
- CLI and orchestration: main automation and scheduling
- Browser automation: stealth Chromium via Playwright
- CAPTCHA solver: OCR service for验证码 recognition
- Writers: pluggable output backends (SQLite, Excel, Feishu)
- Diagnostics and setup: environment validation and site probing
- Configuration: YAML-driven runtime configuration

```mermaid
graph TB
subgraph "CLI and Orchestration"
CLI["zxgk_query.py<br/>CLI + BatchRunner"]
CRON["cron_daily_query.sh<br/>Daily orchestrator"]
SETUP["setup.sh<br/>Environment bootstrap"]
SMOKE["smoke_test.sh<br/>Validation"]
end
subgraph "Browser Automation"
BM["BrowserManager<br/>Playwright + stealth"]
QE["QueryEngine<br/>Search + pagination"]
DS["DetailScreenshot<br/>Popup extraction"]
end
subgraph "CAPTCHA Solver"
CAPT["CaptchaSolver<br/>OCR client"]
OCR["captcha-solver/main.py<br/>FastAPI OCR service"]
end
subgraph "Output Writers"
SQLITE["writers/sqlite.py"]
EXCEL["writers/excel.py"]
FEISHU["writers/feishu.py"]
FBUILD["writers/feishu_build.py"]
end
CFG["config/zxgk.example.yaml"]
CLI --> BM
CLI --> QE
CLI --> DS
CLI --> CAPT
CLI --> SQLITE
CLI --> EXCEL
CLI --> FEISHU
CRON --> CLI
CRON --> SQLITE
CRON --> FEISHU
CRON --> FBUILD
SETUP --> CLI
SETUP --> OCR
SMOKE --> CLI
SMOKE --> OCR
BM --> CAPT
CAPT --> OCR
QE --> DS
FEISHU --> FBUILD
CLI -.-> CFG
CRON -.-> CFG
```

**Diagram sources**
- [zxgk_query.py:175-324](file://zxgk_query.py#L175-L324)
- [zxgk_query.py:328-392](file://zxgk_query.py#L328-L392)
- [captcha-solver/main.py:107-142](file://captcha-solver/main.py#L107-L142)
- [writers/sqlite.py:37-100](file://writers/sqlite.py#L37-L100)
- [writers/excel.py:56-73](file://writers/excel.py#L56-L73)
- [writers/feishu.py:556-591](file://writers/feishu.py#L556-L591)
- [writers/feishu_build.py:109-201](file://writers/feishu_build.py#L109-L201)
- [cron_daily_query.sh:112-154](file://cron_daily_query.sh#L112-L154)
- [config/zxgk.example.yaml:1-103](file://config/zxgk.example.yaml#L1-L103)

**Section sources**
- [README.md:97-122](file://README.md#L97-L122)
- [SKILL.md:225-247](file://SKILL.md#L225-L247)

## Core Components
- CLI and Orchestration
  - Command-line entry point with subcommands for single, batch, backfill, and diagnose modes.
  - Daily orchestration script coordinates three subsites, writes to SQLite, conditionally to Feishu, and triggers Phase B screenshot backfill.
- BrowserManager
  - Launches a stealth Chromium session, navigates to subsites, and handles WAF detection and retries.
- QueryEngine
  - Performs search, handles CAPTCHA OCR, dismisses overlays, collects paginated results, and ensures viewId de-duplication.
- CaptchaSolver
  - Extracts CAPTCHA images from the page, posts to OCR service, and applies confidence thresholds.
- DetailScreenshot
  - Captures detail popups, crops to popup region using OpenCV heuristics, and closes dialogs.
- Writers
  - SQLite writer persists batch results locally with optional screenshot storage as file path or BLOB.
  - Excel writer exports tabular results for reporting.
  - Feishu writer writes raw tables, performs cross-reference updates, and uploads screenshots to Feishu.
  - Feishu build writer automates table creation and initial data population.

**Section sources**
- [zxgk_query.py:1514-1567](file://zxgk_query.py#L1514-L1567)
- [cron_daily_query.sh:112-154](file://cron_daily_query.sh#L112-L154)
- [writers/sqlite.py:37-100](file://writers/sqlite.py#L37-L100)
- [writers/excel.py:56-73](file://writers/excel.py#L56-L73)
- [writers/feishu.py:556-591](file://writers/feishu.py#L556-L591)
- [writers/feishu_build.py:109-201](file://writers/feishu_build.py#L109-L201)

## Architecture Overview
The system follows a staged pipeline:
- Input: company list and configuration
- Automation: stealth browser navigates subsites, submits queries, and collects results
- OCR: CAPTCHA images are sent to OCR service for text extraction
- Storage: results saved to SQLite; optional Feishu synchronization and screenshot uploads
- Backfill: Phase B re-queries missing screenshots and uploads them to Feishu

```mermaid
sequenceDiagram
participant User as "Operator"
participant CLI as "CLI (zxgk_query.py)"
participant Cron as "Scheduler (cron_daily_query.sh)"
participant BM as "BrowserManager"
participant QE as "QueryEngine"
participant CAPT as "CaptchaSolver"
participant OCR as "OCR Service (FastAPI)"
participant DS as "DetailScreenshot"
participant SQL as "SQLite Writer"
participant FS as "Feishu Writer"
User->>CLI : Run single/batch/backfill
CLI->>BM : Launch stealth Chromium
BM->>BM : Navigate to subsite
BM->>QE : Prepare page for search
loop For each company
QE->>CAPT : Refresh CAPTCHA
CAPT->>OCR : POST /solve/base64
OCR-->>CAPT : {text, confidence}
CAPT-->>QE : OCR result
QE->>QE : Submit search, dismiss overlays
QE->>QE : Collect pages, de-duplicate viewIds
alt Screenshots enabled
QE->>DS : Capture detail popups
DS-->>QE : Screenshot map
end
QE-->>CLI : Records + screenshot map
CLI->>SQL : Write batch to SQLite
opt Feishu enabled
CLI->>FS : Write raw table + cross-ref + upload screenshots
end
end
Note over CLI,FS : Phase B backfill triggered by scheduler
```

**Diagram sources**
- [zxgk_query.py:1065-1197](file://zxgk_query.py#L1065-L1197)
- [zxgk_query.py:328-392](file://zxgk_query.py#L328-L392)
- [captcha-solver/main.py:174-209](file://captcha-solver/main.py#L174-L209)
- [writers/sqlite.py:37-100](file://writers/sqlite.py#L37-L100)
- [writers/feishu.py:556-591](file://writers/feishu.py#L556-L591)
- [cron_daily_query.sh:112-154](file://cron_daily_query.sh#L112-L154)

## Detailed Component Analysis

### Browser Automation and Navigation
- Stealth browser initialization
  - Chromium launched with sandbox disabled and stealth overrides to mimic a real browser.
  - Locale and headers configured for Chinese sites.
- Multi-subsite navigation
  - Uses CSS selectors defined per subsite to click into “zhixing”, “shixin”, and “xgl”.
  - WAF detection checks for presence of CAPTCHA element and body length; on block, retries with cooldown.
- Retry and resilience
  - Navigation retried up to three times; browser closed and relaunched after consecutive failures.

```mermaid
flowchart TD
Start(["Launch Browser"]) --> Nav["Navigate to subsite"]
Nav --> WAF{"WAF check: #yzm present?"}
WAF --> |No| Retry["Retry with cooldown"]
Retry --> WAF
WAF --> |Yes| Ready["Ready for search"]
Ready --> End(["Proceed to search"])
```

**Diagram sources**
- [zxgk_query.py:195-277](file://zxgk_query.py#L195-L277)

**Section sources**
- [zxgk_query.py:175-277](file://zxgk_query.py#L175-L277)
- [config/zxgk.example.yaml:32-44](file://config/zxgk.example.yaml#L32-L44)

### CAPTCHA Solving System
- Client-side extraction
  - Captcha image located within the CAPTCHA container and drawn to canvas for data URL conversion.
- OCR service integration
  - Requests sent to OCR endpoint with base64 payload and preprocessing mode.
  - Health-checked before use; on failure, the pipeline aborts early.
- Confidence gating
  - Results below a threshold are rejected and the CAPTCHA is refreshed.

```mermaid
sequenceDiagram
participant QE as "QueryEngine"
participant CAPT as "CaptchaSolver"
participant OCR as "OCR Service"
QE->>CAPT : get_captcha(page)
CAPT->>OCR : POST /solve/base64 {image, preprocess}
OCR-->>CAPT : {text, confidence}
CAPT-->>QE : (text, confidence)
alt confidence < threshold
CAPT->>CAPT : refresh(page)
end
```

**Diagram sources**
- [zxgk_query.py:339-392](file://zxgk_query.py#L339-L392)
- [captcha-solver/main.py:174-209](file://captcha-solver/main.py#L174-L209)

**Section sources**
- [zxgk_query.py:328-392](file://zxgk_query.py#L328-L392)
- [captcha-solver/main.py:107-142](file://captcha-solver/main.py#L107-L142)

### Multi-Subsite Navigation Patterns
- Configuration-driven selectors
  - Each subsite defines a CSS selector and optional extra wait seconds.
- Special handling
  - “shixin” requires explicit province selection to “all”.
- Consistent result collection
  - Pagination loop reads rows, extracts viewIds, and de-duplicates across pages.

```mermaid
flowchart TD
A["Load subsite config"] --> B["Click CSS selector"]
B --> C["Wait for networkidle"]
C --> D{"Subsite special?"}
D --> |shixin| E["Set province=all"]
D --> |other| F["Skip"]
E --> G["Collect rows"]
F --> G
G --> H["De-duplicate by viewId"]
```

**Diagram sources**
- [zxgk_query.py:416-476](file://zxgk_query.py#L416-L476)
- [config/zxgk.example.yaml:32-44](file://config/zxgk.example.yaml#L32-L44)

**Section sources**
- [zxgk_query.py:416-476](file://zxgk_query.py#L416-L476)
- [config/zxgk.example.yaml:32-44](file://config/zxgk.example.yaml#L32-L44)

### Output Writers and Extensibility
- Plugin-style writers
  - Each writer module exposes a write() function; writers are invoked independently.
- SQLite writer
  - Zero-dependency persistence; supports storing screenshot paths or BLOBs.
- Excel writer
  - Exports tabular results for reporting; requires optional dependency.
- Feishu writer
  - Writes raw tables, performs cross-reference updates, and uploads screenshots to Feishu.
- Feishu build writer
  - Automates table creation, DuplexLink setup, and initial data population.

```mermaid
classDiagram
class BatchRunner {
+run(companies)
+save_batch_json(path)
}
class SQLiteWriter {
+write_batch(json_path, db_path, store_screenshots)
}
class ExcelWriter {
+write_batch(json_files, output_path)
}
class FeishuWriter {
+write_raw_table(records, subsite)
+cross_ref_update(subsite)
+upload_screenshots_for_records(records, screenshots_dir, subsite)
}
class FeishuBuildWriter {
+create_table(...)
+add_field(...)
+add_records(...)
+upload_media(...)
}
BatchRunner --> SQLiteWriter : "writes"
BatchRunner --> ExcelWriter : "writes"
BatchRunner --> FeishuWriter : "writes"
FeishuWriter <.. FeishuBuildWriter : "shared constants"
```

**Diagram sources**
- [writers/sqlite.py:37-100](file://writers/sqlite.py#L37-L100)
- [writers/excel.py:56-73](file://writers/excel.py#L56-L73)
- [writers/feishu.py:154-201](file://writers/feishu.py#L154-L201)
- [writers/feishu.py:208-277](file://writers/feishu.py#L208-L277)
- [writers/feishu.py:369-478](file://writers/feishu.py#L369-L478)
- [writers/feishu_build.py:109-201](file://writers/feishu_build.py#L109-L201)

**Section sources**
- [writers/__init__.py:1-10](file://writers/__init__.py#L1-L10)
- [writers/sqlite.py:37-100](file://writers/sqlite.py#L37-L100)
- [writers/excel.py:56-73](file://writers/excel.py#L56-L73)
- [writers/feishu.py:154-201](file://writers/feishu.py#L154-L201)
- [writers/feishu.py:208-277](file://writers/feishu.py#L208-L277)
- [writers/feishu.py:369-478](file://writers/feishu.py#L369-L478)
- [writers/feishu_build.py:109-201](file://writers/feishu_build.py#L109-L201)

### Data Flow from Input to Output
- Input: company list (YAML or plain text) and configuration (YAML).
- Automation: CLI loads config, launches browser, navigates subsites, runs queries, captures screenshots.
- Storage: batch JSON produced per company; merged batch JSON aggregated; SQLite backup; optional Feishu writes.
- Backfill: Phase B scans Feishu for missing screenshots and re-queries details to upload.

```mermaid
flowchart TD
In["Companies.txt / YAML"] --> LoadCfg["Load config (YAML)"]
LoadCfg --> RunCLI["Run CLI (single/batch)"]
RunCLI --> BM["BrowserManager"]
RunCLI --> QE["QueryEngine"]
RunCLI --> DS["DetailScreenshot"]
RunCLI --> CAPT["CaptchaSolver"]
CAPT --> OCR["OCR Service"]
QE --> OutJSON["Per-company JSON"]
OutJSON --> Merge["Merge to batch JSON"]
Merge --> SQLite["SQLite Writer"]
Merge --> Feishu["Feishu Writer"]
Feishu --> Backfill["Phase B: Screenshot Backfill"]
Backfill --> Feishu
```

**Diagram sources**
- [zxgk_query.py:1484-1494](file://zxgk_query.py#L1484-L1494)
- [writers/sqlite.py:37-100](file://writers/sqlite.py#L37-L100)
- [writers/feishu.py:556-591](file://writers/feishu.py#L556-L591)
- [cron_daily_query.sh:112-154](file://cron_daily_query.sh#L112-L154)

**Section sources**
- [zxgk_query.py:1484-1494](file://zxgk_query.py#L1484-L1494)
- [writers/sqlite.py:37-100](file://writers/sqlite.py#L37-L100)
- [writers/feishu.py:556-591](file://writers/feishu.py#L556-L591)
- [cron_daily_query.sh:112-154](file://cron_daily_query.sh#L112-L154)

### Integration Patterns with External Services
- OCR service
  - RESTful endpoints: health check and solve endpoints; configurable base URL.
- Feishu API
  - Uses lark-cli to call Bitable APIs for record creation, updates, media uploads, and search.
- Local storage
  - SQLite database for reliable local persistence; optional screenshot BLOB storage.

```mermaid
graph LR
CAPT["CaptchaSolver"] --> |POST /solve/base64| OCR["OCR Service"]
FEISHU["Feishu Writer"] --> |API calls| LARK["lark-cli"]
LARK --> BITABLE["Feishu Bitable"]
CLI["CLI"] --> |Writes| SQLITE["SQLite DB"]
```

**Diagram sources**
- [captcha-solver/main.py:107-142](file://captcha-solver/main.py#L107-L142)
- [writers/feishu.py:56-66](file://writers/feishu.py#L56-L66)
- [writers/feishu.py:82-126](file://writers/feishu.py#L82-L126)
- [writers/sqlite.py:37-100](file://writers/sqlite.py#L37-L100)

**Section sources**
- [captcha-solver/main.py:107-142](file://captcha-solver/main.py#L107-L142)
- [writers/feishu.py:56-66](file://writers/feishu.py#L56-L66)
- [writers/feishu.py:82-126](file://writers/feishu.py#L82-L126)
- [writers/sqlite.py:37-100](file://writers/sqlite.py#L37-L100)

## Dependency Analysis
- Internal dependencies
  - CLI depends on BrowserManager, QueryEngine, CaptchaSolver, and writers.
  - BatchRunner composes these components and manages lifecycle and retry policies.
- External dependencies
  - Playwright and stealth libraries for browser automation.
  - Requests for OCR service calls.
  - Optional: openpyxl for Excel export; lark-cli for Feishu operations.
- Configuration-driven coupling
  - Subsite selectors, OCR server URL, and Feishu table IDs are configured externally.

```mermaid
graph TB
CLI["zxgk_query.py"] --> BM["BrowserManager"]
CLI --> QE["QueryEngine"]
CLI --> CAPT["CaptchaSolver"]
CLI --> WR["Writers"]
WR --> SQLITE["SQLite"]
WR --> EXCEL["Excel"]
WR --> FEISHU["Feishu"]
CAPT --> OCR["OCR Service"]
FEISHU --> LARK["lark-cli"]
```

**Diagram sources**
- [zxgk_query.py:1065-1197](file://zxgk_query.py#L1065-L1197)
- [writers/sqlite.py:37-100](file://writers/sqlite.py#L37-L100)
- [writers/excel.py:56-73](file://writers/excel.py#L56-L73)
- [writers/feishu.py:556-591](file://writers/feishu.py#L556-L591)
- [captcha-solver/main.py:107-142](file://captcha-solver/main.py#L107-L142)

**Section sources**
- [zxgk_query.py:1065-1197](file://zxgk_query.py#L1065-L1197)
- [writers/sqlite.py:37-100](file://writers/sqlite.py#L37-L100)
- [writers/excel.py:56-73](file://writers/excel.py#L56-L73)
- [writers/feishu.py:556-591](file://writers/feishu.py#L556-L591)
- [captcha-solver/main.py:107-142](file://captcha-solver/main.py#L107-L142)

## Performance Considerations
- Browser reuse and session limits
  - BatchRunner maintains a single browser session per run; restarts after consecutive failures to mitigate memory leaks and WAF drift.
- OCR throughput and reliability
  - OCR requests are retried once on transient failure; confidence thresholds reduce retries on low-quality OCR.
- I/O optimization
  - SQLite supports BLOB storage for screenshots to avoid filesystem churn; Excel export is optimized for minimal formatting overhead.
- Concurrency and pacing
  - Configurable intervals between companies and screenshots reduce WAF pressure and improve stability.

[No sources needed since this section provides general guidance]

## Troubleshooting Guide
- WAF封禁 (WAF blocked)
  - Detected when CAPTCHA element is absent; the system waits and retries. Exit code indicates封禁.
- OCR service unavailable
  - Health check fails or OCR returns empty text/confidence; verify OCR service is running and reachable.
- Feishu authentication issues
  - lark-cli not authenticated; re-run authentication and retry Feishu writes.
- Session cleanup
  - Leftover Chromium processes are cleaned up by both Python and shell scripts; manual cleanup available if needed.
- Diagnostics
  - Use diagnose mode to probe subsite readiness and WAF status.

**Section sources**
- [zxgk_query.py:99-107](file://zxgk_query.py#L99-L107)
- [cron_daily_query.sh:48-96](file://cron_daily_query.sh#L48-L96)
- [writers/feishu.py:56-66](file://writers/feishu.py#L56-L66)
- [diagnose_subsites.py:103-330](file://diagnose_subsites.py#L103-L330)

## Conclusion
The Execution Information Query System is a modular, resilient pipeline that combines stealth browser automation, OCR-based CAPTCHA solving, and extensible output writers. Its staged design—Phase A for text results and local backups, Phase B for screenshot backfill—ensures completeness and auditability. The configuration-driven architecture and plugin-style writers enable easy adaptation to evolving site structures and storage needs.

[No sources needed since this section summarizes without analyzing specific files]

## Appendices

### Configuration Reference
- Core keys
  - captcha_server: OCR service base URL
  - browser: headless, viewport
  - waf: captcha_max_retries, cooldown_on_block_sec, company_interval_sec, screenshot_interval_sec, max_consecutive_fails
  - screenshots.enabled
  - storage.screenshots: file | blob | both
  - subsites: zhixing, shixin, xgl with css_selector and extra_wait_sec
  - feishu: app_token, raw_table.id/fields, detail_table.id/fields, dedup_options
  - output.dir, output.screenshots_dir
  - companies: list of company names

**Section sources**
- [config/zxgk.example.yaml:1-103](file://config/zxgk.example.yaml#L1-L103)

### Exit Codes
- 0: Success
- 1: No results
- 2: WAF blocked
- 3: OCR service unavailable
- 4: Configuration/parameter error

**Section sources**
- [README.md:89-96](file://README.md#L89-L96)