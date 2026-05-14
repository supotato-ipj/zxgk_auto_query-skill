#!/usr/bin/env python3
"""
zxgk_query.py — 中国执行信息公开网 统一查询 CLI

用法:
  python3 zxgk_query.py --company "XX公司"
  python3 zxgk_query.py --company "XX公司" --mode text-only --feishu
  python3 zxgk_query.py --company "XX公司" --mode full --feishu
  python3 zxgk_query.py --batch config/companies.txt --feishu
  python3 zxgk_query.py --batch config/companies.txt --mode full --feishu
  python3 zxgk_query.py --mode backfill --batch-id "20260510-zhixing" --feishu
  python3 zxgk_query.py --diagnose
  python3 zxgk_query.py --batch config/companies.txt --resume

返回值:
  0  成功（查到结果）
  1  查询无结果
  2  WAF 封禁（需冷却）
  3  captcha-solver 不可用
  4  配置/参数错误
"""

import argparse
import atexit
import json
import logging
import os
import re
import signal
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests
import yaml
from playwright.sync_api import sync_playwright
from playwright_stealth import Stealth

import cv2
import numpy as np

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("zxgk_query")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
BROWSER_ARGS = [
    "--no-sandbox",
    "--disable-setuid-sandbox",
    "--disable-dev-shm-usage",
    "--disable-blink-features=AutomationControlled",
    "--disable-features=IsolateOrigins,site-per-process",
    "--disable-web-security",
]

PROXY_VARS = [
    "HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy",
    "ALL_PROXY", "all_proxy",
]

SCRIPT_DIR = Path(__file__).resolve().parent

# ---------------------------------------------------------------------------
# Globals (for signal / atexit cleanup)
# ---------------------------------------------------------------------------
_browser = None

def _cleanup():
    global _browser
    if _browser:
        try:
            _browser.close()
        except Exception:
            pass
        _browser = None

def _signal_handler(signum, frame):
    logger.warning("收到信号 %s，正在清理退出...", signum)
    _cleanup()
    sys.exit(128 + signum)

signal.signal(signal.SIGINT, _signal_handler)
signal.signal(signal.SIGTERM, _signal_handler)
atexit.register(_cleanup)

# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------
class WafBlockedError(Exception):
    """WAF 封禁：子站页面无 #yzm 表单元素"""

class CaptchaUnavailableError(Exception):
    """captcha-solver 服务不可用"""

class SubsiteNavError(Exception):
    """子站链接定位失败（CSS selector 失效）"""

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def clean_env():
    """清理代理环境变量"""
    for k in PROXY_VARS:
        os.environ.pop(k, None)

def load_config(path=None):
    """加载 YAML 配置，返回 dict"""
    if path is None:
        path = SCRIPT_DIR / "config" / "zxgk.yaml"
    config_path = Path(path)
    if not config_path.exists():
        logger.warning("配置文件不存在 %s，使用默认值", config_path)
        return {}
    with open(config_path) as f:
        raw = yaml.safe_load(f) or {}

    # 展开环境变量引用 ${VAR_NAME}
    def _resolve_env(value):
        if isinstance(value, str) and value.startswith("${") and value.endswith("}"):
            env_var = value[2:-1]
            return os.environ.get(env_var, "")
        if isinstance(value, dict):
            return {k: _resolve_env(v) for k, v in value.items()}
        if isinstance(value, list):
            return [_resolve_env(v) for v in value]
        return value
    return _resolve_env(raw)

def load_company_list(path):
    """加载公司列表（YAML 或纯文本，每行一个公司名）"""
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"公司列表文件不存在: {path}")
    if p.suffix in (".yaml", ".yml"):
        with open(p) as f:
            data = yaml.safe_load(f)
        if isinstance(data, list):
            return [item if isinstance(item, str) else item.get("name", str(item)) for item in data]
        raise ValueError("YAML 格式错误：应为公司名列表")
    else:
        # 纯文本：每行 公司名
        with open(p) as f:
            return [line.strip() for line in f if line.strip() and not line.startswith("#")]

def parse_chinese_date(text: str) -> int:
    """2026年03月26日 → 1742947200000 (Asia/Shanghai milliseconds)"""
    from zoneinfo import ZoneInfo
    m = re.match(r'(\d{4})年(\d{1,2})月(\d{1,2})日', text)
    if not m:
        return 0
    y, mth, d = int(m[1]), int(m[2]), int(m[3])
    tz = ZoneInfo("Asia/Shanghai")
    dt = datetime(y, mth, d, tzinfo=tz)
    return int(dt.timestamp() * 1000)

# ---------------------------------------------------------------------------
# Module A: EnvironmentSetup
# ---------------------------------------------------------------------------
def setup_environment():
    clean_env()

