FROM python:3.12-slim

RUN apt-get update && apt-get install -y \
    libgl1-mesa-glx libglib2.0-0 libgomp1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY preprocess.py solver.py main.py .

EXPOSE 8000

ENV PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK=True

# 启动时下载 OCR 模型（不打进镜像）
CMD ["sh", "-c", "\
  python -c 'from paddleocr import PaddleOCR; PaddleOCR(lang=\"en\", ocr_version=\"PP-OCRv4\", use_doc_orientation_classify=False, use_doc_unwarping=False, use_textline_orientation=False); print(\"Models ready\")' \
  && uvicorn main:app --host 0.0.0.0 --port 8000"]
