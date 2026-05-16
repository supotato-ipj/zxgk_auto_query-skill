"""BatchRunner — 批量查询编排"""
import json
import re
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .browser import BrowserManager
from .captcha import CaptchaSolver
from .config import logger
from .query import QueryEngine
from .screenshot import DetailScreenshot


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

        consecutive_fails = 0

        for idx, (company, orig_idx) in enumerate(pending):
            logger.info("[%d/%d] %s", idx + 1, len(pending), company)

            try:
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

                    if self.feishu_enabled:
                        self._write_feishu(records, screenshot_map)

                    logger.info("[%d/%d] %s: ✅ %d条", idx + 1, len(pending), company, len(records))
                else:
                    self.results["no_results"].append(company)
                    consecutive_fails = 0  # 无结果不是浏览器故障，重置计数
                    logger.info("[%d/%d] %s: ❌ 无结果", idx + 1, len(pending), company)

                self._mark_progress(company)

            except Exception as e:
                from .exceptions import WafBlockedError
                if isinstance(e, WafBlockedError):
                    logger.warning("WAF 封禁: %s", e)
                    self.results["blocked"].append(company)
                    consecutive_fails += 1
                    time.sleep(self.cooldown_on_block)
                else:
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

    def _write_feishu(self, records, screenshot_map):
        """写入飞书多维表格（委托给 writers/feishu.py）"""
        import writers.feishu as wf
        try:
            wf.write_raw_table(records, self.subsite)
        except Exception as e:
            logger.warning("飞书 raw 表写入失败: %s", e)
        if screenshot_map:
            try:
                wf.upload_screenshots_for_records(records, str(self.screenshots_dir), self.subsite)
            except Exception as e:
                logger.warning("飞书截图上传失败: %s", e)

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