# ---------------------------------------------------------------------------
# Module B: BrowserManager
# ---------------------------------------------------------------------------
class BrowserManager:
    def __init__(self, config):
        self.config = config
        cfg = config.get("browser", {})
        self.headless = cfg.get("headless", True)
        self.executable = cfg.get("executable", None)
        vp = cfg.get("viewport", [1920, 1080])
        self.viewport = {"width": vp[0], "height": vp[1]}
        self._playwright = None
        self._browser = None
        self._context = None
        self.page = None

    def __enter__(self):
        self.launch()
        return self

    def __exit__(self, *args):
        self.close()

    def launch(self):
        self._cleanup_orphans()
        self._playwright = sync_playwright().start()
        launch_kwargs = dict(headless=self.headless, args=BROWSER_ARGS)
        if self.executable:
            launch_kwargs["executable_path"] = self.executable
        self._browser = self._playwright.chromium.launch(**launch_kwargs)
        self._context = self._browser.new_context(
            viewport=self.viewport,
            locale="zh-CN",
            extra_http_headers={
                "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
            },
        )
        self.page = self._context.new_page()
        stealth = Stealth(
            navigator_platform_override="Linux x86_64",
            navigator_languages_override=("zh-CN", "zh", "en-US", "en"),
            navigator_vendor_override="Google Inc.",
            webgl_vendor_override="Intel Inc.",
            webgl_renderer_override="Intel Iris OpenGL Engine",
        )
        stealth.apply_stealth_sync(self.page)
        global _browser
        _browser = self._browser
        logger.debug("浏览器已启动")

    def close(self):
        global _browser
        _browser = None
        for obj in (self._context, self._browser, self._playwright):
            if obj:
                try:
                    obj.close()
                except Exception:
                    pass
        logger.debug("浏览器已关闭")

    @staticmethod
    def _cleanup_orphans():
        """清理所有 Playwright 启动的 Chromium 进程（含 GPU/Renderer 子进程）"""
        patterns = [
            "playwright_chromiumdev_profile",
            "chromium-browser.*--type=",
        ]
        for pattern in patterns:
            try:
                subprocess.run(
                    ["pkill", "-f", pattern],
                    capture_output=True, text=True, timeout=5
                )
            except Exception:
                pass
        time.sleep(1)

    def navigate(self, subsite_name):
        """主站 → 点击子站链接 → 等待加载，WAF 封禁时自动重试"""
        subsites = self.config.get("subsites", {})
        subsite = subsites.get(subsite_name, {})
        name = subsite.get("name", subsite_name)
        extra_wait = subsite.get("extra_wait_sec", 5)
        logger.info("导航: 主站 → %s", name)

        for attempt in range(3):
            self.page.goto("http://zxgk.court.gov.cn",
                           wait_until="networkidle", timeout=30000)
            self.page.wait_for_timeout(2000)
            self._click_subsite(subsite_name)
            self.page.wait_for_load_state("networkidle", timeout=30000)
            if extra_wait:
                self.page.wait_for_timeout(extra_wait * 1000)

            try:
                self._check_waf()
                return
            except WafBlockedError:
                if attempt < 2:
                    logger.warning("WAF 封禁 (attempt %d/3)，等 30s 后重试导航", attempt + 1)
                    time.sleep(30)
                else:
                    raise

    def _click_subsite(self, name):
        subsites = self.config.get("subsites", {})
        css = subsites.get(name, {}).get("css_selector", "")
        ok = self.page.evaluate(f"""
            () => {{
                const d = document.querySelector('{css}');
                if (!d) return false;
                const a = d.closest('a');
                if (!a) return false;
                a.target = '_self';
                a.click();
                return true;
            }}
        """)
        if not ok:
            raise SubsiteNavError(
                f"子站链接定位失败: CSS='{css}'，网站 DOM 可能已改版"
            )

    def _check_waf(self):
        has_yzm = self.page.evaluate("() => !!document.getElementById('yzm')")
        if not has_yzm:
            body_len = self.page.evaluate("() => document.body?.innerText?.length || 0")
            raise WafBlockedError(
                f"WAF 封禁: #yzm 不存在, body_len={body_len}。需冷却后重试。"
            )
        logger.debug("WAF 检测通过: #yzm 存在")

    def diagnose(self, subsite_name):
        """诊断模式：导航后返回子站状态"""
        try:
            self.navigate(subsite_name)
            has_yzm = True
            has_pname = self.page.evaluate("() => !!document.getElementById('pName')")
            body_len = self.page.evaluate("() => document.body?.innerText?.length || 0")
            return {
                "status": "ok",
                "subsite": subsite_name,
                "yzm_ready": has_yzm,
                "pname_ready": has_pname,
                "body_len": body_len,
            }
        except WafBlockedError as e:
            return {"status": "waf_blocked", "error": str(e)}
        except SubsiteNavError as e:
            return {"status": "nav_error", "error": str(e)}

# ---------------------------------------------------------------------------
# Module C: CaptchaSolver
# ---------------------------------------------------------------------------
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

