"""AsyncBatchRunner — parallel subsite execution via ThreadPoolExecutor.

Each subsite runs in its own OS thread (sync Playwright, no asyncio context),
coordinated by shared ThreadRateGate + ThreadWafCircuitBreaker.
The async layer only spawns threads and collects results.

Usage:
    import asyncio
    from zxgk.async_runner import run_parallel_subsites

    asyncio.run(run_parallel_subsites(config, companies, subsites, ...))
"""

import asyncio
import concurrent.futures
import json
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .async_primitives import ThreadRateGate, ThreadWafCircuitBreaker
from .browser import BrowserManager
from .captcha import CaptchaSolver
from .config import logger
from .exceptions import WafBlockedError
from .query import QueryEngine
from .screenshot import DetailScreenshot


def _generate_batch_id(subsite):
    """生成批次号: {YYYYMMDD}_{subsite}"""
    return f"{datetime.now().strftime('%Y%m%d')}_{subsite}"


class AsyncBatchRunner:
    """Run one subsite's batch query with thread-safe gate/breaker coordination.

    The caller creates one instance per subsite and calls run() from a worker thread
    (via ThreadPoolExecutor). All instances share ThreadRateGate + ThreadWafCircuitBreaker.
    """

    def __init__(self, config, subsite, companies, mode, batch_id,
                 feishu_enabled, resume, max_per_session, output_path,
                 gate: ThreadRateGate, breaker: ThreadWafCircuitBreaker):
        waf_cfg = config.get("waf", {})
        out_cfg = config.get("output", {})
        self.config = config
        self.subsite = subsite
        self.companies = companies
        self.mode = mode
        self.batch_id = batch_id
        self.feishu_enabled = feishu_enabled
        self.resume = resume
        self.max_per_session = max_per_session
        self.output_path = output_path
        self._gate = gate
        self._breaker = breaker

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

        self.progress_file = self.output_dir / f".progress_{self.subsite}_{datetime.now().strftime('%Y%m%d')}.jsonl"
        self.results = {"success": [], "no_results": [], "blocked": [], "errors": []}

        # Browser / solver / engine created in run()
        self._bm = None
        self._solver = None
        self._engine = None
        self._screenshotter = None

    def run(self):
        """Execute batch query for this subsite (sync — called from worker thread)."""
        completed = set()
        if self.resume and self.progress_file.exists():
            completed = self._read_progress()
            logger.info("[%s] 断点续跑: %d 家已完成，跳过", self.subsite, len(completed))

        pending = [c for c in self.companies if c not in completed]
        if not pending:
            logger.info("[%s] 所有公司已完成，无需续跑", self.subsite)
            return self.results

        logger.info("[%s] 批量查询: %d 家（跳过 %d）", self.subsite, len(pending), len(completed))

        self._solver = CaptchaSolver(self.config.get("captcha_server", "http://localhost:8001"))
        self._bm = BrowserManager(self.config)
        self._bm.launch()
        self._bm.navigate(self.subsite)

        self._engine = QueryEngine(self._bm.page, self._solver,
                                   self.captcha_max_retries, self.subsite)
        self._screenshotter = DetailScreenshot(
            self._bm.page, self.screenshots_dir, self.screenshot_interval
        ) if self.screenshots_enabled else None

        consecutive_fails = 0

        for idx, company in enumerate(pending):
            # --- Thread-safe coordination ---
            self._gate.acquire()

            if not self._breaker.check():
                logger.info("[%s] WAF 冷却中，跳过 %s", self.subsite, company)
                self.results["blocked"].append(company)
                continue

            logger.info("[%s] [%d/%d] %s", self.subsite, idx + 1, len(pending), company)

            try:
                # --- Sync work runs in thread ---
                records = self._query_one_company(company)
            except WafBlockedError as e:
                logger.warning("[%s] WAF 封禁: %s", self.subsite, e)
                self.results["blocked"].append(company)
                consecutive_fails += 1
                self._breaker.trip()
                continue
            except Exception as e:
                logger.error("[%s] %s: %s", self.subsite, company, e)
                self.results["errors"].append({"company": company, "error": str(e)})
                consecutive_fails += 1
                continue

            if records:
                self.results["success"].append({
                    "company": company, "count": len(records), "records": records,
                })
                consecutive_fails = 0
                if self.feishu_enabled:
                    self._write_feishu(records)
                logger.info("[%s] [%d/%d] %s: ✅ %d条",
                            self.subsite, idx + 1, len(pending), company, len(records))
            else:
                self.results["no_results"].append(company)
                consecutive_fails = 0
                logger.info("[%s] [%d/%d] %s: ❌ 无结果",
                            self.subsite, idx + 1, len(pending), company)

            self._mark_progress(company)

            # 连续失败 → 重启浏览器
            if consecutive_fails >= self.max_consecutive_fails:
                logger.warning("[%s] 连续失败 %d 次，重启浏览器",
                               self.subsite, consecutive_fails)
                try:
                    self._bm.close()
                except Exception:
                    pass
                time.sleep(self.cooldown_on_block)
                try:
                    self._bm.launch()
                    self._bm.navigate(self.subsite)
                except Exception as e:
                    logger.error("[%s] 浏览器重启失败: %s，跳过剩余公司", self.subsite, e)
                    break
                self._engine = QueryEngine(self._bm.page, self._solver,
                                           self.captcha_max_retries, self.subsite)
                if self._screenshotter:
                    self._screenshotter = DetailScreenshot(
                        self._bm.page, self.screenshots_dir, self.screenshot_interval
                    )
                consecutive_fails = 0

        try:
            self._bm.close()
        except Exception:
            pass

        self._save_summary()
        if self.output_path:
            self.save_batch_json(self.output_path)
        return self.results

    def _query_one_company(self, company):
        """Sync: query one company, capture screenshots. Called directly from run()."""
        self._solver.refresh(self._bm.page)

        records = self._engine.query(company)  # may raise WafBlockedError

        if records and self._screenshotter:
            screenshot_map = self._screenshotter.capture_all(records)
            for rec in records:
                rec["screenshot"] = screenshot_map.get(rec["viewId"], "")

        return records

    def _write_feishu(self, records):
        """写入飞书多维表格（委托给 writers/feishu.py）"""
        import writers.feishu as wf
        try:
            wf.write_raw_table(records, self.subsite)
        except Exception as e:
            logger.warning("[%s] 飞书 raw 表写入失败: %s", self.subsite, e)
        # Upload screenshots for records that have them
        ss_records = [r for r in records if r.get("screenshot")]
        if ss_records:
            try:
                wf.upload_screenshots_for_records(
                    ss_records, str(self.screenshots_dir), self.subsite)
            except Exception as e:
                logger.warning("[%s] 飞书截图上传失败: %s", self.subsite, e)

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
            "total": (len(self.results["success"]) + len(self.results["no_results"])
                      + len(self.results["blocked"]) + len(self.results["errors"])),
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
        logger.info("[%s] 汇总已保存: %s", self.subsite, path)

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
        logger.info("[%s] 合并 JSON 已保存: %s (%d 家公司, %d 条记录)",
                    self.subsite, output_path,
                    data["summary"]["total_companies"],
                    data["summary"]["total_records"])


