# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

CAPTCHA recognition web service — FastAPI API that accepts images and returns recognized text with confidence scores using PaddleOCR (PP-OCRv4). Designed for internal agent use: single-request, English alphanumeric CAPTCHAs with interference lines and slight distortion.

## Architecture

```
Client (HTTP POST) -> FastAPI (port 8000) -> preprocess.py -> solver.py (PaddleOCR) -> text response
```

- **`main.py`** — FastAPI app with `/solve` (multipart → JSON), `/solve/text` (multipart → plain text), `/solve/base64` (JSON → JSON), plus `/` and `/health`. Error responses are always JSON. Model loaded in lifespan, OCR runs via `asyncio.to_thread`.
- **`preprocess.py`** — Memory-only pipeline: grayscale → median blur → CLAHE contrast → adaptive threshold → morphological open/close → invert. All parameters are externally configurable via kwargs.
- **`solver.py`** — PaddleOCR singleton (`CaptchaSolver`), English/digit mode. `recognize()` returns `(text, confidence)` tuple — confidence is `None` only when no text detected.

## Source of Truth

`DEPLOYMENT.md` is the original blueprint (now superseded by the actual source files). It still contains useful deployment instructions (systemd, Nginx reverse proxy), performance benchmarks, and troubleshooting.

## Setup & Run

```bash
# Create venv and install
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt

# Run dev server
PORT=8000 python main.py

# Docker
docker compose up -d --build
```

## API

```
POST /solve         multipart file  → { success, text, confidence, elapsed_ms }
POST /solve/text    multipart file  → plain text (success) / JSON (error)
POST /solve/base64  { image: b64 }  → { success, text, confidence, elapsed_ms }
GET  /health                         → { status: "healthy" }
```

File upload limits: 5MB max, 2000x1000 px max.

## Configuration (env vars)

| Variable | Default | Description |
|----------|---------|-------------|
| `PORT` | `8000` | Listen port |
| `ALLOWED_ORIGINS` | `*` | CORS origins (comma-separated) |
| `LOG_LEVEL` | `info` | Python logging level |
| `PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK` | — | Set to `True` to skip model hoster connectivity check (needed behind proxies) |

If running behind a SOCKS5 proxy, pip install `PySocks` and `socksio` first, then set `ALL_PROXY=socks5://host:port`.

## Key Design Decisions

- **PaddleOCR singleton** — model loads once in lifespan, not per request
- **`asyncio.to_thread`** — OCR runs in thread pool to avoid blocking the event loop
- **Confidence returned** — caller decides threshold; `None` means no text detected
- **Preprocessing params externalized** — all tunable via kwargs for per-CAPTCHA-type optimization
- **`lang='en'`** — alphanumeric only; output stripped to `[a-zA-Z0-9]`
- **CPU inference** — no GPU needed; single recognition ~50-80ms
- **Memory budget** — ~500MB runtime; docker compose caps at 2G

## Version Compatibility

- **PaddlePaddle must be <3.3** — 3.3.0+ has a oneDNN/PIR incompatibility with OCR models (`>=3.0.0,<3.3` in requirements.txt)
- **PaddleOCR 3.x** uses `ocr_version='PP-OCRv4'`, disables doc orientation/unwarping/textline orientation for speed
- **Preprocessing returns 3-channel BGR** — PaddleOCR 3.x text detection requires 3 channels (not grayscale)