# ---------------------------------------------------------------------------
# Module D: QueryEngine
# ---------------------------------------------------------------------------
class QueryEngine:
    """查询引擎。

    调用方应在调用 query() 前确保页面验证码为新鲜状态
    （BatchRunner 在每个公司查询前自动刷新，run_single 刚完成导航验证码本就新鲜）。
    """

    def __init__(self, page, captcha_solver, max_retries=5, subsite="zhixing"):
        self.page = page
        self.solver = captcha_solver
        self.max_retries = max_retries
        self.subsite = subsite

    def query(self, company):
        """查询 + 翻页收集所有结果，viewId 去重。返回 list[dict]"""
        for attempt in range(self.max_retries):
            try:
                logger.info("查询尝试 %d/%d: %s", attempt + 1, self.max_retries, company)

                # shixin 需要显式设置法院范围为"全部"
                if self.subsite == "shixin":
                    try:
                        self.page.select_option("#pProvince", "0")
                    except Exception:
                        logger.debug("#pProvince 设置失败，使用默认值")

                self.page.fill("#pName", company)

                cap = self.solver.get_captcha(self.page)
                if not cap:
                    logger.warning("未找到验证码图片，刷新后重试")
                    self.solver.refresh(self.page)
                    continue

                text, conf = self.solver.solve(cap)
                logger.info("OCR: '%s' conf=%.3f", text, conf)

                if not text or not text.strip():
                    logger.warning("OCR 返回空字符串，跳过提交，刷新后重试")
                    self.solver.refresh(self.page)
                    continue
                if conf is not None and conf < 0.3:
                    logger.warning("OCR 置信度过低 (%.3f)，跳过提交", conf)
                    self.solver.refresh(self.page)
                    continue

                self.page.fill("#yzm", text)
                self._submit()
                # Extra safety: dismiss any late-appearing dialogs before reading result
                self._dismiss_dialogs()

                result_text = self.page.evaluate(
                    '() => document.getElementById("result-block")?.innerText || ""'
                )
                if "没有找到" in result_text:
                    logger.info("查询无结果（没有找到匹配记录）: %s", company)
                    return []
                if "验证码错误" in result_text or "验证码已过期" in result_text:
                    logger.info("验证码被拒（%s），刷新后重试", result_text[:60].replace("\n", " "))
                    self.solver.refresh(self.page)
                    continue
                page_text = self.page.evaluate(
                    '() => (document.body?.innerText || "").substring(0, 500)'
                )
                if "没有找到" in page_text:
                    logger.info("查询无结果（没有找到匹配记录）: %s", company)
                    return []

                rows = self.page.evaluate(
                    '() => document.querySelectorAll("#tbody-result tr").length'
                )
                logger.debug("rows=%d", rows)

                if rows > 0:
                    records = self._collect_all_pages()
                    logger.info("查询成功: %d 条记录", len(records))
                    return records

                logger.debug("rows=0，刷新验证码重试")
                self.solver.refresh(self.page)

            except Exception as e:
                logger.warning("查询异常 (attempt %d/%d): %s", attempt + 1, self.max_retries, e)
                self.solver.refresh(self.page)

        logger.warning("查询全部失败（%d 次重试）: %s", self.max_retries, company)
        return []

    def _submit(self):
        for _ in range(5):
            ready = self.page.evaluate('() => typeof search === "function"')
            if ready:
                break
            time.sleep(0.5)
        else:
            raise RuntimeError("search() 未定义，页面可能未加载完成")

        try:
            self.page.evaluate("initCurrentPage()")
        except Exception:
            logger.debug("initCurrentPage 不可用，跳过")
        self.page.evaluate("search()")
        time.sleep(2)
        self._dismiss_dialogs()
        try:
            self.page.wait_for_load_state("networkidle", timeout=15000)
        except Exception:
            pass
        self.page.wait_for_timeout(500)
        self._dismiss_dialogs()

    def _dismiss_overlay(self):
        """Dismiss confirmation dialogs and error popups.

        The zxgk website shows a confirmation overlay after search() that blocks
        access to #result-block. On captcha failure, a second error popup appears
        on top. Both must be dismissed before results can be read.

        Button search is scoped to dialog/modal containers to avoid mis-clicking
        page-level buttons with the same label.
        """
        self.page.evaluate("""
        () => {
            const dialogs = document.querySelectorAll(
                '.dialog, .modal, .popup, [role="dialog"], [role="alertdialog"], '
                + '.layui-layer-dialog, .layui-layer, .ui-dialog'
            );
            const container = dialogs.length > 0
                ? Array.from(dialogs)
                : [document.body];
            for (const d of container) {
                const btns = d.querySelectorAll('button, input[type="button"], a.btn');
                for (const btn of btns) {
                    const t = (btn.textContent || '').trim();
                    if (t === '确定') { btn.click(); }
                }
                for (const btn of btns) {
                    const t = (btn.textContent || '').trim();
                    if (t === '关闭') { btn.click(); }
                }
            }
        }
        """)

    def _dismiss_dialogs(self):
        """Poll-dismiss overlays until all dialogs are gone or timeout."""
        for _ in range(8):
            try:
                self._dismiss_overlay()
            except Exception as e:
                logger.debug("弹窗 dismiss 异常: %s", e)
                return
            remaining = self.page.evaluate(
                '() => document.querySelectorAll('
                '".dialog, .modal, .popup, [role=\\"dialog\\"], [role=\\"alertdialog\\"], '
                '.layui-layer-dialog, .layui-layer, .ui-dialog"'
                ').length'
            )
            if remaining == 0:
                break
            time.sleep(0.5)

    def _collect_all_pages(self):
        """翻页循环，viewId 去重"""
        all_records = {}
        page_num = 1

        while True:
            records = self.page.evaluate(r"""
            () => {
                const rows = document.querySelectorAll('#tbody-result tr');
                return Array.from(rows).map(r => {
                    const tds = r.querySelectorAll('td');
                    if (tds.length < 4) return null;
                    if (Array.from(r.children).every(c => c.tagName === 'TH')) return null;
                    const a = r.querySelector('a[onclick*="showDetail"]');
                    const onclick = a?.getAttribute('onclick') || '';
                    const vid = onclick.match(/showDetail\((\d+)/) || [];
                    return {
                        name: tds[1]?.innerText?.trim() || '',
                        caseNo: tds[3]?.innerText?.trim() || '',
                        date: tds[2]?.innerText?.trim() || '',
                        viewId: vid[1] || '',
                    };
                }).filter(r => r && r.viewId);
            }
            """)

            new_count = 0
            for rec in records:
                vid = rec["viewId"]
                if vid not in all_records:
                    rec["timestamp"] = parse_chinese_date(rec.get("date", ""))
                    all_records[vid] = rec
                    new_count += 1

            has_next = self.page.evaluate("""
            () => {
                const btn = document.getElementById('next-btn');
                return btn && !btn.disabled && btn.offsetParent !== null;
            }
            """)
            logger.debug("第%d页: %d条 新增%d 累计%d next=%s",
                         page_num, len(records), new_count, len(all_records), has_next)

            if not has_next:
                has_next = self.page.evaluate(
                    '() => (document.body?.innerText || "").includes("下一页")'
                )
            if not has_next:
                break
            if new_count == 0:
                logger.warning("翻页后无新增 viewId，翻页可能失效")

            self.page.evaluate("nextPage()")
            time.sleep(3)
            try:
                self.page.wait_for_load_state("networkidle", timeout=10000)
            except Exception:
                pass
            page_num += 1

        return list(all_records.values())

# ---------------------------------------------------------------------------
# OpenCV 弹窗提取 — 纯像素分析，不依赖 DOM 选择器
# ---------------------------------------------------------------------------
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

# ---------------------------------------------------------------------------
# Module E: DetailScreenshot
# ---------------------------------------------------------------------------
class DetailScreenshot:
    def __init__(self, page, output_dir, interval_sec=2.0):
        self.page = page
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.interval_sec = interval_sec

    def capture_all(self, records):
        """批量截取详情弹窗，返回 {viewId: filepath} 映射"""
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

