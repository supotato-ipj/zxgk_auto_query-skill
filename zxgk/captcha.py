"""CaptchaSolver — 验证码识别客户端"""
import time

import requests

from .config import logger


class CaptchaSolver:
    def __init__(self, server_url="http://localhost:8001"):
        self.server_url = server_url.rstrip("/")

    def health_check(self):
        try:
            r = requests.get(f"{self.server_url}/health", timeout=5)
            return r.status_code == 200
        except requests.RequestException:
            return False

    def get_captcha(self, page):
        """在 #yzm 父容器内截取验证码为 base64 data URL"""
        return page.evaluate("""
        () => {
            const y = document.getElementById('yzm');
            if (!y) return null;
            const p = y.closest('.form-group') || y.parentElement.parentElement;
            for (const i of p.querySelectorAll('img')) {
                const w = i.naturalWidth || i.width;
                const h = i.naturalHeight || i.height;
                if (w > 20 && w < 300 && h > 10 && h < 100) {
                    const c = document.createElement('canvas');
                    c.width = w;
                    c.height = h;
                    c.getContext('2d').drawImage(i, 0, 0);
                    return c.toDataURL('image/png');
                }
            }
            return null;
        }
        """)

    def solve(self, b64):
        """调用 captcha-solver，返回 (text, confidence)"""
        raw = b64.split(",", 1)[1] if b64.startswith("data:") else b64
        for attempt in range(2):
            try:
                r = requests.post(
                    f"{self.server_url}/solve/base64",
                    json={"image": raw, "preprocess": "gray"},
                    timeout=10,
                )
                data = r.json()
                return data.get("text", ""), data.get("confidence", 0.0) or 0.0
            except requests.RequestException:
                if attempt == 0:
                    time.sleep(1)
                    continue
                raise

    def refresh(self, page):
        """点击验证码图片刷新"""
        page.evaluate("""
        () => {
            const y = document.getElementById('yzm');
            if (y) {
                const p = y.closest('.form-group') || y.parentElement.parentElement;
                const i = p.querySelector('img');
                if (i) i.click();
            }
        }
        """)
        time.sleep(1)
