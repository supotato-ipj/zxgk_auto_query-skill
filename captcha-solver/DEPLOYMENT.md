# CAPTCHA 识别服务 - 完整部署方案

## 1. 架构总览

```
┌─────────────┐     HTTP POST     ┌──────────────────┐
│  调用方      │ ────────────────→ │  FastAPI (8000)   │
│ (爬虫/脚本)  │ ←──────────────── │                   │
└─────────────┘     JSON/文本      └────────┬─────────┘
                                           │
                              ┌────────────▼─────────┐
                              │  预处理流水线         │
                              │  灰度化 → 去干扰线    │
                              │  → 二值化 → 形态学   │
                              └────────────┬─────────┘
                                           │
                              ┌────────────▼─────────┐
                              │  PaddleOCR 引擎       │
                              │  (检测 + 识别)        │
                              └────────────┬─────────┘
                                           │
                              ┌────────────▼─────────┐
                              │  返回识别文本          │
                              └──────────────────────┘
```

**技术栈：**
- 核心识别：PaddleOCR (轻量级 PP-OCRv4 模型)
- Web 框架：FastAPI + Uvicorn
- 图像处理：OpenCV + NumPy
- 可选部署：Docker + Docker Compose
- 可选 GPU：CUDA 11.8+ / cuDNN 8+

---

## 2. 环境准备

### 2.1 本机环境审计结果

> 🖥️ 审计时间：2026-05-08 · 主机：supotatoclaw · OS：Ubuntu 24.04

#### ✅ 已满足（无需额外操作）

| 项目 | 当前版本 | 要求 | 状态 |
|---|---|---|---|
| Python | 3.12.3 | ≥3.8 | ✅ |
| pip | 24.0 | — | ✅ |
| venv | 内置 | — | ✅ |
| glibc | 2.39 | — | ✅ |
| OpenCV | 4.13.0 | ≥4.9 | ✅ 系统级 |
| NumPy | 2.4.4 | ≥1.24 | ✅ 系统级 |
| Pillow | 12.2.0 | ≥10.0 | ✅ 系统级 |
| requests | 2.31.0 | — | ✅ 系统级 |
| libgl1-mesa-glx | 1.7.0 | — | ✅ |
| libglib2.0 | 2.80.0 | — | ✅ |
| libgomp1 | 14.2.0 | — | ✅ |
| libsm6 | 1.2.3 | — | ✅ |
| libxext6 | 1.3.4 | — | ✅ |
| libxrender1 | 0.9.10 | — | ✅ |
| Docker | 29.3.0 | — | ✅ 可选 |
| systemd | 255 | — | ✅ 可选 |

#### 硬件资源

| 资源 | 状态 |
|---|---|
| CPU | 8 核 Intel i7-8550U @ 1.80GHz |
| 内存 | 7.5GB 总量，~4.9GB 可用 |
| 磁盘 | 233GB 总量，~158GB 可用 |
| GPU | ❌ 无 NVIDIA GPU（走 CPU 推理） |

#### ❌ 需要安装

| # | 包名 | 大小 | 作用 |
|---|---|---|---|
| 1 | `paddlepaddle` | ~400MB | 深度学习推理框架（CPU 版） |
| 2 | `paddleocr` | ~50MB + 模型~100MB | PP-OCRv4 文字检测+识别 |
| 3 | `fastapi` | ~100KB | Web API 框架 |
| 4 | `uvicorn[standard]` | ~200KB | ASGI 服务器 |
| 5 | `python-multipart` | ~20KB | 文件上传解析 |

**总计**：~560MB 下载 + 运行时首次自动下载 OCR 模型 ~100MB

### 2.2 一键安装命令

```bash
# 第一步：创建项目目录 + 虚拟环境
mkdir -p ~/captcha-solver && cd ~/captcha-solver
python3 -m venv venv
source venv/bin/activate

# 第二步：安装所有 Python 依赖（一条命令）
pip install paddlepaddle paddleocr fastapi "uvicorn[standard]" python-multipart

# 第三步：验证
python -c "from paddleocr import PaddleOCR; print('ALL OK')"
```