# ---------------------------------------------------------------------------
# Module F: FeishuWriter (stub — phase ④)
# ---------------------------------------------------------------------------
class FeishuWriter:
    """飞书多维表格写入。当前为 stub，阶段④实现。"""

    def __init__(self, config):
        feishu = config.get("feishu", {})
        self.app_token = feishu.get("app_token", "")
        self.raw_table_id = feishu.get("raw_table", {}).get("id", "")
        self.raw_fields = feishu.get("raw_table", {}).get("fields", {})
        dt = feishu.get("detail_table", {})
        self.detail_table_id = dt.get("id", "")
        self.detail_fields = dt.get("fields", {})
        self.dedup_options = dt.get("dedup_options", {})
        self.batch_field_id = feishu.get("raw_table", {}).get("batch_field_id", "")

    def write_query_results(self, records, company, batch_id=""):
        """Stub: 写 raw_每日一级切片（阶段④实现）

        Args:
            records: [{"name": str, "caseNo": str, "date": str, "viewId": str}, ...]
            company: 查询公司名
            batch_id: 批次号，格式 {YYYYMMDD}-{subsite}
        """
        if not self.app_token or not self.raw_table_id:
            logger.info("飞书未配置，跳过 raw 表写入")
            return []
        logger.warning("FeishuWriter.write_query_results: 尚未实现（阶段④）")
        return []

    def upload_screenshots(self, records, screenshot_map):
        """Stub: 按 viewId 精确匹配上传截图到 tbl_二级录入表（阶段④实现）

        Args:
            records: [{"viewId": str, "caseNo": str, ...}, ...]
            screenshot_map: {viewId: filepath}

        实施方案: 截图上传需走 lark-cli（App cli_a94f3），因为 OpenClaw 内置
        feishu 工具（App cli_a9177）与 lark-cli 的 token 不互通。
        """
        if not self.app_token or not self.detail_table_id:
            logger.info("飞书未配置，跳过截图上传")
            return
        logger.warning("FeishuWriter.upload_screenshots: 尚未实现（阶段④）")

