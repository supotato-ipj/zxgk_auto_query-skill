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
        time.sleep(0.5)


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
            time.sleep(3)
            try:
                self.page.wait_for_load_state("networkidle", timeout=10000)
            except Exception:
                pass
            page_num += 1

        return list(all_records.values())