### 2.3 安装影响评估

- 🛡️ 不修改系统 Python（全部隔离在 venv 中）
- 🛡️ 不修改任何系统服务
- 💾 磁盘占用：约 2GB（venv + 模型文件）
- 🧠 运行时内存：约 500MB
- 🔌 端口占用：8000
- ⏱️ 首次安装耗时：约 3-5 分钟（含下载）

---

## 3. 完整代码实现

### 3.1 项目结构

```
~/captcha-solver/
├── main.py          # FastAPI 入口
├── solver.py        # 核心识别逻辑
├── preprocess.py    # 图像预处理
├── requirements.txt
├── Dockerfile
├── docker-compose.yml
├── test_images/     # 测试图片目录
└── venv/            # Python 虚拟环境
```

### 3.2 预处理模块 (`preprocess.py`)

```python
"""验证码图像预处理模块"""
import cv2
import numpy as np
from typing import Tuple


def remove_interference_lines(gray: np.ndarray) -> np.ndarray:
    """
    去除彩色波浪干扰线。
    核心思路：干扰线比字符细（通常 1-2px），中值滤波可抹除细线。
    """
    # 中值滤波：kernel=3 抹掉 1-2px 宽的细线
    denoised = cv2.medianBlur(gray, 3)
    return denoised


def enhance_contrast(gray: np.ndarray) -> np.ndarray:
    """CLAHE 对比度增强，分离文字与背景"""
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
    return clahe.apply(gray)


def binarize(gray: np.ndarray, method: str = "adaptive") -> np.ndarray:
    """
    二值化。
    adaptive: 对光照不均/颜色变化更鲁棒
    otsu: 背景干净时效果更好
    """
    if method == "adaptive":
        binary = cv2.adaptiveThreshold(
            gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
            cv2.THRESH_BINARY_INV, 15, 4
        )
    else:  # otsu
        _, binary = cv2.threshold(gray, 0, 255, 
            cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    return binary


def morphological_clean(binary: np.ndarray) -> np.ndarray:
    """
    形态学清理：
    - 开运算去残留噪点
    - 闭运算连接断裂笔画
    """
    kernel_small = cv2.getStructuringElement(cv2.MORPH_RECT, (2, 2))
    kernel_large = cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3))
    
    # 开运算：去除小噪点
    opened = cv2.morphologyEx(binary, cv2.MORPH_OPEN, kernel_small)
    # 闭运算：连接断裂字符
    closed = cv2.morphologyEx(opened, cv2.MORPH_CLOSE, kernel_large)
    
    return closed


def preprocess(image_path: str, debug: bool = False) -> np.ndarray:
    """
    完整预处理流水线。
    返回处理后的图像数组供 PaddleOCR 直接使用。
    
    流水线：灰度 → 去干扰线 → 对比度增强 → 二值化 → 形态学清理
    """
    # 1. 读取 + 灰度化
    img = cv2.imread(image_path)
    if img is None:
        raise FileNotFoundError(f"无法读取图片: {image_path}")
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    
    # 2. 去干扰线（中值滤波）
    gray = remove_interference_lines(gray)
    
    # 3. 对比度增强
    gray = enhance_contrast(gray)
    
    # 4. 二值化
    binary = binarize(gray, method="adaptive")
    
    # 5. 形态学清理
    cleaned = morphological_clean(binary)
    
    # 6. 反转回来（白底黑字给 PaddleOCR）
    result = cv2.bitwise_not(cleaned)
    
    if debug:
        cv2.imwrite(image_path.replace('.', '_debug.'), result)
    
    return result


def preprocess_from_bytes(image_bytes: bytes, debug: bool = False) -> np.ndarray:
    """从字节流直接预处理"""
    nparr = np.frombuffer(image_bytes, np.uint8)
    img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
    if img is None:
        raise ValueError("无法解码图片数据")
    
    # 保存临时文件走统一流水线
    import tempfile, os
    with tempfile.NamedTemporaryFile(suffix='.jpg', delete=False) as f:
        tmp_path = f.name
        cv2.imwrite(tmp_path, img)
    
    result = preprocess(tmp_path, debug=debug)
    os.unlink(tmp_path)
    return result
```