# ---------------------------------------------------------------------------
# Module G: ScreenshotBackfiller — Phase B 截图补全
# ---------------------------------------------------------------------------
class ScreenshotBackfiller:
    """Phase B 截图补全：查案件主表 missing → re-query → 逐条截图上传。

    一个浏览器 session 完成当日所有缺失截图的补全。
    流程：
      1. 查询案件主表中「截图」为空的记录
      2. 通过 raw_一级 DuplexLink 获取真实 viewId（不靠 batch JSON 推测）
      3. 按公司分组，依次搜索 → 过验证码 → showDetail → 截图 → 上传
    """

    def __init__(self, config, batch_id, max_per_session=10):
        feishu = config.get("feishu", {})
        self.app_token = feishu.get("app_token", "")
        self.raw_table_id = feishu.get("raw_table", {}).get("id", "")
        self.detail_table_id = feishu.get("detail_table", {}).get("id", "")
        self.batch_id = batch_id
        self.max_per_session = max_per_session
        self.captcha_server = config.get("captcha_server", "http://localhost:8001")
        self.config = config

    # ── Feishu helpers (thin wrappers around write_to_bitable) ──

    @staticmethod
    def _lark_api(method, path, data=None):
        import writers.feishu as wtb
        return wtb.lark_api(method, path, data)

    @staticmethod
    def _find_raw_record_by_case(case_record_id):
        """在 raw 表中查找链接到指定 case record 的记录，返回 raw record dict 或 None"""
        import writers.feishu as wtb
        raw_table = wtb.RAW_TABLES.get("zhixing", "")
        filter_payload = {
            "conjunction": "and",
            "conditions": [
                {"field_name": "案件主表", "operator": "contains",
                 "value": [case_record_id]}
            ],
        }
        path = f"/open-apis/bitable/v1/apps/{wtb.APP_TOKEN}/tables/{raw_table}/records/search"
        resp = wtb.lark_api("POST", path, {"filter": filter_payload, "page_size": 1})
        if not resp or resp.get("code") != 0:
            return None
        items = resp.get("data", {}).get("items", [])
        return items[0] if items else None

    # ── Main API ──

    def find_missing_screenshots(self):
        """查询案件主表中「截图」为空的记录，通过 DuplexLink 获取真实 viewId。

        返回: [(viewId, caseNo, case_record_id, company), ...]
        """
        import writers.feishu as wtb

        # 1. 查案件主表 — 截图字段为空
        filter_payload = {
            "conjunction": "and",
            "conditions": [
                {"field_name": wtb.CASE_FIELD_SCREENSHOT, "operator": "isEmpty"}
            ],
        }
        path = f"/open-apis/bitable/v1/apps/{wtb.APP_TOKEN}/tables/{wtb.CASE_TABLE}/records/search"
        resp = self._lark_api("POST", path, {"filter": filter_payload, "page_size": 500})
        if not resp or resp.get("code") != 0:
            logger.warning("查询案件主表失败")
            return []

        items = resp.get("data", {}).get("items", [])
        if not items:
            logger.info("案件主表无缺失截图记录")
            return []

        logger.info("案件主表 %d 条记录缺截图，开始获取 viewId ...", len(items))

        missing = []
        for item in items:
            case_record_id = item["record_id"]
            case_fields = item.get("fields", {})

            # 2. 通过 raw 表「案件主表」DuplexLink 反向查找 raw 记录
            raw_record = self._find_raw_record_by_case(case_record_id)
            if not raw_record:
                logger.debug("case=%s 无关联 raw 记录，跳过", case_record_id)
                continue

            raw_fields = raw_record.get("fields", {})
            view_field = raw_fields.get("查看", "")
            view_id = wtb._parse_view_id(view_field)
            if not view_id:
                logger.debug("case=%s raw 记录无 viewId，跳过", case_record_id)
                continue

            company = wtb._extract_text(raw_fields.get("被执行人", ""))
            case_no = wtb._extract_text(case_fields.get(wtb.CASE_FIELD_CASE_NO, ""))

            if not company:
                logger.debug("case=%s 无被执行人，跳过", case_record_id)
                continue

            missing.append((view_id, case_no, case_record_id, company))
            logger.debug("  viewId=%s case=%s company=%s", view_id, case_no, company)

        logger.info("获取完成: %d 条有效缺截图记录", len(missing))
        return missing

    def backfill_batch(self, records):
        """按公司分组截图回填。

        records: [(viewId, caseNo, case_record_id, company), ...]
        """
        import writers.feishu as wtb
        from collections import defaultdict

        # 按公司分组
        by_company = defaultdict(list)
        for vid, cno, rid, comp in records:
            by_company[comp].append((vid, cno, rid))

        logger.info("Phase B 截图回填: %d 家公司, %d 条记录", len(by_company), len(records))

        clean_env()
        solver = CaptchaSolver(self.captcha_server)
        if not solver.health_check():
            logger.error("captcha-solver 不可用，Phase B 终止")
            return

        screenshots_dir = Path(self.config.get("output", {}).get(
            "screenshots_dir", "output/screenshots"))
        screenshots_dir.mkdir(parents=True, exist_ok=True)

        success = 0
        fail = 0

        with BrowserManager(self.config) as bm:
            bm.navigate("zhixing")

            for company, entries in by_company.items():
                logger.info("--- 公司: %s (%d 条) ---", company, len(entries))

                # 搜索公司，过验证码
                if not self._search_company(bm.page, solver, company):
                    logger.warning("搜索失败: %s，跳过该公司 %d 条", company, len(entries))
                    fail += len(entries)
                    continue

                # 逐条截图 + 上传
                for view_id, case_no, case_record_id in entries:
                    png_path = screenshots_dir / f"detail_{view_id}.png"
                    logger.info("  viewId=%s case=%s", view_id, case_no)

                    # showDetail → 截图 → 关弹窗
                    if not self._capture_detail(bm.page, view_id, str(png_path)):
                        logger.warning("  截图失败")
                        fail += 1
                        continue

                    # 上传截图到飞书
                    file_token = wtb.lark_upload_media(str(png_path))
                    if not file_token:
                        logger.warning("  上传失败")
                        fail += 1
                        continue

                    if wtb.lark_update_record(
                        wtb.CASE_TABLE, case_record_id,
                        {wtb.CASE_FIELD_SCREENSHOT: [{"file_token": file_token}]},
                    ):
                        logger.info("  ✅ 上传成功")
                        success += 1
                    else:
                        logger.warning("  ❌ 写入失败")
                        fail += 1

                    time.sleep(1)

        logger.info("Phase B 完成: ✅ %d, ❌ %d", success, fail)

    def _search_company(self, page, solver, company):
        """在 zhixing 子站搜索公司名，过验证码。返回 True/False"""
        for attempt in range(8):
            page.fill("#pName", company)
            page.wait_for_timeout(500)

            b64 = solver.get_captcha(page)
            if not b64:
                page.wait_for_timeout(1000)
                continue

            text, conf = solver.solve(b64)
            logger.debug("  OCR: '%s' conf=%.3f", text, conf)
            if not text or not text.strip():
                solver.refresh(page)
                continue

            page.fill("#yzm", text.strip())
            page.wait_for_timeout(300)

            try:
                page.evaluate("search()")
            except Exception:
                pass
            time.sleep(2)
            try:
                page.wait_for_load_state("networkidle", timeout=15000)
            except Exception:
                pass
            page.wait_for_timeout(1000)

            body = page.inner_text("body")
            if "验证码错误" in body or "验证码已过期" in body:
                logger.debug("  验证码被拒 (attempt %d)", attempt + 1)
                solver.refresh(page)
                continue
            if "没有找到" in body:
                logger.info("  无结果")
                return False

            rows = page.evaluate(
                '() => document.querySelectorAll("#tbody-result tr").length')
            if rows > 0:
                logger.info("  查询成功: %d 条", rows)
                return True

            logger.debug("  rows=0 (attempt %d)", attempt + 1)
            solver.refresh(page)

        return False

    def _capture_detail(self, page, view_id, output_path):
        """showDetail(viewId) → 等弹窗 → 截图 → 关弹窗。返回 True/False"""
        ok = page.evaluate(f"""
            () => {{
                const el = document.querySelector('a[onclick*="showDetail({view_id})"]');
                if (el) {{ el.click(); return true; }}
                if (typeof showDetail === 'function') {{ showDetail({view_id}); return true; }}
                return false;
            }}
        """)
        if not ok:
            return False

        time.sleep(2)

        screenshot_bytes = page.screenshot(full_page=False)
        crop_w, crop_h = extract_popup_from_bytes(screenshot_bytes, output_path)
        if crop_w is None:
            page.screenshot(path=output_path, full_page=False)

        # 关闭弹窗
        page.evaluate("""
            () => {
                const dialogs = document.querySelectorAll(
                    '.dialog, .modal, .popup, [role="dialog"], [role="alertdialog"], '
                    + '.layui-layer-dialog, .layui-layer, .ui-dialog');
                const containers = dialogs.length > 0 ? Array.from(dialogs) : [document.body];
                for (const d of containers) {
                    const btns = d.querySelectorAll('button, a, span, div');
                    for (const btn of btns) {
                        const t = (btn.textContent || '').trim();
                        if (t === '关闭') { btn.click(); return; }
                    }
                }
            }
        """)
        time.sleep(1)
        page.keyboard.press("Escape")
        time.sleep(1)
        return True

    def run(self):
        """Phase B 主入口：查 missing → 按公司分组回填"""
        missing = self.find_missing_screenshots()
        if not missing:
            print("Phase B: 无缺失截图，跳过")
            return []

        print(f"Phase B: {len(missing)} 条缺失截图，开始回填")
        self.backfill_batch(missing)
        return missing