# ---------------------------------------------------------------------------
# Sync worker function (runs in ThreadPoolExecutor — no asyncio context)
# ---------------------------------------------------------------------------

def _run_subsite_sync(subsite, companies, config, mode, feishu_enabled, resume,
                      max_per_session, output_dir, gate, breaker):
    """Sync worker: run one subsite's full batch query in a thread pool thread.

    No asyncio context here — Playwright Sync API works natively.
    Returns (subsite, results_dict) so the async layer can collect results.
    """
    batch_id = _generate_batch_id(subsite)
    out_dir = Path(output_dir or config.get("output", {}).get("dir", "output"))
    output_path = out_dir / f"zxgk_batch_{batch_id}.json"

    runner = AsyncBatchRunner(
        config=config,
        subsite=subsite,
        companies=companies,
        mode=mode,
        batch_id=batch_id,
        feishu_enabled=feishu_enabled,
        resume=resume,
        max_per_session=max_per_session,
        output_path=str(output_path),
        gate=gate,
        breaker=breaker,
    )
    results = runner.run()
    return subsite, results


# ---------------------------------------------------------------------------
# Top-level async entry point
# ---------------------------------------------------------------------------
async def run_parallel_subsites(config, companies, subsites, mode="screenshot",
                                feishu_enabled=False, resume=False,
                                max_per_session=10, output_dir=None):
    """Run multiple subsites concurrently with shared rate limiting.

    Each subsite runs in its own thread pool worker — no asyncio event loop
    in the worker thread, so Playwright Sync API works natively.

    Args:
        config:           YAML config dict
        companies:        list of company name strings
        subsites:         list of subsite keys, e.g. ["zhixing","shixin","xgl"]
        mode:             "text-only" | "screenshot" | "full"
        feishu_enabled:   whether to write to Feishu
        resume:           resume from progress file
        max_per_session:  max screenshots per browser session
        output_dir:       override output directory

    Returns:
        dict: {subsite: results_dict, ...}
    """
    waf_cfg = config.get("waf", {})
    out_cfg = config.get("output", {})
    out_dir = Path(output_dir or out_cfg.get("dir", "output"))

    gate = ThreadRateGate(rate=1.0 / waf_cfg.get("company_interval_sec", 30), burst=1)
    breaker = ThreadWafCircuitBreaker(waf_cfg.get("cooldown_on_block_sec", 300))

    loop = asyncio.get_running_loop()
    with concurrent.futures.ThreadPoolExecutor(max_workers=len(subsites)) as pool:

        async def _run_one(subsite):
            try:
                result = await loop.run_in_executor(
                    pool,
                    _run_subsite_sync,
                    subsite, companies, config, mode,
                    feishu_enabled, resume, max_per_session,
                    str(out_dir), gate, breaker,
                )
                return result  # (subsite, results_dict)
            except Exception as e:
                logger.error("[%s] 子站任务异常: %s", subsite, e)
                return subsite, {"success": [], "no_results": [],
                                "blocked": [], "errors": [
                                    {"company": "__task__", "error": str(e)}]}

        gathered = await asyncio.gather(*(_run_one(s) for s in subsites))

    return dict(gathered)