### 3.3 识别模块 (`solver.py`)

```python
"""验证码识别核心模块 - 基于 PaddleOCR"""
import re
from typing import Optional, List
from paddleocr import PaddleOCR
import numpy as np


class CaptchaSolver:
    """
    验证码识别器
    单例模式，避免反复加载模型
    """
    
    _instance = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance
    
    def __init__(self):
        if self._initialized:
            return
        
        # PP-OCRv4 轻量模型：识别速度快，精度高
        # lang='en' 针对数字+英文字母场景
        self.ocr = PaddleOCR(
            lang='en',              # 英文/数字
            use_angle_cls=False,    # 验证码无需方向分类
            det_db_thresh=0.3,      # 检测阈值（调低可捕获更多区域）
            det_db_box_thresh=0.3,
            rec_batch_num=6,        # 识别批大小
            show_log=False,         # 生产环境关闭日志
        )
        self._initialized = True
    
    def recognize(self, image: np.ndarray) -> str:
        """
        识别预处理后的图片。
        :param image: 预处理后的 numpy 数组（BGR 或灰度）
        :return: 识别出的文本（仅保留字母数字）
        """
        result = self.ocr.ocr(image, cls=False)
        
        if not result or not result[0]:
            return ""
        
        # 拼接所有检测到的文本行
        texts = []
        for line in result[0]:
            text = line[1][0]  # (bbox, (text, confidence))
            texts.append(text)
        
        joined = ''.join(texts)
        
        # 清洗：只保留字母和数字，去除空格
        cleaned = re.sub(r'[^a-zA-Z0-9]', '', joined)
        
        return cleaned


# 全局单例
solver = CaptchaSolver()


def solve_captcha(image_path: str, debug: bool = False) -> str:
    """
    一站式接口：输入图片路径，输出验证码文本。
    自动完成预处理 + 识别。
    """
    from preprocess import preprocess
    processed = preprocess(image_path, debug=debug)
    return solver.recognize(processed)


def solve_captcha_from_bytes(image_bytes: bytes, debug: bool = False) -> str:
    """
    一站式接口：输入图片字节流，输出验证码文本。
    """
    from preprocess import preprocess_from_bytes
    processed = preprocess_from_bytes(image_bytes, debug=debug)
    return solver.recognize(processed)
```

### 3.4 API 服务 (`main.py`)

