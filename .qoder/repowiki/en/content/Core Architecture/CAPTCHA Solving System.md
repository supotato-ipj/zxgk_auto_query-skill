# CAPTCHA Solving System

<cite>
**Referenced Files in This Document**
- [main.py](file://captcha-solver/main.py)
- [solver.py](file://captcha-solver/solver.py)
- [preprocess.py](file://captcha-solver/preprocess.py)
- [API.md](file://captcha-solver/API.md)
- [Dockerfile](file://captcha-solver/Dockerfile)
- [docker-compose.yml](file://captcha-solver/docker-compose.yml)
- [requirements.txt](file://captcha-solver/requirements.txt)
- [zxgk_query.py](file://zxgk_query.py)
- [README.md](file://README.md)
- [config/zxgk.example.yaml](file://config/zxgk.example.yaml)
</cite>

## Table of Contents
1. [Introduction](#introduction)
2. [System Architecture](#system-architecture)
3. [Core Components](#core-components)
4. [CaptchaSolver Class Implementation](#captchasolver-class-implementation)
5. [OCR Service Communication](#ocr-service-communication)
6. [Image Extraction from DOM Elements](#image-extraction-from-dom-elements)
7. [Image Preprocessing Pipeline](#image-preprocessing-pipeline)
8. [Canvas-Based Image Extraction](#canvas-based-image-extraction)
9. [Confidence-Based Validation](#confidence-based-validation)
10. [Integration Patterns](#integration-patterns)
11. [Retry Mechanisms](#retry-mechanisms)
12. [Error Handling Strategies](#error-handling-strategies)
13. [Performance Optimization](#performance-optimization)
14. [Timeout Handling](#timeout-handling)
15. [Service Availability Checks](#service-availability-checks)
16. [Practical Examples](#practical-examples)
17. [Troubleshooting Guide](#troubleshooting-guide)
18. [Conclusion](#conclusion)

## Introduction

The CAPTCHA solving system is a comprehensive solution designed to automate the recognition of verification codes in Chinese enforcement information websites. The system consists of two primary components: a standalone OCR service built with PaddleOCR and a browser automation framework that integrates with the OCR service to solve CAPTCHAs during automated web scraping.

The system addresses the challenge of CAPTCHA recognition in government websites by providing:
- Real-time OCR processing using PaddleOCR
- Robust image preprocessing pipelines
- Canvas-based image extraction from DOM elements
- Confidence-based validation and retry mechanisms
- Integration with browser automation frameworks
- Comprehensive error handling and fallback strategies

## System Architecture

The CAPTCHA solving system follows a microservice architecture with clear separation of concerns:

```mermaid
graph TB
subgraph "Browser Automation Layer"
BA[BrowserManager]
QE[QueryEngine]
CS[CaptchaSolver]
DS[DetailScreenshot]
end
subgraph "OCR Service Layer"
API[FastAPI Server]
SOLVER[CaptchaSolver]
PREPROC[Preprocessing Pipeline]
PADDLE[PaddleOCR Engine]
end
subgraph "External Dependencies"
WEBSITE[Chinese Enforcement Website]
FS[File System]
FEISHU[Feishu API]
end
BA --> QE
QE --> CS
CS --> API
API --> SOLVER
SOLVER --> PREPROC
PREPROC --> PADDLE
CS -.-> WEBSITE
QE --> WEBSITE
DS --> WEBSITE
API --> FS
QE --> FEISHU
```

**Diagram sources**
- [main.py:101-142](file://captcha-solver/main.py#L101-L142)
- [solver.py:8-33](file://captcha-solver/solver.py#L8-L33)
- [zxgk_query.py:328-392](file://zxgk_query.py#L328-L392)

The architecture consists of four main layers:

1. **Browser Automation Layer**: Handles web navigation, DOM manipulation, and user interaction
2. **OCR Service Layer**: Provides real-time CAPTCHA recognition capabilities
3. **Preprocessing Pipeline**: Optimizes images for OCR accuracy
4. **Integration Layer**: Manages external dependencies and data persistence

## Core Components

### OCR Service Components

The OCR service is built using FastAPI and PaddleOCR, providing multiple API endpoints for different input formats:

```mermaid
classDiagram
class CaptchaSolver {
-PaddleOCR ocr
-bool _initialized
+recognize(image) Tuple~str, float~
+__new__() CaptchaSolver
+__init__() void
}
class PreprocessPipeline {
+remove_interference_lines(gray, kernel) ndarray
+enhance_contrast(gray, clip_limit, tile_size) ndarray
+binarize(gray, method, block_size, c) ndarray
+morphological_clean(binary, open_kernel, close_kernel) ndarray
+preprocess(image_path, debug) ndarray
+preprocess_from_bytes(image_bytes, debug) ndarray
+preprocess_from_bytes_gray(image_bytes) ndarray
+preprocess_from_bytes_raw(image_bytes) ndarray
+preprocess_from_bytes_mode(image_bytes, mode) ndarray
}
class FastAPIServer {
+app FastAPI
+solve(file) SolveResponse
+solve_text(file) TextResponse
+solve_base64(data) JSONResponse
+health() JSONResponse
+root() JSONResponse
}
CaptchaSolver --> PreprocessPipeline : "uses"
FastAPIServer --> CaptchaSolver : "depends on"
```

**Diagram sources**
- [solver.py:8-83](file://captcha-solver/solver.py#L8-L83)
- [preprocess.py:1-130](file://captcha-solver/preprocess.py#L1-L130)
- [main.py:101-215](file://captcha-solver/main.py#L101-L215)

**Section sources**
- [main.py:101-215](file://captcha-solver/main.py#L101-L215)
- [solver.py:8-83](file://captcha-solver/solver.py#L8-L83)
- [preprocess.py:1-130](file://captcha-solver/preprocess.py#L1-L130)

## CaptchaSolver Class Implementation

The `CaptchaSolver` class serves as the core OCR recognition component, implementing a singleton pattern to avoid repeated model loading:

### Singleton Pattern Implementation

The class implements a custom singleton pattern to ensure efficient memory usage and model initialization:

```mermaid
sequenceDiagram
participant Client as "Client Code"
participant CS as "CaptchaSolver"
participant Paddle as "PaddleOCR"
Client->>CS : __new__()
CS->>CS : Check _instance
alt First Instance
CS->>CS : Create new instance
CS->>CS : Initialize _initialized = False
else Existing Instance
CS->>CS : Return existing instance
end
Client->>CS : __init__()
CS->>CS : Check _initialized
alt Not Initialized
CS->>Paddle : Initialize PaddleOCR
Paddle-->>CS : Model Loaded
CS->>CS : Set _initialized = True
else Already Initialized
CS->>CS : Return
end
```

**Diagram sources**
- [solver.py:13-33](file://solver.py#L13-L33)

### OCR Recognition Process

The recognition process involves multiple stages of image processing and text extraction:

```mermaid
flowchart TD
Start([OCR Recognition Request]) --> ValidateInput["Validate OCR Input"]
ValidateInput --> CheckResult{"OCR Result<br/>Available?"}
CheckResult --> |No| ReturnEmpty["Return ('', None)"]
CheckResult --> |Yes| ExtractData["Extract Recognition Data"]
ExtractData --> CheckTexts{"Text Arrays<br/>Available?"}
CheckTexts --> |No| ReturnEmpty
CheckTexts --> |Yes| JoinTexts["Join Recognition Texts"]
JoinTexts --> CleanText["Remove Non-Alphanumeric Characters"]
CleanText --> CalcConf["Calculate Average Confidence"]
CalcConf --> ReturnResult["Return (cleaned_text, avg_confidence)"]
ReturnEmpty --> End([End])
ReturnResult --> End
```

**Diagram sources**
- [solver.py:34-55](file://solver.py#L34-L55)

**Section sources**
- [solver.py:8-83](file://captcha-solver/solver.py#L8-L83)

## OCR Service Communication

The OCR service exposes multiple API endpoints designed to handle different input formats and use cases:

### API Endpoint Architecture

| Endpoint | Method | Description | Response Format |
|----------|--------|-------------|-----------------|
| `/` | GET | Service information | JSON with service status |
| `/health` | GET | Health check endpoint | JSON with health status |
| `/solve` | POST | File upload recognition | JSON with text, confidence, timing |
| `/solve/text` | POST | File upload recognition (plain text) | Plain text response |
| `/solve/base64` | POST | Base64 input recognition | JSON with text, confidence, timing |

### Request/Response Processing

The service implements comprehensive request validation and response formatting:

```mermaid
sequenceDiagram
participant Client as "Client Application"
participant API as "FastAPI Endpoint"
participant Validator as "Request Validator"
participant Processor as "Async Processor"
participant Solver as "CaptchaSolver"
Client->>API : POST /solve/base64
API->>Validator : Validate Request
Validator-->>API : Validation Result
alt Validation Success
API->>Processor : Process Image Bytes
Processor->>Solver : Recognize Image
Solver-->>Processor : OCR Result
Processor-->>API : Processed Result
API-->>Client : JSON Response
else Validation Failure
API-->>Client : HTTP 400 Error
end
```

**Diagram sources**
- [main.py:174-209](file://captcha-solver/main.py#L174-L209)

**Section sources**
- [main.py:101-215](file://captcha-solver/main.py#L101-L215)
- [API.md:19-76](file://captcha-solver/API.md#L19-L76)

## Image Extraction from DOM Elements

The browser automation system implements sophisticated DOM element extraction to capture CAPTCHA images:

### Canvas-Based Image Capture

The system uses JavaScript evaluation to extract images from the verification code container:

```mermaid
flowchart TD
Start([DOM Element Extraction]) --> FindYZM["Find #yzm Element"]
FindYZM --> CheckFound{"Element Found?"}
CheckFound --> |No| ReturnNull["Return Null"]
CheckFound --> |Yes| GetContainer["Get Container Element"]
GetContainer --> FindImages["Find All Images in Container"]
FindImages --> FilterImages["Filter by Size Constraints"]
FilterImages --> CreateCanvas["Create Canvas Element"]
CreateCanvas --> DrawImage["Draw Image to Canvas"]
DrawImage --> ConvertToDataURL["Convert to Data URL"]
ConvertToDataURL --> ReturnDataURL["Return Data URL"]
ReturnNull --> End([End])
ReturnDataURL --> End
```

**Diagram sources**
- [zxgk_query.py:339-359](file://zxgk_query.py#L339-L359)

### Image Filtering Criteria

The system applies strict filtering criteria to identify legitimate CAPTCHA images:

- **Width Range**: 20px < width < 300px
- **Height Range**: 10px < height < 100px
- **Aspect Ratio**: Balanced proportions typical of verification codes
- **Container Hierarchy**: Located within form-group or parent containers

**Section sources**
- [zxgk_query.py:339-359](file://zxgk_query.py#L339-L359)

## Image Preprocessing Pipeline

The preprocessing pipeline optimizes images for improved OCR accuracy through multiple stages:

### Complete Preprocessing Workflow

```mermaid
flowchart TD
InputImage["Input Image"] --> DecodeImage["Decode Image Bytes"]
DecodeImage --> ConvertColor["Convert to Grayscale"]
ConvertColor --> RemoveInterference["Remove Interference Lines"]
RemoveInterference --> EnhanceContrast["Enhance Contrast (CLAHE)"]
EnhanceContrast --> Binarize["Binarize Image"]
Binarize --> MorphClean["Morphological Cleaning"]
MorphClean --> InvertColors["Invert Colors (White Text on Black Background)"]
InvertColors --> ConvertColorSpace["Convert to BGR Color Space"]
ConvertColorSpace --> OutputImage["Output Preprocessed Image"]
```

**Diagram sources**
- [preprocess.py:86-102](file://preprocess.py#L86-L102)

### Individual Preprocessing Steps

Each preprocessing stage serves a specific purpose in the optimization pipeline:

1. **Interference Line Removal**: Uses median blur to eliminate fine interference lines
2. **Contrast Enhancement**: Implements CLAHE (Contrast Limited Adaptive Histogram Equalization)
3. **Binarization**: Applies adaptive thresholding for optimal text-background separation
4. **Morphological Cleaning**: Uses opening and closing operations to refine character shapes

**Section sources**
- [preprocess.py:7-129](file://captcha-solver/preprocess.py#L7-L129)

## Canvas-Based Image Extraction

The system implements advanced canvas-based extraction for high-quality image capture:

### Canvas Creation and Drawing Process

```mermaid
sequenceDiagram
participant DOM as "DOM Element"
participant Canvas as "Canvas Context"
participant ImageData as "Image Data"
participant DataURL as "Data URL"
DOM->>Canvas : Create Canvas Element
Canvas->>Canvas : Set Width/Height
Canvas->>ImageData : Get Image Context
ImageData->>Canvas : Draw Image
Canvas->>DataURL : Convert to PNG Data URL
DataURL-->>DOM : Return Data URL String
```

**Diagram sources**
- [zxgk_query.py:350-355](file://zxgk_query.py#L350-L355)

### Memory Management

The canvas-based approach ensures efficient memory usage by:
- Creating temporary canvas elements for extraction
- Converting to data URLs without permanent storage
- Allowing automatic garbage collection of intermediate objects

**Section sources**
- [zxgk_query.py:339-359](file://zxgk_query.py#L339-L359)

## Confidence-Based Validation

The system implements robust confidence-based validation to ensure OCR accuracy:

### Validation Thresholds

The confidence validation system operates on multiple levels:

```mermaid
flowchart TD
Start([OCR Result]) --> CheckText{"Text Present?"}
CheckText --> |No| SkipSubmission["Skip Submission"]
CheckText --> |Yes| CheckConfidence{"Confidence Available?"}
CheckConfidence --> |No| SubmitResult["Submit Result"]
CheckConfidence --> |Yes| ValidateThreshold{"Confidence >= 0.3?"}
ValidateThreshold --> |No| RefreshCaptcha["Refresh CAPTCHA"]
ValidateThreshold --> |Yes| SubmitResult
SkipSubmission --> End([End])
RefreshCaptcha --> End
SubmitResult --> End
```

**Diagram sources**
- [zxgk_query.py:437-440](file://zxgk_query.py#L437-L440)

### Threshold Configuration

- **Minimum Confidence**: 0.3 (rejects low-confidence results)
- **Fallback Strategy**: Automatic CAPTCHA refresh on validation failure
- **Retry Logic**: Up to 5 attempts per query with exponential backoff

**Section sources**
- [zxgk_query.py:437-440](file://zxgk_query.py#L437-L440)

## Integration Patterns

The system demonstrates several integration patterns for seamless operation:

### Browser Automation Integration

The `CaptchaSolver` class integrates with the browser automation framework:

```mermaid
classDiagram
class BrowserManager {
+launch() void
+navigate(subsite) void
+diagnose(subsite) dict
+close() void
}
class CaptchaSolver {
-string server_url
+health_check() bool
+get_captcha(page) string
+solve(b64) tuple
+refresh(page) void
}
class QueryEngine {
-Page page
-CaptchaSolver solver
-int max_retries
+query(company) list
+_submit() void
+_collect_all_pages() list
}
BrowserManager --> QueryEngine : "provides Page"
QueryEngine --> CaptchaSolver : "uses"
CaptchaSolver --> BrowserManager : "interacts with"
```

**Diagram sources**
- [zxgk_query.py:175-392](file://zxgk_query.py#L175-L392)

### Configuration-Driven Integration

The system supports flexible configuration through YAML files:

- **Service Configuration**: Captcha server URL and timeouts
- **Browser Configuration**: Headless mode, viewport, and proxy settings
- **WAF Parameters**: Retry limits, cooldown periods, and intervals
- **Output Configuration**: File paths and storage preferences

**Section sources**
- [config/zxgk.example.yaml:7-44](file://config/zxgk.example.yaml#L7-L44)
- [zxgk_query.py:1065-1197](file://zxgk_query.py#L1065-L1197)

## Retry Mechanisms

The system implements comprehensive retry mechanisms to handle transient failures:

### Multi-Level Retry Strategy

```mermaid
flowchart TD
Start([Operation Attempt]) --> CheckFailure{"Operation Failed?"}
CheckFailure --> |No| Success["Success"]
CheckFailure --> |Yes| CheckAttempts{"Attempts < Max?"}
CheckAttempts --> |No| Fail["Final Failure"]
CheckAttempts --> |Yes| ApplyBackoff["Apply Backoff"]
ApplyBackoff --> Wait["Wait for Timeout"]
Wait --> Retry["Retry Operation"]
Retry --> CheckFailure
Success --> End([End])
Fail --> End
```

**Diagram sources**
- [zxgk_query.py:411-482](file://zxgk_query.py#L411-L482)

### Specific Retry Scenarios

1. **CAPTCHA Recognition**: Up to 8 attempts with 1-second delays
2. **Browser Navigation**: Up to 3 attempts with 30-second cooldowns
3. **Service Health Checks**: Immediate retries with 5-second timeouts
4. **Network Operations**: Up to 2 attempts with exponential backoff

**Section sources**
- [zxgk_query.py:411-482](file://zxgk_query.py#L411-L482)

## Error Handling Strategies

The system implements comprehensive error handling across all layers:

### Exception Hierarchy

```mermaid
classDiagram
class Exception {
<<abstract>>
}
class CaptchaUnavailableError {
+message : string
}
class WafBlockedError {
+message : string
}
class SubsiteNavError {
+message : string
}
Exception <|-- CaptchaUnavailableError
Exception <|-- WafBlockedError
Exception <|-- SubsiteNavError
```

**Diagram sources**
- [zxgk_query.py:99-107](file://zxgk_query.py#L99-L107)

### Error Recovery Patterns

- **Service Unavailable**: Graceful degradation with manual intervention
- **WAF Detection**: Automatic cooldown and retry with increased intervals
- **Navigation Failure**: DOM element re-discovery with fallback selectors
- **OCR Failure**: Automatic CAPTCHA refresh and alternative preprocessing modes

**Section sources**
- [zxgk_query.py:99-107](file://zxgk_query.py#L99-L107)

## Performance Optimization

The system incorporates multiple performance optimization strategies:

### Memory Management

- **Singleton Pattern**: Prevents repeated model loading
- **Lazy Initialization**: OCR models loaded only when needed
- **Canvas Cleanup**: Automatic garbage collection of temporary elements
- **Memory Limits**: Docker container memory constraints (2GB)

### Processing Optimization

- **Async Processing**: Non-blocking OCR operations
- **Image Caching**: Preprocessed images cached in memory
- **Batch Processing**: Multiple queries per browser session
- **Resource Pooling**: Shared browser instances across operations

**Section sources**
- [Dockerfile:16-21](file://captcha-solver/Dockerfile#L16-L21)
- [docker-compose.yml:12](file://captcha-solver/docker-compose.yml#L12)

## Timeout Handling

The system implements comprehensive timeout management:

### Timeout Configuration

| Operation | Timeout Value | Purpose |
|-----------|---------------|---------|
| Service Health Check | 5 seconds | Quick availability verification |
| OCR Processing | 10 seconds | Prevent hanging operations |
| Browser Navigation | 30 seconds | Handle slow network conditions |
| Network Requests | 15 seconds | Prevent stuck HTTP operations |
| Page Load States | 15-30 seconds | Allow for dynamic content loading |

### Timeout Recovery

```mermaid
sequenceDiagram
participant Client as "Client"
participant Service as "Service"
participant Timeout as "Timeout Handler"
Client->>Service : Request Processing
Service->>Timeout : Start Timer
alt Processing Complete
Timeout->>Service : Cancel Timer
Service-->>Client : Success Response
else Timeout Triggered
Timeout->>Service : Cancel Operation
Service-->>Client : Timeout Error
end
```

**Diagram sources**
- [main.py:334-337](file://captcha-solver/main.py#L334-L337)

**Section sources**
- [main.py:332-337](file://captcha-solver/main.py#L332-L337)

## Service Availability Checks

The system provides robust service availability monitoring:

### Health Check Implementation

```mermaid
flowchart TD
Start([Health Check Request]) --> SendRequest["Send GET /health"]
SendRequest --> CheckStatus{"HTTP Status 200?"}
CheckStatus --> |Yes| MarkHealthy["Mark Service Healthy"]
CheckStatus --> |No| MarkUnhealthy["Mark Service Unhealthy"]
MarkHealthy --> LogSuccess["Log Success"]
MarkUnhealthy --> LogFailure["Log Failure"]
LogSuccess --> End([End])
LogFailure --> End
```

**Diagram sources**
- [main.py:107-109](file://captcha-solver/main.py#L107-L109)

### Availability Monitoring

- **Periodic Checks**: Every 30 seconds for continuous monitoring
- **Graceful Degradation**: Alternative processing modes when unavailable
- **Failover Mechanisms**: Automatic switching to backup services
- **Alerting System**: Integration with monitoring and alerting infrastructure

**Section sources**
- [main.py:107-109](file://captcha-solver/main.py#L107-L109)

## Practical Examples

### Complete CAPTCHA Solving Workflow

```mermaid
sequenceDiagram
participant User as "User"
participant Browser as "Browser Manager"
participant Solver as "Captcha Solver"
participant OCR as "OCR Service"
participant Site as "Enforcement Website"
User->>Browser : Navigate to Website
Browser->>Site : Load Page
Site-->>Browser : Page Ready
Browser->>Solver : Get CAPTCHA Image
Solver->>Site : Extract Image from DOM
Site-->>Solver : Image Data URL
Solver->>OCR : Send Image for Recognition
OCR-->>Solver : Text + Confidence
Solver-->>Browser : OCR Result
Browser->>Site : Fill CAPTCHA + Submit
Site-->>Browser : Results Page
Browser-->>User : Display Results
```

**Diagram sources**
- [zxgk_query.py:409-482](file://zxgk_query.py#L409-L482)

### Integration with Browser Automation

The system integrates seamlessly with Playwright-based browser automation:

1. **Page Navigation**: Automatic navigation to target sub-sites
2. **Element Interaction**: Dynamic interaction with form elements
3. **Result Collection**: Automated extraction of search results
4. **Screenshot Capture**: Optional screenshot capture for evidence

**Section sources**
- [zxgk_query.py:409-482](file://zxgk_query.py#L409-L482)

## Troubleshooting Guide

### Common Issues and Solutions

#### OCR Service Unavailable
- **Symptoms**: HTTP 500 errors, service timeouts
- **Causes**: Model loading failures, memory constraints
- **Solutions**: Restart service, increase memory allocation, check logs

#### CAPTCHA Recognition Failures
- **Symptoms**: Empty text results, low confidence scores
- **Causes**: Poor image quality, incorrect preprocessing
- **Solutions**: Adjust preprocessing parameters, refresh CAPTCHA

#### Browser Automation Issues
- **Symptoms**: Navigation failures, element not found errors
- **Causes**: DOM changes, network issues
- **Solutions**: Update selectors, increase timeouts, check WAF

#### Performance Issues
- **Symptoms**: Slow processing, memory leaks
- **Causes**: Inefficient image processing, resource exhaustion
- **Solutions**: Optimize preprocessing, implement caching

**Section sources**
- [README.md:89-96](file://README.md#L89-L96)

## Conclusion

The CAPTCHA solving system represents a comprehensive solution for automated verification code recognition in Chinese enforcement information websites. The system successfully combines modern OCR technology with robust browser automation to provide reliable, scalable CAPTCHA solving capabilities.

Key achievements include:

- **High Accuracy**: PaddleOCR integration with custom preprocessing pipeline
- **Robust Architecture**: Microservice design with clear separation of concerns
- **Comprehensive Error Handling**: Multi-level retry mechanisms and fallback strategies
- **Performance Optimization**: Memory-efficient processing and resource management
- **Flexible Integration**: Configurable patterns supporting various deployment scenarios

The system provides a solid foundation for automated web scraping tasks while maintaining reliability and performance standards suitable for production environments.