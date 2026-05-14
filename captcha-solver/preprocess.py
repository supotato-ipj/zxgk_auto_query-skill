"""验证码图像预处理模块"""
import cv2
import numpy as np
from typing import Tuple


def remove_interference_lines(gray: np.ndarray, kernel: int = 3) -> np.ndarray:
    """中值滤波去除细干扰线。kernel 越大去线越强，但字符也可能被抹除。"""
    return cv2.medianBlur(gray, kernel)


def enhance_contrast(gray: np.ndarray, clip_limit: float = 2.0, tile_size: int = 8) -> np.ndarray:
    """CLAHE 对比度增强，分离文字与背景。"""
    clahe = cv2.createCLAHE(clipLimit=clip_limit, tileGridSize=(tile_size, tile_size))
    return clahe.apply(gray)


def binarize(gray: np.ndarray, method: str = "adaptive",
             block_size: int = 15, c: int = 4) -> np.ndarray:
    """二值化。adaptive 对光照不均更鲁棒，otsu 适合干净背景。"""
    if method == "adaptive":
        return cv2.adaptiveThreshold(
            gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
            cv2.THRESH_BINARY_INV, block_size, c,
        )
    else:
        _, binary = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
        return binary


def morphological_clean(binary: np.ndarray,
                        open_kernel: Tuple[int, int] = (2, 2),
                        close_kernel: Tuple[int, int] = (3, 3)) -> np.ndarray:
    """形态学清理：开运算去噪点，闭运算连接断裂笔画。"""
    k_open = cv2.getStructuringElement(cv2.MORPH_RECT, open_kernel)
    k_close = cv2.getStructuringElement(cv2.MORPH_RECT, close_kernel)
    opened = cv2.morphologyEx(binary, cv2.MORPH_OPEN, k_open)
    closed = cv2.morphologyEx(opened, cv2.MORPH_CLOSE, k_close)
    return closed


def preprocess(image_path: str, debug: bool = False,
               median_kernel: int = 3,
               clahe_clip: float = 2.0, clahe_tile: int = 8,
               adaptive_block: int = 15, adaptive_c: int = 4,
               binarize_method: str = "adaptive",
               morph_open_kernel: Tuple[int, int] = (2, 2),
               morph_close_kernel: Tuple[int, int] = (3, 3)) -> np.ndarray:
    """
    完整预处理流水线：灰度 → 去干扰线 → 对比度增强 → 二值化 → 形态学清理。
    返回白底黑字图像供 PaddleOCR 使用。
    """
    img = cv2.imread(image_path)
    if img is None:
        raise FileNotFoundError(f"无法读取图片: {image_path}")

    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    gray = remove_interference_lines(gray, kernel=median_kernel)
    gray = enhance_contrast(gray, clip_limit=clahe_clip, tile_size=clahe_tile)
    binary = binarize(gray, method=binarize_method, block_size=adaptive_block, c=adaptive_c)
    cleaned = morphological_clean(binary, open_kernel=morph_open_kernel, close_kernel=morph_close_kernel)
    result = cv2.bitwise_not(cleaned)
    result = cv2.cvtColor(result, cv2.COLOR_GRAY2BGR)

    if debug:
        cv2.imwrite(image_path.replace('.', '_debug.'), result)
    return result


def preprocess_from_bytes(image_bytes: bytes, debug: bool = False, **kwargs) -> np.ndarray:
    """
    从字节流直接预处理（完整流水线），纯内存操作，不写磁盘。
    流水线参数通过 kwargs 传入，与 preprocess() 一致。
    """
    return _preprocess_full(image_bytes, **kwargs)


def _decode_image(image_bytes: bytes) -> np.ndarray:
    nparr = np.frombuffer(image_bytes, np.uint8)
    img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
    if img is None:
        raise ValueError("无法解码图片数据")
    return img


def _preprocess_full(image_bytes: bytes, **kwargs) -> np.ndarray:
    """完整流水线：灰度 → 去干扰线 → CLAHE → 二值化 → 形态学 → 反相"""
    img = _decode_image(image_bytes)
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    gray = remove_interference_lines(gray, kernel=kwargs.get("median_kernel", 3))
    gray = enhance_contrast(gray,
                            clip_limit=kwargs.get("clahe_clip", 2.0),
                            tile_size=kwargs.get("clahe_tile", 8))
    binary = binarize(gray,
                      method=kwargs.get("binarize_method", "adaptive"),
                      block_size=kwargs.get("adaptive_block", 15),
                      c=kwargs.get("adaptive_c", 4))
    cleaned = morphological_clean(binary,
                                  open_kernel=kwargs.get("morph_open_kernel", (2, 2)),
                                  close_kernel=kwargs.get("morph_close_kernel", (3, 3)))
    result = cv2.bitwise_not(cleaned)
    return cv2.cvtColor(result, cv2.COLOR_GRAY2BGR)


def preprocess_from_bytes_gray(image_bytes: bytes) -> np.ndarray:
    """轻量模式：仅灰度化，不滤波不二值化。适用于小尺寸/干扰线粗的验证码。"""
    img = _decode_image(image_bytes)
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    return cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR)


def preprocess_from_bytes_raw(image_bytes: bytes) -> np.ndarray:
    """无预处理：返回原始 BGR 图像。"""
    return _decode_image(image_bytes)


def preprocess_from_bytes_mode(image_bytes: bytes, mode: str = "full", **kwargs) -> np.ndarray:
    """
    根据模式选择预处理强度。
    - `full`: 完整流水线（默认）
    - `gray`: 仅灰度化
    - `none`: 无预处理，原始图直出
    """
    if mode == "none":
        return preprocess_from_bytes_raw(image_bytes)
    elif mode == "gray":
        return preprocess_from_bytes_gray(image_bytes)
    else:  # full
        return _preprocess_full(image_bytes, **kwargs)
