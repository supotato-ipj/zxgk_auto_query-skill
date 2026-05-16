# Query Engine

<cite>
**Referenced Files in This Document**
- [zxgk/query.py](file://zxgk/query.py)
- [zxgk/cli.py](file://zxgk/cli.py)
- [zxgk/runner.py](file://zxgk/runner.py)
- [zxgk/browser.py](file://zxgk/browser.py)
- [zxgk/captcha.py](file://zxgk/captcha.py)
- [zxgk/config.py](file://zxgk/config.py)
- [config/zxgk.example.yaml](file://config/zxgk.example.yaml)
- [diagnose_subsites.py](file://diagnose_subsites.py)
- [writers/sqlite.py](file://writers/sqlite.py)
</cite>

## Update Summary
**Changes Made**
- Updated QueryEngine class documentation to reflect the new 275-line implementation in zxgk/query.py
- Added detailed analysis of the intelligent search algorithms and configurable retry mechanisms
- Documented the popup dismissal automation system with module-level utilities
- Enhanced pagination handling and viewId-based deduplication documentation
- Updated subsite-specific behaviors for zhixing, shixin, and xgl sites
- Added comprehensive error handling and retry logic documentation
- Documented the new module-level dialog dismissal utilities

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
This document provides comprehensive technical documentation for the QueryEngine class that orchestrates the complete search workflow for the China Execution Information Public Disclosure system. The QueryEngine has been completely redesigned as a 275-line implementation in zxgk/query.py, featuring intelligent search algorithms with configurable retry mechanisms, sophisticated popup dismissal automation, and robust result collection strategies. It explains the query execution pipeline including form population, CAPTCHA submission, result collection, pagination handling, viewId-based deduplication, Chinese date parsing, and result validation. It also covers error handling strategies, retry logic, state management, subsite-specific behaviors for zhixing, shixin, and xgl sites, result extraction, data transformation, consistency validation, and integration with browser automation and CAPTCHA solving systems.

## Project Structure
The project is organized around a central CLI that coordinates browser automation, CAPTCHA solving, result extraction, and storage. The main orchestration logic has been centralized in the new QueryEngine class with clearly separated concerns:
- Browser automation and navigation
- CAPTCHA acquisition and solving
- Intelligent query execution with popup dismissal
- Sophisticated pagination handling and deduplication
- Screenshot capture and backfill
- Batch processing and progress tracking
- Output writers (SQLite, Excel, Feishu)

```mermaid
graph TB
CLI["CLI Entry (zxgk/cli.py)"]
BM["BrowserManager<br/>Navigation & WAF checks"]
CE["CaptchaSolver<br/>Health + OCR"]
QE["QueryEngine<br/>Intelligent search + popup dismissal"]
DS["DetailScreenshot<br/>popup capture"]
BR["BatchRunner<br/>batch loop + retries"]
SB["ScreenshotBackfiller<br/>phase B backfill"]
OUT_SQLITE["SQLite Writer"]
OUT_FEISHU["Feishu Writer"]
CLI --> BM
CLI --> CE
CLI --> BR
BR --> BM
BR --> CE
BR --> QE
BR --> DS
BR --> OUT_SQLITE
BR --> OUT_FEISHU
CLI --> SB
SB --> BM
SB --> CE
SB --> OUT_FEISHU
```

**Diagram sources**
- [zxgk/cli.py:104-111](file://zxgk/cli.py#L104-L111)
- [zxgk/runner.py:59-65](file://zxgk/runner.py#L59-L65)
- [zxgk/query.py:53-65](file://zxgk/query.py#L53-L65)

**Section sources**
- [zxgk/cli.py:1-321](file://zxgk/cli.py#L1-L321)
- [config/zxgk.example.yaml:1-103](file://config/zxgk.example.yaml#L1-L103)

## Core Components
- **BrowserManager**: Launches and manages a Chromium browser instance with stealth settings, navigates to subsites, performs WAF checks, and handles diagnostics.
- **CaptchaSolver**: Interacts with a local OCR service to capture and solve CAPTCHAs, with health checks and refresh capabilities.
- **QueryEngine**: **NEW** - Executes the core search workflow with intelligent retry mechanisms, popup dismissal automation, and sophisticated result collection strategies.
- **DetailScreenshot**: Captures screenshots of detail popups using DOM-based and pixel-based extraction.
- **BatchRunner**: Orchestrates batch queries with retry logic, WAF cooling, and progress tracking.
- **ScreenshotBackfiller**: Phase B backfill of missing screenshots by re-querying and uploading to Feishu.
- **Writers**: Output writers for SQLite, Excel, and Feishu.

**Section sources**
- [zxgk/browser.py:58-190](file://zxgk/browser.py#L58-L190)
- [zxgk/captcha.py:9-73](file://zxgk/captcha.py#L9-L73)
- [zxgk/query.py:53-276](file://zxgk/query.py#L53-L276)
- [zxgk/runner.py:15-278](file://zxgk/runner.py#L15-L278)

## Architecture Overview
The QueryEngine sits at the center of the search pipeline, coordinating with BrowserManager and CaptchaSolver to submit queries, handle CAPTCHA challenges, and collect results. It integrates with BatchRunner for batch processing and with DetailScreenshot for capturing detail popups. The new implementation features sophisticated popup dismissal automation and intelligent retry mechanisms.

```mermaid
sequenceDiagram
participant User as "User"
participant CLI as "CLI"
participant Runner as "BatchRunner"
participant Engine as "QueryEngine"
participant Browser as "BrowserManager"
participant Solver as "CaptchaSolver"
participant Site as "ZXGK Site"
User->>CLI : "Run query (single/batch)"
CLI->>Runner : "Initialize with config"
Runner->>Browser : "Launch + navigate(subsite)"
Runner->>Solver : "Health check"
Runner->>Engine : "Create engine(page, solver)"
loop For each company
Runner->>Browser : "Clear/prefill #pName"
Runner->>Solver : "refresh()"
Runner->>Engine : "query(company)"
Engine->>Solver : "get_captcha()"
Engine->>Solver : "solve(captcha)"
Engine->>Browser : "fill(#yzm)"
Engine->>Browser : "submit(search)"
Engine->>Engine : "dismiss_dialogs()"
Engine->>Browser : "evaluate result text"
alt No results
Engine-->>Runner : "[]"
else Has results
Engine->>Engine : "collect_all_pages()"
Engine->>Engine : "apply viewId deduplication"
Engine-->>Runner : "records"
end
Runner->>Runner : "save_result + write output"
end
Runner-->>CLI : "Summary"
CLI-->>User : "Exit code + artifacts"
```

**Diagram sources**
- [zxgk/cli.py:104-111](file://zxgk/cli.py#L104-L111)
- [zxgk/query.py:66-139](file://zxgk/query.py#L66-L139)
- [zxgk/query.py:141-162](file://zxgk/query.py#L141-L162)
- [zxgk/query.py:197-214](file://zxgk/query.py#L197-L214)

## Detailed Component Analysis

### QueryEngine
**NEW** - The QueryEngine encapsulates the end-to-end search workflow with sophisticated popup dismissal automation and intelligent retry mechanisms. It ensures the page has a fresh CAPTCHA before each query, submits the form, validates the response, and collects results across pages while applying viewId-based deduplication.

Key behaviors:
- **Form population**: fills the company name into the search field.
- **CAPTCHA handling**: retrieves the CAPTCHA image, solves it with confidence checking, and fills the CAPTCHA field.
- **Submission**: waits for the search function to be ready, initializes current page state, invokes the search function, and dismisses overlays.
- **Popup dismissal**: **NEW** - Implements sophisticated dialog and overlay dismissal with polling mechanism.
- **Result validation**: checks for "no results" messages and CAPTCHA rejection messages.
- **Pagination**: iterates through pages, extracts records, and applies viewId-based deduplication.
- **Date parsing**: converts Chinese dates to epoch milliseconds for consistent sorting and filtering.

```mermaid
classDiagram
class QueryEngine {
+page
+solver
+max_retries
+subsite
+query(company) list[dict]
+_submit() void
+_dismiss_dialogs() void
+_dismiss_overlay() void
+_collect_all_pages() list[dict]
}
class CaptchaSolver {
+server_url
+health_check() bool
+get_captcha(page) str
+solve(b64) (str, float)
+refresh(page) void
}
class BrowserManager {
+navigate(subsite_name) void
+diagnose(subsite_name) dict
+_check_waf() void
+_click_subsite(name) void
}
QueryEngine --> CaptchaSolver : "uses"
QueryEngine --> BrowserManager : "uses page"
```

**Diagram sources**
- [zxgk/query.py:53-276](file://zxgk/query.py#L53-L276)
- [zxgk/captcha.py:9-73](file://zxgk/captcha.py#L9-L73)
- [zxgk/browser.py:58-190](file://zxgk/browser.py#L58-L190)

**Section sources**
- [zxgk/query.py:53-276](file://zxgk/query.py#L53-L276)

#### Query Execution Flow
**UPDATED** - The QueryEngine now features sophisticated retry mechanisms with configurable maximum attempts and intelligent popup dismissal automation.

```mermaid
flowchart TD
Start(["Start query(company)"]) --> Prefill["Fill #pName with company"]
Prefill --> ProvinceCheck{"Subsite is shixin?"}
ProvinceCheck --> |Yes| SetProvince["Set pProvince='0' (all)"]
ProvinceCheck --> |No| GetCap["Get CAPTCHA image"]
SetProvince --> GetCap
GetCap --> CapFound{"CAPTCHA found?"}
CapFound --> |No| Refresh["Refresh CAPTCHA"] --> RetryAttempt["Retry attempt"]
CapFound --> |Yes| Solve["Solve CAPTCHA with confidence check"]
Solve --> Confidence{"Confidence >= 0.3?"}
Confidence --> |No| Refresh --> RetryAttempt
Confidence --> |Yes| FillYZM["Fill #yzm with solution"]
FillYZM --> Submit["_submit()"]
Submit --> Dismiss["Dismiss dialogs with polling"]
Dismiss --> Validate["Validate result text"]
Validate --> NoResult{"No results?"}
NoResult --> |Yes| ReturnEmpty["Return []"]
NoResult --> |No| RowsCheck{"Rows > 0?"}
RowsCheck --> |No| Refresh --> RetryAttempt
RowsCheck --> |Yes| Collect["Collect all pages with viewId dedup"]
Collect --> Dedup["Apply viewId deduplication"]
Dedup --> Done(["Return records"])
RetryAttempt --> MaxRetries{"Max retries reached?"}
MaxRetries --> |No| Prefill
MaxRetries --> |Yes| ReturnEmpty
```

**Diagram sources**
- [zxgk/query.py:66-139](file://zxgk/query.py#L66-L139)
- [zxgk/query.py:141-162](file://zxgk/query.py#L141-L162)
- [zxgk/query.py:197-214](file://zxgk/query.py#L197-L214)

#### Popup Dismissal Automation
**NEW** - The QueryEngine implements sophisticated popup dismissal automation with module-level utilities for reusable dialog handling.

The system features two levels of popup dismissal:
- **Module-level utilities**: `dismiss_overlay()` and `dismiss_dialogs()` provide reusable dialog handling for external tools like diagnose_subsites.py
- **Class-level automation**: `_dismiss_overlay()` and `_dismiss_dialogs()` integrate directly into the query workflow

```mermaid
flowchart TD
DialogStart["Dialog Detection"] --> OverlayCheck{"Overlay present?"}
OverlayCheck --> |Yes| FindButtons["Find buttons in dialogs"]
FindButtons --> ClickOK["Click '确定' buttons"]
ClickOK --> ClickClose["Click '关闭' buttons"]
ClickClose --> PollCheck{"Poll remaining dialogs"}
PollCheck --> |> 0| Wait["Wait 0.5s"] --> DialogStart
PollCheck --> |= 0| Success["All dialogs dismissed"]
OverlayCheck --> |No| Success
```

**Diagram sources**
- [zxgk/query.py:8-51](file://zxgk/query.py#L8-L51)
- [zxgk/query.py:164-195](file://zxgk/query.py#L164-L195)
- [zxgk/query.py:197-214](file://zxgk/query.py#L197-L214)

#### Pagination and Deduplication
- **Pagination detection**: checks for a next button element and its disabled/visibility state, with a fallback to scanning the page body for "next" indicators.
- **Record extraction**: selects rows from the result table, filters out header rows, and extracts name, case number, date, and viewId from the detail link's onclick attribute.
- **Deduplication**: maintains a dictionary keyed by viewId to ensure uniqueness across pages and sessions.
- **Date normalization**: converts Chinese date strings to epoch milliseconds for consistent downstream processing.

```mermaid
flowchart TD
PageStart(["Page start"]) --> Extract["Extract rows from #tbody-result"]
Extract --> FilterHeaders["Filter header rows"]
FilterHeaders --> BuildRec["Build record {name, caseNo, date, viewId}"]
BuildRec --> Timestamp["Convert date to timestamp"]
Timestamp --> AddMap["Add to all_records by viewId"]
AddMap --> NextCheck{"Has next page?"}
NextCheck --> |Yes| ClickNext["Click nextPage()"]
ClickNext --> WaitLoad["Wait for networkidle"]
WaitLoad --> PageStart
NextCheck --> |No| ReturnList["Return list(all_records.values())"]
```

**Diagram sources**
- [zxgk/query.py:215-276](file://zxgk/query.py#L215-L276)

#### Subsite-Specific Behaviors
- **zhixing**: Standard behavior with no special configuration.
- **shixin**: **NEW** - Explicitly sets the province filter to "all" (value "0") before searching to ensure broader coverage.
- **xgl**: Includes an additional column for enterprise information compared to other subsites.

These differences are reflected in the subsite configuration and the diagnostic tool's probing of DOM structures.

**Section sources**
- [zxgk/query.py:72-78](file://zxgk/query.py#L72-L78)
- [config/zxgk.example.yaml:32-44](file://config/zxgk.example.yaml#L32-L44)
- [diagnose_subsites.py:47-167](file://diagnose_subsites.py#L47-L167)

#### Result Extraction and Transformation
- **Field mapping**: Extracts name, case number, date, and viewId from the result table.
- **Data transformation**: Converts Chinese dates to numeric timestamps for consistency.
- **Consistency validation**: Skips rows with insufficient columns or header-only rows; validates presence of detail links.

**Section sources**
- [zxgk/query.py:221-239](file://zxgk/query.py#L221-L239)
- [zxgk/config.py:90-99](file://zxgk/config.py#L90-L99)

#### Error Handling and Retry Logic
**UPDATED** - The QueryEngine features sophisticated retry mechanisms with configurable maximum attempts and intelligent error detection.

- **WAF封禁 detection**: Checks for the presence of the CAPTCHA element and body length to detect封禁 conditions.
- **CAPTCHA failures**: Retries on CAPTCHA errors or expired CAPTCHAs by refreshing and re-solving.
- **General exceptions**: Wraps query attempts in exception handling and refreshes CAPTCHA on failure.
- **Retry limits**: Configurable maximum retries per query attempt (default 5).
- **Continuous failure handling**: BatchRunner restarts the browser after a configurable number of consecutive failures.
- **Confidence-based filtering**: **NEW** - Rejects CAPTCHA solutions with confidence below 0.3.

```mermaid
flowchart TD
Attempt["Attempt (1..max_retries)"] --> TryQuery["Try query()"]
TryQuery --> Success{"Success?"}
Success --> |Yes| Done["Done"]
Success --> |No| Exception{"Exception?"}
Exception --> |Yes| RefreshCap["Refresh CAPTCHA"] --> RetryLimit{"Exceeded max retries?"}
Exception --> |No| ValidateMsg{"Validate result text"}
ValidateMsg --> NoResult{"No results?"}
NoResult --> |Yes| Done
ValidateMsg --> |No| CapError{"CAPTCHA error/expired?"}
CapError --> |Yes| RefreshCap --> RetryLimit
CapError --> |No| RowsZero{"Rows == 0?"}
RowsZero --> |Yes| RefreshCap --> RetryLimit
RetryLimit --> |Yes| Done
RetryLimit --> |No| TryQuery
```

**Diagram sources**
- [zxgk/query.py:66-139](file://zxgk/query.py#L66-L139)
- [zxgk/runner.py:116-135](file://zxgk/runner.py#L116-L135)

**Section sources**
- [zxgk/query.py:66-139](file://zxgk/query.py#L66-L139)
- [zxgk/runner.py:104-145](file://zxgk/runner.py#L104-L145)

### BatchRunner
BatchRunner coordinates repeated queries across companies, managing browser lifecycle, CAPTCHA freshness, and output persistence. It implements:
- Progress tracking to support resume functionality.
- WAF cooling periods and consecutive failure thresholds.
- Conditional Feishu writing and screenshot capture modes.
- Consolidation of results into a structured batch JSON.

```mermaid
sequenceDiagram
participant Runner as "BatchRunner"
participant Browser as "BrowserManager"
participant Solver as "CaptchaSolver"
participant Engine as "QueryEngine"
participant Output as "Output Writers"
Runner->>Browser : "launch + navigate(subsite)"
Runner->>Solver : "health_check()"
loop For each company
Runner->>Browser : "clear/prefill #pName"
Runner->>Solver : "refresh()"
Runner->>Engine : "query(company)"
alt Records found
Runner->>Output : "capture screenshots"
Runner->>Output : "write JSON + SQLite"
else No results
Runner->>Output : "mark no_results"
end
Runner->>Runner : "track progress"
end
Runner->>Output : "save summary + batch JSON"
```

**Diagram sources**
- [zxgk/runner.py:45-145](file://zxgk/runner.py#L45-L145)
- [writers/sqlite.py:37-100](file://writers/sqlite.py#L37-L100)

**Section sources**
- [zxgk/runner.py:15-278](file://zxgk/runner.py#L15-L278)

### ScreenshotBackfiller (Phase B)
Phase B identifies missing screenshots from the case table, re-queries the site, captures detail popups, and uploads them to Feishu. It:
- Queries the case table for records with empty screenshot fields.
- Resolves real viewIds via DuplexLink references.
- Navigates to the zhixing subsite, performs CAPTCHA verification, and captures screenshots.
- Uploads screenshots to Feishu and updates the case record.

```mermaid
flowchart TD
StartB(["Start Phase B"]) --> QueryCases["Query case table for missing screenshots"]
QueryCases --> Found{"Any missing?"}
Found --> |No| EndB(["End"])
Found --> |Yes| ResolveViewId["Resolve viewId via DuplexLink"]
ResolveViewId --> GroupByCompany["Group by company"]
GroupByCompany --> Navigate["Navigate to zhixing"]
Navigate --> SearchLoop["For each company: search + verify CAPTCHA"]
SearchLoop --> CaptureLoop["For each record: showDetail → capture → upload"]
CaptureLoop --> UpdateRecord["Update case record with screenshot"]
UpdateRecord --> NextCompany{"More companies?"}
NextCompany --> |Yes| SearchLoop
NextCompany --> |No| EndB
```

**Diagram sources**
- [zxgk/cli.py:166-178](file://zxgk/cli.py#L166-L178)

**Section sources**
- [zxgk/cli.py:166-178](file://zxgk/cli.py#L166-L178)

### Writers
- **SQLite writer**: Writes batch results to a local SQLite database, supporting storing screenshot paths or binary data.
- **Excel writer**: Outputs results to Excel format.
- **Feishu writer**: Writes results to Feishu tables (placeholder in current code).

**Section sources**
- [writers/sqlite.py:1-121](file://writers/sqlite.py#L1-L121)
- [zxgk/cli.py:145-157](file://zxgk/cli.py#L145-L157)

## Dependency Analysis
The system exhibits clear separation of concerns with explicit dependencies:
- CLI depends on BatchRunner for batch operations and on individual runners for single queries.
- BatchRunner depends on BrowserManager, CaptchaSolver, QueryEngine, and output writers.
- QueryEngine depends on CaptchaSolver and BrowserManager.
- ScreenshotBackfiller depends on BrowserManager, CaptchaSolver, and Feishu APIs.

```mermaid
graph TB
CLI["CLI (zxgk/cli.py)"]
BR["BatchRunner"]
QE["QueryEngine"]
BM["BrowserManager"]
CS["CaptchaSolver"]
SB["ScreenshotBackfiller"]
OUT_SQLITE["SQLite Writer"]
OUT_FEISHU["Feishu Writer"]
CLI --> BR
CLI --> SB
BR --> QE
BR --> BM
BR --> CS
BR --> OUT_SQLITE
BR --> OUT_FEISHU
QE --> CS
QE --> BM
SB --> BM
SB --> CS
SB --> OUT_FEISHU
```

**Diagram sources**
- [zxgk/cli.py:104-111](file://zxgk/cli.py#L104-L111)
- [zxgk/runner.py:59-65](file://zxgk/runner.py#L59-L65)
- [zxgk/query.py:53-65](file://zxgk/query.py#L53-L65)

**Section sources**
- [zxgk/cli.py:104-111](file://zxgk/cli.py#L104-L111)
- [zxgk/runner.py:59-65](file://zxgk/runner.py#L59-L65)

## Performance Considerations
- **Browser reuse**: Reusing a single browser session across queries reduces startup overhead.
- **Stealth settings**: Applying stealth attributes helps reduce detection and improves stability.
- **Timeout tuning**: Configurable timeouts for page loads and network idle states balance reliability and speed.
- **Retry strategies**: Controlled retries for CAPTCHA and WAF封禁 prevent unnecessary failures.
- **Output modes**: Using text-only mode reduces screenshot overhead for large batches.
- **Concurrent processing**: The current implementation runs sequentially; parallelization could improve throughput but requires careful state management.
- **Popup dismissal optimization**: **NEW** - The polling-based dialog dismissal system optimizes for minimal waiting time while ensuring all overlays are cleared.

## Troubleshooting Guide
Common issues and resolutions:
- **WAF封禁**: Detected when the CAPTCHA element is absent or body length indicates封禁. The system automatically retries with delays.
- **CAPTCHA solver unavailable**: Health check failure prevents execution; ensure the OCR service is running on the configured port.
- **Navigation failures**: CSS selectors for subsites may change; use the diagnostic tool to probe DOM structures.
- **No results**: The system distinguishes between "no results" and "CAPTCHA error." In the latter case, it refreshes and retries.
- **Continuous failures**: The BatchRunner restarts the browser after a threshold of consecutive failures to recover from state corruption.
- **Popup blocking**: **NEW** - The sophisticated dialog dismissal system handles various overlay types including confirmation dialogs, error popups, and modal windows.
- **Confidence issues**: **NEW** - CAPTCHA solutions with confidence below 0.3 are automatically rejected to prevent false positives.

**Section sources**
- [zxgk/query.py:66-139](file://zxgk/query.py#L66-L139)
- [zxgk/runner.py:104-145](file://zxgk/runner.py#L104-L145)
- [diagnose_subsites.py:47-167](file://diagnose_subsites.py#L47-L167)

## Conclusion
The QueryEngine provides a robust, modular framework for automating queries against the China Execution Information Public Disclosure system. The new 275-line implementation features sophisticated popup dismissal automation, intelligent retry mechanisms, and configurable error handling. It integrates browser automation, CAPTCHA solving, result extraction, pagination, and output persistence while offering comprehensive error handling, retry logic, and subsite-specific adaptations. The design supports both single queries and large-scale batch processing, with clear pathways for diagnostics and recovery.

## Appendices

### Practical Examples
- **Single query**: Run a single company search with optional screenshots and Feishu writing.
- **Batch processing**: Execute queries for a list of companies with progress tracking and consolidated output.
- **Error recovery**: The system handles封禁, CAPTCHA errors, and continuous failures with automatic retries and browser restarts.
- **Popup dismissal**: **NEW** - The system automatically handles various types of overlays and dialogs during the query process.

**Section sources**
- [zxgk/cli.py:86-164](file://zxgk/cli.py#L86-L164)
- [zxgk/runner.py:181-220](file://zxgk/runner.py#L181-L220)

### Configuration Reference
- **Subsite configuration**: Defines CSS selectors and extra wait times for each subsite.
- **WAF parameters**: Controls retry counts, cooldown periods, intervals, and screenshot timing.
- **Output settings**: Directories for JSON and screenshot storage.

**Section sources**
- [config/zxgk.example.yaml:32-96](file://config/zxgk.example.yaml#L32-L96)

### Setup and Diagnostics
- **One-click setup**: Installs Python dependencies, Playwright Chromium, lark-cli, and optional OCR service.
- **Smoke testing**: Validates Python/Shell syntax, YAML configuration, environment variables, and recent batch JSON format.
- **Subsite diagnostics**: Probes DOM structures and pagination behavior across all three subsites.

**Section sources**
- [zxgk/cli.py:25-84](file://zxgk/cli.py#L25-L84)
- [diagnose_subsites.py:1-200](file://diagnose_subsites.py#L1-L200)