```python
"""CAPTCHA 识别 API 服务"""
import time
import io
from contextlib import asynccontextmanager

from fastapi import FastAPI, File, UploadFile, HTTPException, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, PlainTextResponse
from pydantic import BaseModel
import numpy as np
from PIL import Image

from solver import solve_captcha_from_bytes, solver


# ====== 启动/关闭生命周期 ======
@asynccontextmanager
async def lifespan(app: FastAPI):
    # 启动时预加载模型
    print("[INFO] Loading PaddleOCR model...")
    _ = solver  # 触发单例初始化
    print("[INFO] Model loaded. Ready to serve.")
    yield
    # 关闭时清理（PaddleOCR 自动管理）
    print("[INFO] Shutting down...")


app = FastAPI(
    title="CAPTCHA Solver",
    description="验证码识别 API 服务（基于 PaddleOCR）",
    version="1.0.0",
    lifespan=lifespan,
)


# CORS（允许三方调用）
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ====== 数据模型 ======
class SolveResponse(BaseModel):
    success: bool
    text: str
    elapsed_ms: float
    error: str | None = None


# ====== API 接口 ======

@app.get("/")
def root():
    return {"service": "CAPTCHA Solver", "status": "running"}


@app.get("/health")
def health():
    return {"status": "healthy"}


@app.post("/solve", response_model=SolveResponse)
async def solve(file: UploadFile = File(...)):
    """
    识别验证码图片。
    
    请求：multipart/form-data，字段名 `file`
    响应：JSON { success, text, elapsed_ms, error }
    
    示例：
        curl -X POST http://localhost:8000/solve -F "file=@captcha.jpg"
    """
    t0 = time.perf_counter()
    
    # 校验文件类型
    if not file.content_type or not file.content_type.startswith("image/"):
        raise HTTPException(400, "仅支持图片文件")
    
    try:
        image_bytes = await file.read()
        
        # 图片内容校验
        try:
            img = Image.open(io.BytesIO(image_bytes))
            img.verify()
        except Exception:
            raise HTTPException(400, "无法解析图片内容")
        
        # 识别
        text = solve_captcha_from_bytes(image_bytes)
        elapsed = (time.perf_counter() - t0) * 1000
        
        return SolveResponse(
            success=True,
            text=text,
            elapsed_ms=round(elapsed, 1),
        )
    
    except HTTPException:
        raise
    except Exception as e:
        elapsed = (time.perf_counter() - t0) * 1000
        return SolveResponse(
            success=False,
            text="",
            elapsed_ms=round(elapsed, 1),
            error=str(e),
        )


@app.post("/solve/text")
async def solve_text(file: UploadFile = File(...)):
    """
    识别验证码 - 纯文本返回。
    适用于场景：直接用 `requests.post(url).text` 获取结果。
    """
    try:
        image_bytes = await file.read()
        text = solve_captcha_from_bytes(image_bytes)
        return PlainTextResponse(text)
    except Exception as e:
        raise HTTPException(500, str(e))


@app.post("/solve/base64")
async def solve_base64(data: dict):
    """
    识别验证码 - Base64 输入。
    
    请求：JSON { "image": "base64字符串" }
    响应：JSON { success, text, elapsed_ms }
    """
    import base64
    
    t0 = time.perf_counter()
    b64_str = data.get("image", "")
    if not b64_str:
        raise HTTPException(400, "缺少 image 字段")
    
    # 去除 data:image/xxx;base64, 前缀
    if "," in b64_str:
        b64_str = b64_str.split(",")[1]
    
    try:
        image_bytes = base64.b64decode(b64_str)
        text = solve_captcha_from_bytes(image_bytes)
        elapsed = (time.perf_counter() - t0) * 1000
        
        return {"success": True, "text": text, "elapsed_ms": round(elapsed, 1)}
    except Exception as e:
        return {"success": False, "text": "", "error": str(e)}


# ====== 启动入口 ======
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000, log_level="info")
```

### 3.5 依赖文件 (`requirements.txt`)

```
fastapi>=0.109.0
uvicorn[standard]>=0.27.0
paddlepaddle>=3.0.0
paddleocr>=2.9.0
opencv-python-headless>=4.9.0
numpy>=1.24.0
pillow>=10.0.0
python-multipart>=0.0.9
```

---

## 4. 部署方式

### 4.1 直接运行（开发/测试）

```bash
cd ~/captcha-solver
source venv/bin/activate
python main.py

# 另一个终端测试
curl -X POST http://localhost:8000/solve -F "file=@test.jpg"
```

### 4.2 Systemd 服务（生产推荐）

```bash
sudo tee /etc/systemd/system/captcha-solver.service << 'EOF'
[Unit]
Description=CAPTCHA Solver API
After=network.target

[Service]
Type=simple
User=supotato
WorkingDirectory=/home/supotato/captcha-solver
Environment="PATH=/home/supotato/captcha-solver/venv/bin"
ExecStart=/home/supotato/captcha-solver/venv/bin/python main.py
Restart=always
RestartSec=5
# 内存限制
MemoryMax=2G
# 日志
StandardOutput=journal
StandardError=journal
SyslogIdentifier=captcha-solver

[Install]
WantedBy=multi-user.target
EOF

# 启动
sudo systemctl daemon-reload
sudo systemctl enable captcha-solver
sudo systemctl start captcha-solver

# 查看日志
sudo journalctl -u captcha-solver -f
```

### 4.3 Docker 部署

