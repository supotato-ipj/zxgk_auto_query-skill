# CAPTCHA Solver API 调用文档

## 启动服务

```bash
cd captcha-solver

# Docker（推荐）
docker compose up -d

# 或裸机
source venv/bin/activate
pip install -r requirements.txt
PORT=8000 python main.py
```

> 首次启动会自动下载 PaddleOCR 模型（~1.5GB），请耐心等待。

## 服务端点

| 方法 | 路径 | Content-Type | 说明 |
|------|------|-------------|------|
| GET | `/` | — | 服务信息 |
| GET | `/health` | — | 健康检查，返回 `{"status":"healthy"}` |
| POST | `/solve` | multipart/form-data | 文件上传识别，返回 JSON |
| POST | `/solve/text` | multipart/form-data | 文件上传识别，返回纯文本 |
| POST | `/solve/base64` | application/json | Base64 输入识别，返回 JSON |

## API 详细说明

### POST /solve — 文件上传

```bash
curl -X POST http://localhost:8000/solve -F "file=@captcha.jpg"
```

响应：
```json
{
  "success": true,
  "text": "4xZL",
  "confidence": 0.9521,
  "elapsed_ms": 85.3,
  "error": null
}
```

- `confidence` 为 `null` 时表示未检测到任何文字
- `success` 为 `false` 时，`error` 包含错误信息

### POST /solve/text — 纯文本返回

```bash
curl -X POST http://localhost:8000/solve/text -F "file=@captcha.jpg"
```

成功返回纯文本：`4xZL`
失败返回 JSON：`{"success":false,"text":"","elapsed_ms":1.2,"error":"..."}`

### POST /solve/base64 — Base64 输入

```bash
curl -X POST http://localhost:8000/solve/base64 \
  -H "Content-Type: application/json" \
  -d '{"image": "base64编码的图片字符串"}'
```

响应格式同 `/solve`。

### GET /health — 健康检查

```bash
curl http://localhost:8000/health
# {"status":"healthy"}
```

## 配置环境变量

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `PORT` | `8000` | 监听端口 |
| `ALLOWED_ORIGINS` | `*` | CORS 允许的来源（逗号分隔） |
| `LOG_LEVEL` | `info` | 日志级别（debug/info/warning/error） |
| `PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK` | — | 设为 `True` 跳过模型源检查 |

## 调用限制

- 仅支持图片格式（image/*）
- 文件大小上限：5MB
- 图片尺寸上限：2000×1000 px
- 单次识别延迟：约 50-150ms（CPU 模式）

## Python 调用示例

```python
import requests

# 方式 1：文件上传
with open('captcha.jpg', 'rb') as f:
    resp = requests.post('http://localhost:8000/solve', files={'file': f})
    data = resp.json()
    print(data['text'], data['confidence'])

# 方式 2：Base64
import base64
with open('captcha.jpg', 'rb') as f:
    b64 = base64.b64encode(f.read()).decode()
resp = requests.post('http://localhost:8000/solve/base64', json={'image': b64})
print(resp.json()['text'])
```

## 快速测试

```bash
# 1. 检查服务是否存活
curl -s http://localhost:8000/health

# 2. 上传一张验证码图片（替换为实际路径）
curl -s -X POST http://localhost:8000/solve -F "file=@./test.jpg"
```