# ---------------------------------------------------------------------------
# Module H: BatchRunner
# ---------------------------------------------------------------------------
class BatchRunner:
    def __init__(self, config, subsite, mode="screenshot", batch_id="",
                 feishu_enabled=False, resume=False, max_per_session=10,
                 output_path=None):
        waf_cfg = config.get("waf", {})
        out_cfg = config.get("output", {})
        self.config = config
        self.subsite = subsite
        self.mode = mode
        self.batch_id = batch_id
        self.feishu_enabled = feishu_enabled
        self.resume = resume
        self.max_per_session = max_per_session
        self.output_path = output_path

        self.screenshots_enabled = mode != "text-only"
        self.company_interval = waf_cfg.get("company_interval_sec", 30)
        self.cooldown_on_block = waf_cfg.get("cooldown_on_block_sec", 300)
        self.max_consecutive_fails = waf_cfg.get("max_consecutive_fails", 3)
        self.captcha_max_retries = waf_cfg.get("captcha_max_retries", 5)
        self.screenshot_interval = waf_cfg.get("screenshot_interval_sec", 2)

        self.output_dir = Path(out_cfg.get("dir", "output"))
        self.screenshots_dir = Path(out_cfg.get("screenshots_dir", "output/screenshots"))
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.screenshots_dir.mkdir(parents=True, exist_ok=True)

        self.progress_file = self.output_dir / f".progress_{datetime.now().strftime('%Y%m%d')}.jsonl"
        self.results = {"success": [], "no_results": [], "blocked": [], "errors": []}

    def run(self, companies):
        completed = set()
        if self.resume and self.progress_file.exists():
            completed = self._read_progress()
            logger.info("断点续跑: %d 家已完成，跳过", len(completed))

        pending = [(c, i) for i, c in enumerate(companies) if c not in completed]
        if not pending:
            logger.info("所有公司已完成，无需续跑")
            return self.results

        logger.info("批量查询: %d 家（跳过 %d）", len(pending), len(completed))
        solver = CaptchaSolver(self.config.get("captcha_server", "http://localhost:8001"))

        bm = BrowserManager(self.config)
        bm.launch()
        bm.navigate(self.subsite)

        engine = QueryEngine(bm.page, solver, self.captcha_max_retries, self.subsite)
        screenshotter = DetailScreenshot(bm.page, self.screenshots_dir, self.screenshot_interval) \
            if self.screenshots_enabled else None
        feishu = FeishuWriter(self.config) if self.feishu_enabled else None

        consecutive_fails = 0

        for idx, (company, orig_idx) in enumerate(pending):
            logger.info("[%d/%d] %s", idx + 1, len(pending), company)

            try:
                bm.page.evaluate("document.getElementById('pName').value = ''")
                bm.page.fill("#pName", company)

                # 每次查询前强制刷新验证码，避免跨公司复用的过期验证码
                solver.refresh(bm.page)
                logger.debug("已刷新验证码（避免跨公司复用导致 TTL 过期）")

                records = engine.query(company)

                if records:
                    screenshot_map = {}
                    if screenshotter:
                        screenshot_map = screenshotter.capture_all(records)

                    self._save_result(company, records, screenshot_map)
                    self.results["success"].append({
                        "company": company, "count": len(records), "records": records,
                    })
                    consecutive_fails = 0

                    if feishu:
                        feishu.write_query_results(records, company, self.batch_id)
                        if screenshot_map:
                            feishu.upload_screenshots(records, screenshot_map)

                    logger.info("[%d/%d] %s: ✅ %d条", idx + 1, len(pending), company, len(records))
                else:
                    self.results["no_results"].append(company)
                    consecutive_fails = 0  # 无结果不是浏览器故障，重置计数
                    logger.info("[%d/%d] %s: ❌ 无结果", idx + 1, len(pending), company)

                self._mark_progress(company)

            except WafBlockedError as e:
                logger.warning("WAF 封禁: %s", e)
                self.results["blocked"].append(company)
                consecutive_fails += 1
                time.sleep(self.cooldown_on_block)

            except Exception as e:
                logger.error("%s: %s", company, e)
                self.results["errors"].append({"company": company, "error": str(e)})
                consecutive_fails += 1

            # 连续失败 → 重启浏览器
            if consecutive_fails >= self.max_consecutive_fails:
                logger.warning("连续失败 %d 次，重启浏览器", consecutive_fails)
                try:
                    bm.close()
                except Exception:
                    pass
                time.sleep(self.cooldown_on_block)
                try:
                    bm.launch()
                    bm.navigate(self.subsite)
                except Exception as e:
                    logger.error("浏览器重启失败: %s，跳过剩余公司", e)
                    break
                engine = QueryEngine(bm.page, solver, self.captcha_max_retries, self.subsite)
                if screenshotter:
                    screenshotter = DetailScreenshot(
                        bm.page, self.screenshots_dir, self.screenshot_interval
                    )
                consecutive_fails = 0

            # 公司间冷却
            if idx < len(pending) - 1:
                time.sleep(self.company_interval)

        bm.close()
        self._save_summary()
        if self.output_path:
            self.save_batch_json(self.output_path)
        return self.results

    def _save_result(self, company, records, screenshot_map=None):
        if screenshot_map is None:
            screenshot_map = {}
        ts = datetime.now(timezone.utc).isoformat()
        # 嵌入每个 record 的 screenshot 路径
        for rec in records:
            rec["screenshot"] = screenshot_map.get(rec["viewId"], "")
        data = {
            "company": company,
            "subsite": self.subsite,
            "batch_id": self.batch_id,
            "query_time": ts,
            "total": len(records),
            "records": records,
            "screenshot_map": screenshot_map,
        }
        safe_name = re.sub(r"[^\w\-]", "_", company)[:40]
        out_path = self.output_dir / f"query_{safe_name}_{int(time.time())}.json"
        with open(out_path, "w") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        logger.debug("结果已保存: %s", out_path)

    def _read_progress(self):
        done = set()
        with open(self.progress_file) as f:
            for line in f:
                try:
                    entry = json.loads(line.strip())
                    done.add(entry.get("company", ""))
                except json.JSONDecodeError:
                    continue
        return done

    def _mark_progress(self, company):
        with open(self.progress_file, "a") as f:
            f.write(json.dumps({"company": company, "time": int(time.time())},
                               ensure_ascii=False) + "\n")

    def _save_summary(self):
        ts = datetime.now(timezone.utc).isoformat()
        summary = {
            "query_time": ts,
            "subsite": self.subsite,
            "total": len(self.results["success"]) + len(self.results["no_results"])
                     + len(self.results["blocked"]) + len(self.results["errors"]),
            "success": len(self.results["success"]),
            "no_results": len(self.results["no_results"]),
            "blocked": len(self.results["blocked"]),
            "errors": len(self.results["errors"]),
            "companies": {k: [c["company"] if isinstance(c, dict) else c for c in v]
                          for k, v in self.results.items()},
        }
        path = self.output_dir / f"summary_{int(time.time())}.json"
        with open(path, "w") as f:
            json.dump(summary, f, ensure_ascii=False, indent=2)
        logger.info("汇总已保存: %s", path)

    def _build_batch_json(self):
        """构建合并 batch JSON。返回 dict"""
        tz = timezone(timedelta(hours=8))
        now = datetime.now(tz).isoformat()

        companies = []
        for c in self.results["success"]:
            companies.append({
                "company": c["company"],
                "status": "ok",
                "total": c["count"],
                "records": c["records"],
            })
        for c in self.results["no_results"]:
            companies.append({
                "company": c if isinstance(c, str) else c["company"],
                "status": "no_results",
                "total": 0,
                "records": [],
            })
        for c in self.results["blocked"]:
            companies.append({
                "company": c if isinstance(c, str) else c,
                "status": "waf_blocked",
                "error": "WAF 封禁",
                "total": 0,
                "records": [],
            })
        for c in self.results["errors"]:
            companies.append({
                "company": c["company"],
                "status": "error",
                "error": c.get("error", "未知错误"),
                "total": 0,
                "records": [],
            })

        total_records = sum(c["total"] for c in companies)

        return {
            "batch_id": self.batch_id,
            "subsite": self.subsite,
            "query_time": now,
            "companies": companies,
            "summary": {
                "total_companies": len(companies),
                "success": len(self.results["success"]),
                "waf_retry": len(self.results["blocked"]),
                "total_records": total_records,
            },
        }

    def save_batch_json(self, output_path):
        """写入合并 batch JSON 到 output_path"""
        data = self._build_batch_json()
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "w") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        logger.info("合并 JSON 已保存: %s (%d 家公司, %d 条记录)",
                    output_path, data["summary"]["total_companies"],
                    data["summary"]["total_records"])

# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------
def run_diagnose(config, subsite):
    """--diagnose: 检查 WAF 状态和子站可用性"""
    setup_environment()
    solver = CaptchaSolver(config.get("captcha_server", "http://localhost:8001"))

    # Step 1: captcha-solver 健康检查
    print("=" * 50)
    print("诊断: 执行信息查询 CLI")
    print("=" * 50)
    print(f"\n[1] captcha-solver ({config.get('captcha_server', 'http://localhost:8001')}) ... ", end="", flush=True)
    if solver.health_check():
        print("✅ OK")
    else:
        print("❌ 不可用")
        print("    → 启动: cd ~/workspace-main/projects/captcha-solver && PORT=8001 python main.py")
        return 3

    # Step 2: 浏览器 + WAF 检测
    print(f"[2] WAF 检测 (/{subsite}/) ... ", end="", flush=True)
    bm = BrowserManager(config)
    try:
        bm.launch()
        result = bm.diagnose(subsite)
        if result["status"] == "ok":
            print("✅ 通过")
            print(f"    #yzm={result['yzm_ready']}  #pName={result['pname_ready']}  body_len={result['body_len']}")
        else:
            print(f"❌ {result['status']}")
            print(f"    {result.get('error', '')}")
    except Exception as e:
        print(f"❌ 异常: {e}")
    finally:
        try:
            bm.close()
        except Exception:
            pass

    # Step 3: playwright-stealth 版本
    print(f"[3] playwright-stealth ... ", end="", flush=True)
    try:
        import playwright_stealth
        ver = getattr(playwright_stealth, "__version__", "?")
        print(f"✅ v{ver}")
    except ImportError:
        print("❌ 未安装")

    # Step 4: 依赖检查
    print("[4] venv 依赖 ... ", end="", flush=True)
    try:
        import playwright
        import yaml
        import requests
        print("✅ playwright + pyyaml + requests")
    except ImportError as e:
        print(f"❌ {e}")

    print("\n" + "=" * 50)
    print("诊断完成")
    return 0

def _generate_batch_id(subsite):
    """生成批次号: {YYYYMMDD}-{subsite}"""
    return f"{datetime.now().strftime('%Y%m%d')}-{subsite}"

def run_single(config, args):
    """单条查询"""
    setup_environment()
    solver = CaptchaSolver(args.captcha_server or config.get("captcha_server", "http://localhost:8001"))

    if not solver.health_check():
        logger.error("captcha-solver 不可用: %s", solver.server_url)
        return 3

    mode = args.mode
    screenshot_mode = not args.no_screenshots and mode != "text-only"
    batch_id = args.batch_id or _generate_batch_id(args.subsite)

    out_dir = Path(args.output_dir or config.get("output", {}).get("dir", "output"))
    ss_dir = Path(args.output_dir or config.get("output", {}).get("screenshots_dir", "output/screenshots"))
    out_dir.mkdir(parents=True, exist_ok=True)
    ss_dir.mkdir(parents=True, exist_ok=True)

    bm = BrowserManager(config)
    try:
        bm.launch()
        bm.navigate(args.subsite)
        engine = QueryEngine(bm.page, solver,
                             config.get("waf", {}).get("captcha_max_retries", 5),
                             args.subsite)
        records = engine.query(args.company)

        if not records:
            return 1

        # 输出 JSON（内嵌截图映射）
        ts = datetime.now(timezone.utc).isoformat()
        screenshot_map = {}
        if screenshot_mode:
            interval = config.get("waf", {}).get("screenshot_interval_sec", 2)
            ss = DetailScreenshot(bm.page, ss_dir, interval)
            screenshot_map = ss.capture_all(records)  # {viewId: filepath}

        result = {
            "company": args.company,
            "subsite": args.subsite,
            "batch_id": batch_id,
            "query_time": ts,
            "total": len(records),
            "records": records,
            "screenshot_map": screenshot_map,  # viewId → path, Phase B 用
        }
        # 同时嵌入每个 record 方便阅读
        for rec in result["records"]:
            rec["screenshot"] = screenshot_map.get(rec["viewId"], "")

        safe_name = re.sub(r"[^\w\-]", "_", args.company)[:40]
        out_path = out_dir / f"query_{safe_name}_{int(time.time())}.json"
        with open(out_path, "w") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)

        logger.info("结果已保存: %s", out_path)
        logger.info("共 %d 条记录", len(records))

        # 飞书写入
        if args.feishu:
            feishu = FeishuWriter(config)
            feishu.write_query_results(records, args.company, batch_id)
            if screenshot_map:
                feishu.upload_screenshots(records, screenshot_map)

        return 0
    except WafBlockedError as e:
        logger.error("WAF 封禁: %s", e)
        return 2
    finally:
        bm.close()