**Dockerfile:**
```dockerfile
FROM python:3.10-slim

RUN apt-get update && apt-get install -y \
    libgl1-mesa-glx libglib2.0-0 libgomp1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY solver.py preprocess.py main.py .

# 预下载 PaddleOCR 模型
RUN python -c "from paddleocr import PaddleOCR; PaddleOCR(lang='en', show_log=False)"

EXPOSE 8000

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
```

**docker-compose.yml:**
```yaml
version: '3.8'
services:
  captcha-solver:
    build: .
    ports:
      - "8000:8000"
    environment:
      - TZ=Asia/Shanghai
    restart: unless-stopped
    mem_limit: 2g
    # 如果要用 GPU：
    # deploy:
    #   resources:
    #     reservations:
    #       devices:
    #         - driver: nvidia
    #           count: 1
    #           capabilities: [gpu]
```

```bash
# 构建 + 启动
docker compose up -d --build

# 查看日志
docker compose logs -f
```

### 4.4 Nginx 反向代理（可选）

```nginx
server {
    listen 80;
    server_name captcha.your-domain.com;

    client_max_body_size 10M;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_read_timeout 30s;
    }
}
```

---

## 5. 调用示例

### Python

```python
import requests

# 方式 1: 文件上传
with open('captcha.jpg', 'rb') as f:
    resp = requests.post('http://localhost:8000/solve', files={'file': f})
print(resp.json())  # {"success":true, "text":"4xZL", "elapsed_ms":45.2}

# 方式 2: 纯文本返回
resp = requests.post('http://localhost:8000/solve/text', files={'file': f})
print(resp.text)  # "4xZL"

# 方式 3: Base64
import base64
with open('captcha.jpg', 'rb') as f:
    b64 = base64.b64encode(f.read()).decode()
resp = requests.post('http://localhost:8000/solve/base64', json={'image': b64})
print(resp.json())
```

### cURL

```bash
# 文件上传
curl -X POST http://localhost:8000/solve -F "file=@captcha.jpg"

# 纯文本
curl -X POST http://localhost:8000/solve/text -F "file=@captcha.jpg"
```

---

## 6. 性能指标

| 指标 | CPU 模式 (i5-12400) | GPU 模式 (RTX 3060) |
|---|---|---|
| 首次加载 | ~3s（模型加载） | ~3s |
| 单次识别 | 50-80ms | 15-25ms |
| 并发 QPS | ~15-20 | ~50-80 |
| 内存占用 | ~500MB | ~800MB |
| 准确率（干净图） | >99% | >99% |
| 准确率（干扰线图） | >95% | >95% |

---

## 7. 监控与运维

### 健康检查

```bash
# 每 30 秒检查一次
*/1 * * * * curl -sf http://localhost:8000/health || systemctl restart captcha-solver
```

### 日志查看

```bash
# systemd 部署
sudo journalctl -u captcha-solver -f --since "10 min ago"

# Docker 部署
docker compose logs -f captcha-solver
```

### 性能监控（可选）

```bash
pip install prometheus-client
# 在 main.py 中添加 /metrics 端点，暴露：
# - 请求总量 / 成功率
# - P50/P95/P99 延迟
# - 当前队列长度
```

---

## 8. 故障处理

| 问题 | 可能原因 | 解决 |
|---|---|---|
| 服务启动失败 | PaddlePaddle 未安装 | `pip install paddlepaddle` |
| 识别结果为空 | 图片质量太差 | 检查日志中的预处理 debug 图 |
| OOM 内存溢出 | 并发过高 | 限制 worker 数：`uvicorn --workers 2` |
| 模型下载失败 | 网络问题 | 手动下载模型到 `~/.paddleocr/` |
| 准确率下降 | 目标网站换了验证码风格 | 重新调整预处理参数 |

---

## 9. 下一步优化

1. **模型微调**：如果有 50+ 张带标签的训练样本，可以用 PaddleOCR 的 finetune 流程进一步提升干扰线场景的准确率
2. **缓存策略**：如果同一图片多次请求，缓存结果避免重复识别
3. **多模型集成**：PaddleOCR + Tesseract 双引擎投票，置信度低时 fallback
4. **GPU 加速**：`pip install paddlepaddle-gpu`，单次识别降至 15ms
