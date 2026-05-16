"""DetailScreenshot — 详情弹窗截图 + OpenCV 弹窗提取"""
import re
from pathlib import Path

import cv2
import numpy as np

from .config import logger


def extract_popup_from_bytes(screenshot_bytes, output_path):
    """
    从全页截图 bytes 中用 OpenCV 精准提取弹窗区域（全程内存，无中间磁盘 IO）。
    返回 (width, height) or (None, None)
    """
    nparr = np.frombuffer(screenshot_bytes, np.uint8)
    img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
    if img is None:
        return None, None

    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    h_img, w_img = img.shape[:2]

    # Step 1-2: Canny 边缘 → 膨胀 → 轮廓
    edges = cv2.Canny(gray, 50, 150)
    dilated = cv2.dilate(edges, np.ones((3, 3), np.uint8), iterations=2)
    contours, _ = cv2.findContours(dilated, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    # Step 3: 筛选候选矩形（尺寸 + 位置）
    candidates = []
    for c in contours:
        x, y, w, h = cv2.boundingRect(c)
        if (400 < w < 1400 and 150 < h < 500 and y > h_img * 0.35):
            candidates.append((w * h, x, y, w, h))

    if not candidates:
        return None, None

    # Step 4: 最大面积 → 粗裁
    area, x, y, cw, ch = max(candidates, key=lambda v: v[0])
    crop = img[y:y + ch, x:x + cw]
    crop_gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)

    # Step 5: 白底检测
    mask = cv2.inRange(crop_gray, 230, 255)

    # Step 6: 列投影 → 精裁边界
    col_proj = np.sum(mask, axis=0) / ch
    content_cols = col_proj > 0.1

    if not np.any(content_cols):
        l, r = int(cw * 0.25), int(cw * 0.92)
    else:
        changes = np.diff(np.concatenate([[False], content_cols, [False]]).astype(int))
        starts = np.where(changes == 1)[0]
        ends = np.where(changes == -1)[0]
        longest_idx = np.argmax(ends - starts)
        l, r = starts[longest_idx], ends[longest_idx]

    l = max(0, int(l) - 8)
    r = min(cw, int(r) + 8)

    tight = crop[:, l:r]
    cv2.imwrite(str(output_path), tight)
    return tight.shape[1], tight.shape[0]


class DetailScreenshot:
    def __init__(self, page, output_dir, interval_sec=2.0):
        self.page = page
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.interval_sec = interval_sec

    def capture_all(self, records):
        """批量截取详情弹窗，返回 {viewId: filepath} 映射"""
        import time

        screenshot_map = {}
        for i, rec in enumerate(records):
            fp = self._capture_one(rec["viewId"], i + 1, rec.get("caseNo", ""))
            screenshot_map[rec["viewId"]] = fp
            logger.info("截图 %d/%d: %s (viewId=%s)",
                        i + 1, len(records),
                        rec.get("caseNo", "?"), rec["viewId"])
            time.sleep(self.interval_sec)
        return screenshot_map

    def _capture_one(self, view_id, index, case_no=""):
        import time

        self.page.evaluate(f"showDetail({view_id})")
        time.sleep(2)

        safe_case = re.sub(r"[（）()\s]", "_", case_no)[:30] if case_no else ""
        filename = f"detail_r{index}_{view_id}_{safe_case}.png"
        filepath = self.output_dir / filename
        screenshot_bytes = self.page.screenshot(full_page=False)
        crop_w, crop_h = extract_popup_from_bytes(screenshot_bytes, str(filepath))
        if crop_w is None:
            with open(str(filepath), 'wb') as f:
                f.write(screenshot_bytes)

        # 关闭弹窗
        self.page.evaluate("""
        () => {
            for (const el of document.querySelectorAll('a,span,div')) {
                if (el.textContent?.trim() === '关闭' && el.offsetParent !== null) {
                    el.click(); return;
                }
            }
        }
        """)
        time.sleep(1)
        return str(filepath)
