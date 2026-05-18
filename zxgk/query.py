"""QueryEngine — 查询引擎：填表、OCR、提交、翻页收集"""

import time

from .config import logger, parse_chinese_date


# ── 模块级工具：弹窗处理（供 diagnose_subsites.py 等复用）──
def dismiss_overlay(page):
    """Dismiss confirmation dialogs and error popups (module-level, reusable).

    Clicks 确定/关闭 buttons scoped to dialog containers, then presses Escape
    as fallback for dialogs without clickable close buttons.
    """
    page.evaluate("""
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
    # Escape key as fallback (handles dialogs without clickable close buttons)
    page.keyboard.press("Escape")


def dismiss_dialogs(page, max_iterations=8):
    """Poll-dismiss overlays until all dialogs are gone or timeout (module-level, reusable)."""
    for _ in range(max_iterations):
        try:
            dismiss_overlay(page)
        except Exception as e:
            logger.debug("弹窗 dismiss 异常: %s", e)
            return
        remaining = page.evaluate(
            '() => document.querySelectorAll('
            '".dialog, .modal, .popup, [role=\\"dialog\\"], [role=\\"alertdialog\\"], '
            '.layui-layer-dialog, .layui-layer, .ui-dialog"'
            ').length'
        )
        if remaining == 0:
            break
        page.wait_for_timeout(500)


class QueryEngine:
    """查询引擎。

    调用方应在调用 query() 前确保页面验证码为新鲜状态
    （BatchRunner 在每个公司查询前自动刷新，run_single 刚完成导航验证码本就新鲜）。
    """

    def __init__(self, page, captcha_solver, max_retries=5, subsite="zhixing",
                 empty_result_max_retries=2):
        self.page = page
        self.solver = captcha_solver
        self.max_retries = max_retries
        self.subsite = subsite
        self.empty_result_max_retries = empty_result_max_retries

    def query(self, company):
        """查询 + 翻页收集所有结果，viewId 去重。返回 list[dict]"""
        last_failure_type = None
        consecutive_same_failure = 0
        empty_retries = 0

        for attempt in range(self.max_retries):
            # 渐进等待（按总次数 3 等分：1s / 3s / 5s）
            fast_end = max(1, self.max_retries // 3)
            cooldown_end = max(fast_end + 1, 2 * self.max_retries // 3)
            if attempt < fast_end:
                time.sleep(1)
            elif attempt < cooldown_end:
                time.sleep(3)
            else:
                time.sleep(5)

            # 最后 2 次尝试重建导航
            if attempt >= self.max_retries - 2:
                logger.info("重建导航: %s", self.subsite)
                self.page.goto(
                    f"https://zxgk.court.gov.cn/{self.subsite}/",
                    wait_until="networkidle",
                )
                time.sleep(3)

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
                    last_failure_type, consecutive_same_failure = self._track_failure(
                        "no_captcha", last_failure_type, consecutive_same_failure
                    )
                    if consecutive_same_failure == 0:
                        continue
                    continue

                text, conf = self.solver.solve(cap)
                logger.info("OCR: '%s' conf=%.3f", text, conf)

                if not text or not text.strip():
                    logger.warning("OCR 返回空字符串，跳过提交，刷新后重试")
                    self.solver.refresh(self.page)
                    last_failure_type, consecutive_same_failure = self._track_failure(
                        "ocr_empty", last_failure_type, consecutive_same_failure
                    )
                    if consecutive_same_failure == 0:
                        continue
                    continue
                if conf is not None and conf < 0.3:
                    logger.warning("OCR 置信度过低 (%.3f)，跳过提交", conf)
                    self.solver.refresh(self.page)
                    last_failure_type, consecutive_same_failure = self._track_failure(
                        "ocr_low_conf", last_failure_type, consecutive_same_failure
                    )
                    if consecutive_same_failure == 0:
                        continue
                    continue

                self.page.fill("#yzm", text)
                self._submit()
                # Extra safety: dismiss any late-appearing dialogs before reading result
                self._dismiss_dialogs()

                result_text = self.page.evaluate(
                    '() => document.getElementById("result-block")?.innerText || ""'
                )
                if "没有找到" in result_text:
                    if empty_retries < self.empty_result_max_retries:
                        logger.warning(
                            "查询返回'没有找到'(empty_retry %d/%d): %s",
                            empty_retries + 1, self.empty_result_max_retries, company,
                        )
                        empty_retries += 1
                        self.solver.refresh(self.page)
                        time.sleep(2)
                        continue
                    logger.info("查询无结果（经 %d 次重试确认）: %s", empty_retries + 1, company)
                    return []
                if "验证码错误" in result_text or "验证码已过期" in result_text:
                    logger.info("验证码被拒（%s），刷新后重试", result_text[:60].replace("\n", " "))
                    self.page.fill("#yzm", "")
                    self.solver.refresh(self.page)
                    last_failure_type, consecutive_same_failure = self._track_failure(
                        "captcha_rejected", last_failure_type, consecutive_same_failure
                    )
                    if consecutive_same_failure == 0:
                        continue
                    continue
                page_text = self.page.evaluate(
                    '() => (document.body?.innerText || "").substring(0, 500)'
                )
                if "没有找到" in page_text:
                    if empty_retries < self.empty_result_max_retries:
                        logger.warning(
                            "页面文本含'没有找到'(empty_retry %d/%d): %s",
                            empty_retries + 1, self.empty_result_max_retries, company,
                        )
                        empty_retries += 1
                        self.solver.refresh(self.page)
                        time.sleep(2)
                        continue
                    logger.info("查询无结果（经 %d 次重试确认）: %s", empty_retries + 1, company)
                    return []

                rows = self.page.evaluate(
                    '() => document.querySelectorAll("#tbody-result tr").length'
                )
                logger.debug("rows=%d", rows)

                if rows > 0:
                    records = self._collect_all_pages()
                    logger.info("查询成功: %d 条记录", len(records))
                    return records

                if rows == 0:
                    if conf is not None and conf < 0.65:
                        logger.warning(
                            "rows=0 且置信度低(%.3f)，验证码可能识错，重试验证", conf
                        )
                    else:
                        logger.debug(
                            "rows=0 置信度(%.3f)，可能是静默验证码错误，刷新重试", conf
                        )
                    if empty_retries < self.empty_result_max_retries:
                        empty_retries += 1
                        self.solver.refresh(self.page)
                        time.sleep(1)
                        continue
                    logger.info("rows=0 经 %d 次重试确认，接受为真无记录", empty_retries + 1)
                    return []

            except Exception as e:
                logger.warning("查询异常 (attempt %d/%d): %s", attempt + 1, self.max_retries, e)
                self.solver.refresh(self.page)
                last_failure_type, consecutive_same_failure = self._track_failure(
                    "exception", last_failure_type, consecutive_same_failure
                )
                if consecutive_same_failure == 0:
                    continue

        logger.warning("查询全部失败（%d 次重试）: %s", self.max_retries, company)
        return []

    def _track_failure(self, failure_type, last_failure_type, consecutive_same_failure):
        """追踪连续同类型失败，触发升级时重置计数器。返回 (last_type, count)"""
        if failure_type == last_failure_type:
            consecutive_same_failure += 1
        else:
            consecutive_same_failure = 1
            last_failure_type = failure_type

        if consecutive_same_failure >= 3:
            logger.warning(
                "连续 %d 次同类型失败(%s)，重载页面",
                consecutive_same_failure, failure_type,
            )
            self.page.reload()
            time.sleep(2)
            return (None, 0)

        return (last_failure_type, consecutive_same_failure)

    def _submit(self):
        for _ in range(5):
            ready = self.page.evaluate('() => typeof search === "function"')
            if ready:
                break
            self.page.wait_for_timeout(500)
        else:
            raise RuntimeError("search() 未定义，页面可能未加载完成")

        try:
            self.page.evaluate("initCurrentPage()")
        except Exception:
            logger.debug("initCurrentPage 不可用，跳过")
        self.page.evaluate("search()")
        self._dismiss_dialogs()
        try:
            self.page.wait_for_load_state("networkidle", timeout=15000)
        except Exception:
            pass
        self.page.wait_for_timeout(500)
        self._dismiss_dialogs()

    def _dismiss_dialogs(self):
        """Poll-dismiss overlays until all dialogs are gone or timeout.

        Delegates to module-level dismiss_dialogs for unified close logic.
        """
        dismiss_dialogs(self.page)

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
            self.page.wait_for_timeout(2000)
            try:
                self.page.wait_for_load_state("networkidle", timeout=10000)
            except Exception:
                pass
            page_num += 1

        return list(all_records.values())
