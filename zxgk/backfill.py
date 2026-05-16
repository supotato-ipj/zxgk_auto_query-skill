"""ScreenshotBackfiller — Phase B 截图补全"""
import os
import time
from collections import defaultdict
from pathlib import Path

from .browser import BrowserManager
from .captcha import CaptchaSolver
from .config import clean_env, logger


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

    # ── Feishu helpers (thin wrappers around writers/feishu.py) ──

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
                        try:
                            os.remove(str(png_path))
                        except OSError:
                            pass
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

        from .screenshot import extract_popup_from_bytes
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
