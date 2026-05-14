"""CAPTCHA 识别 API 服务"""
import asyncio
import base64
import io
import logging
import os
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, File, HTTPException, Query, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, PlainTextResponse
from PIL import Image
from pydantic import BaseModel

from solver import CaptchaSolver, solve_captcha_from_bytes

# ====== 配置 ======
PORT = int(os.getenv("PORT", "8000"))
ALLOWED_ORIGINS = os.getenv("ALLOWED_ORIGINS", "*")
LOG_LEVEL = os.getenv("LOG_LEVEL", "info").upper()
MAX_FILE_SIZE = 5 * 1024 * 1024  # 5MB
MAX_IMAGE_WIDTH = 2000
MAX_IMAGE_HEIGHT = 1000

logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger("captcha-solver")

# ====== 全局单例（lifespan 中初始化） ======
solver: CaptchaSolver = None


# ====== 启动/关闭生命周期 ======
@asynccontextmanager
async def lifespan(app: FastAPI):
    global solver
    logger.info("Loading PaddleOCR model...")
    solver = CaptchaSolver()
    logger.info("Model loaded. Ready to serve.")
    yield
    logger.info("Shutting down...")


app = FastAPI(
    title="CAPTCHA Solver",
    description="验证码识别 API 服务（基于 PaddleOCR）",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS.split(","),
    allow_methods=["POST", "GET"],
    allow_headers=["*"],
)

# ====== 数据模型 ======
class SolveResponse(BaseModel):
    success: bool
    text: str
    confidence: float | None = None
    elapsed_ms: float
    error: str | None = None


# ====== 辅助函数 ======
async def _validate_image(file: UploadFile, content: bytes) -> None:
    """校验上传文件：类型 + 大小 + 图片尺寸。"""
    if not file.content_type or not file.content_type.startswith("image/"):
        raise HTTPException(400, "仅支持图片文件")

    if len(content) > MAX_FILE_SIZE:
        raise HTTPException(400, f"文件大小超过限制 ({MAX_FILE_SIZE // 1024 // 1024}MB)")

    try:
        img = Image.open(io.BytesIO(content))
        w, h = img.size
        if w > MAX_IMAGE_WIDTH or h > MAX_IMAGE_HEIGHT:
            raise HTTPException(400, f"图片尺寸超过限制 ({MAX_IMAGE_WIDTH}x{MAX_IMAGE_HEIGHT})")
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(400, "无法解析图片内容")


def _log_request(text: str, confidence: float | None, elapsed_ms: float,
                 client_ip: str = "-") -> None:
    logger.info(
        "client=%s text=%s confidence=%s elapsed=%.1fms",
        client_ip, text or "<empty>",
        f"{confidence:.3f}" if confidence is not None else "N/A",
        elapsed_ms,
    )


# ====== API 接口 ======

@app.get("/")
def root():
    return {"service": "CAPTCHA Solver", "status": "running"}


@app.get("/health")
def health():
    return {"status": "healthy"}


@app.post("/solve", response_model=SolveResponse)
async def solve(file: UploadFile = File(...),
                preprocess: str = Query("gray", description="预处理模式: full, gray, none"),
                request: Request = None):
    """
    识别验证码图片（multipart/form-data 上传）。默认 gray（仅灰度化），对小尺寸细笔画验证码更可靠。
    preprocess: `full`（完整流水线）、`gray`（仅灰度化）、`none`（无预处理）
    """
    t0 = time.perf_counter()
    client_ip = request.client.host if request else "-"

    try:
        content = await file.read()
        await _validate_image(file, content)
        text, confidence = await asyncio.to_thread(
            solve_captcha_from_bytes, content, solver, preprocess
        )
        elapsed = (time.perf_counter() - t0) * 1000
        _log_request(text, confidence, elapsed, client_ip)
        return SolveResponse(
            success=True, text=text, confidence=confidence, elapsed_ms=round(elapsed, 1),
        )
    except HTTPException:
        raise
    except Exception as e:
        elapsed = (time.perf_counter() - t0) * 1000
        logger.error("client=%s error=%s", client_ip, str(e))
        return SolveResponse(
            success=False, text="", elapsed_ms=round(elapsed, 1), error=str(e),
        )


@app.post("/solve/text")
async def solve_text(file: UploadFile = File(...),
                     preprocess: str = Query("full", description="预处理模式: full, gray, none"),
                     request: Request = None):
    """
    识别验证码 - 成功返回纯文本，失败返回 JSON。
    """
    t0 = time.perf_counter()
    client_ip = request.client.host if request else "-"

    try:
        content = await file.read()
        await _validate_image(file, content)
        text, confidence = await asyncio.to_thread(
            solve_captcha_from_bytes, content, solver, preprocess
        )
        elapsed = (time.perf_counter() - t0) * 1000
        _log_request(text, confidence, elapsed, client_ip)
        return PlainTextResponse(text)
    except HTTPException:
        raise
    except Exception as e:
        elapsed = (time.perf_counter() - t0) * 1000
        logger.error("client=%s error=%s", client_ip, str(e))
        return JSONResponse(
            status_code=500,
            content={"success": False, "text": "", "elapsed_ms": round(elapsed, 1), "error": str(e)},
        )


@app.post("/solve/base64")
async def solve_base64(data: dict, request: Request = None):
    """
    识别验证码 - Base64 输入。
    请求: { "image": "base64字符串", "preprocess": "full|gray|none" (可选) }
    响应: { success, text, confidence, elapsed_ms }
    """
    t0 = time.perf_counter()
    client_ip = request.client.host if request else "-"

    b64_str = data.get("image", "")
    if not b64_str:
        raise HTTPException(400, "缺少 image 字段")

    preprocess_mode = data.get("preprocess", "gray")
    if preprocess_mode not in ("full", "gray", "none"):
        preprocess_mode = "full"

    if "," in b64_str:
        b64_str = b64_str.split(",")[1]

    try:
        image_bytes = base64.b64decode(b64_str)
        text, confidence = await asyncio.to_thread(
            solve_captcha_from_bytes, image_bytes, solver, preprocess_mode
        )
        elapsed = (time.perf_counter() - t0) * 1000
        _log_request(text, confidence, elapsed, client_ip)
        return {"success": True, "text": text, "confidence": confidence, "elapsed_ms": round(elapsed, 1)}
    except HTTPException:
        raise
    except Exception as e:
        elapsed = (time.perf_counter() - t0) * 1000
        logger.error("client=%s error=%s", client_ip, str(e))
        return {"success": False, "text": "", "elapsed_ms": round(elapsed, 1), "error": str(e)}


# ====== 启动入口 ======
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=PORT, log_level=LOG_LEVEL.lower())
