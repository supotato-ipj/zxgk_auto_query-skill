"""验证码识别核心模块 - 基于 PaddleOCR 3.x"""
import re
from typing import Optional, Tuple
from paddleocr import PaddleOCR
import numpy as np


class CaptchaSolver:
    """验证码识别器。单例模式避免反复加载模型。"""

    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self.ocr = PaddleOCR(
            lang='en',
            ocr_version='PP-OCRv4',
            use_doc_orientation_classify=False,
            use_doc_unwarping=False,
            use_textline_orientation=False,
            text_det_thresh=0.3,
            text_det_box_thresh=0.3,
            text_recognition_batch_size=6,
        )
        self._initialized = True

    def recognize(self, image: np.ndarray) -> Tuple[str, Optional[float]]:
        """
        识别预处理后的图片。
        返回 (cleaned_text, avg_confidence)。
        无结果时返回 ("", None)。
        """
        result = self.ocr.ocr(image)

        if not result or not result[0]:
            return "", None

        page = result[0]
        rec_texts = page.get('rec_texts', [])
        rec_scores = page.get('rec_scores', [])

        if not rec_texts:
            return "", None

        joined = ''.join(rec_texts)
        cleaned = re.sub(r'[^a-zA-Z0-9]', '', joined)
        avg_conf = sum(rec_scores) / len(rec_scores) if rec_scores else None
        return cleaned, avg_conf


def solve_captcha(image_path: str, solver: Optional[CaptchaSolver] = None,
                  debug: bool = False, **preprocess_kwargs) -> Tuple[str, Optional[float]]:
    """
    一站式接口：输入图片路径，输出 (验证码文本, 置信度)。
    自动完成预处理 + 识别。
    """
    from preprocess import preprocess
    if solver is None:
        solver = CaptchaSolver()
    processed = preprocess(image_path, debug=debug, **preprocess_kwargs)
    return solver.recognize(processed)


def solve_captcha_from_bytes(image_bytes: bytes, solver: Optional[CaptchaSolver] = None,
                              preprocess_mode: str = "full",
                              debug: bool = False, **preprocess_kwargs) -> Tuple[str, Optional[float]]:
    """
    一站式接口：输入图片字节流，输出 (验证码文本, 置信度)。
    preprocess_mode: `full`（完整流水线）、`gray`（仅灰度化）、`none`（无预处理）
    """
    from preprocess import preprocess_from_bytes_mode
    if solver is None:
        solver = CaptchaSolver()
    processed = preprocess_from_bytes_mode(image_bytes, mode=preprocess_mode, **preprocess_kwargs)
    return solver.recognize(processed)
