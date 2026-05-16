"""BrowserManager — Playwright 浏览器生命周期管理"""
import atexit
import signal
import subprocess
import sys
import time

from playwright.sync_api import sync_playwright
from playwright_stealth import Stealth

from .config import BROWSER_ARGS, logger
from .exceptions import SubsiteNavError, WafBlockedError

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
        _cleanup_orphans()
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