def run_backfill(config, args):
    """Phase B 截图补全"""
    setup_environment()
    solver = CaptchaSolver(args.captcha_server or config.get("captcha_server", "http://localhost:8001"))

    if not solver.health_check():
        logger.error("captcha-solver 不可用: %s", solver.server_url)
        return 3

    backfiller = ScreenshotBackfiller(config, args.batch_id, args.max_per_session)
    backfiller.run()
    return 0

def run_batch(config, args):
    """批量查询"""
    setup_environment()
    solver = CaptchaSolver(args.captcha_server or config.get("captcha_server", "http://localhost:8001"))

    if not solver.health_check():
        logger.error("captcha-solver 不可用: %s", solver.server_url)
        return 3

    companies = load_company_list(args.batch)
    mode = args.mode
    batch_id = args.batch_id or _generate_batch_id(args.subsite)

    runner = BatchRunner(
        config=config,
        subsite=args.subsite,
        mode=mode,
        batch_id=batch_id,
        feishu_enabled=args.feishu,
        resume=args.resume,
        max_per_session=args.max_per_session,
        output_path=args.output,
    )
    results = runner.run(companies)

    success = len(results["success"])
    no_results = len(results["no_results"])
    blocked = len(results["blocked"])
    errors = len(results["errors"])

    logger.info("批量完成: ✅%d 无结果%d 封禁%d 错误%d", success, no_results, blocked, errors)

    if blocked > 0 and success == 0:
        return 2
    if success == 0 and no_results > 0:
        return 1
    if errors > 0 and success == 0:
        return 1
    return 0

# ---------------------------------------------------------------------------
# CLI Entry Point
# ---------------------------------------------------------------------------
def build_parser():
    parser = argparse.ArgumentParser(
        prog="zxgk_query",
        description="中国执行信息公开网 统一查询 CLI",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python3 zxgk_query.py --company "XX公司"
  python3 zxgk_query.py --company "XX公司" --mode text-only --feishu
  python3 zxgk_query.py --company "XX公司" --mode full --feishu
  python3 zxgk_query.py --batch config/companies.txt --feishu
  python3 zxgk_query.py --batch config/companies.txt --mode full --feishu --resume
  python3 zxgk_query.py --mode backfill --batch-id "20260510-zhixing" --feishu
  python3 zxgk_query.py --diagnose
        """,
    )

    parser.add_argument("--config", default=None,
                        help="配置文件路径 (默认: config/zxgk.yaml)")
    parser.add_argument("--company", default=None,
                        help="公司名称（单条查询）")
    parser.add_argument("--batch", default=None,
                        help="批量公司列表文件 (YAML 或每行一个公司名的文本文件)")
    parser.add_argument("--subsite", default="zhixing",
                        choices=["zhixing", "shixin", "xgl"],
                        help="子站 (默认: zhixing)")
    parser.add_argument("--no-screenshots", action="store_true", default=False,
                        help="禁用详情弹窗截图（仅 --mode screenshot 模式有效）")
    parser.add_argument("--feishu", action="store_true", default=False,
                        help="写入飞书多维表格")
    parser.add_argument("--mode", default="screenshot",
                        choices=["text-only", "screenshot", "full", "backfill"],
                        help="运行模式: text-only(仅文本+写一级表) / screenshot(默认,查询+即时截图) "
                             "/ full(Phase A→等待计算→Phase B) / backfill(仅补全截图)")
    parser.add_argument("--batch-id", default=None,
                        help="批次号，格式 {YYYYMMDD}-{subsite}（backfill/full 模式）")
    parser.add_argument("--no-wait", action="store_true", default=False,
                        help="full 模式下跳过飞书计算等待")
    parser.add_argument("--max-per-session", type=int, default=10,
                        help="单次浏览器 session 最大截图数（默认 10）")
    parser.add_argument("--captcha-server", default=None,
                        help="captcha-solver 地址 (默认: http://localhost:8001)")
    parser.add_argument("--output-dir", default=None,
                        help="输出目录 (默认: output/)")
    parser.add_argument("--output", default=None,
                        help="合并 JSON 输出路径（batch 模式）")
    parser.add_argument("--resume", action="store_true", default=False,
                        help="批量模式断点续跑")
    parser.add_argument("--diagnose", action="store_true", default=False,
                        help="诊断模式：检查 WAF 状态和依赖")
    parser.add_argument("--verbose", "-v", action="store_true", default=False,
                        help="详细日志")

    return parser

def main():
    parser = build_parser()
    args = parser.parse_args()

    if args.verbose:
        logger.setLevel(logging.DEBUG)

    config = load_config(args.config)

    # --diagnose: 诊断模式
    if args.diagnose:
        return run_diagnose(config, args.subsite)

    # --mode backfill 必须指定 --batch-id
    if args.mode == "backfill" and not args.batch_id:
        parser.error("--mode backfill 需要 --batch-id")

    # backfill 模式：不需要 --company/--batch，从 batch_id 提取 subsite
    if args.mode == "backfill":
        parts = args.batch_id.rsplit("-", 1)
        if len(parts) == 2 and parts[1] in config.get("subsites", {}):
            args.subsite = parts[1]
        args.feishu = True
        return run_backfill(config, args)

    # 其他模式必须指定 --company 或 --batch
    if not args.company and not args.batch:
        parser.error("请指定 --company 或 --batch")

    if args.company and args.batch:
        parser.error("--company 和 --batch 不能同时使用")

    # --mode full 自动启用飞书
    if args.mode == "full":
        args.feishu = True

    if args.company:
        return run_single(config, args)
    else:
        return run_batch(config, args)

if __name__ == "__main__":
    sys.exit(main())
