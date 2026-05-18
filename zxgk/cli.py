"""zxgk CLI — 命令入口和参数解析"""
import argparse
import json
import logging
import re
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .browser import BrowserManager
from .captcha import CaptchaSolver
from .config import load_config, load_company_list, logger, setup_environment
from .exceptions import WafBlockedError
from .query import QueryEngine
from .runner import BatchRunner
from .screenshot import DetailScreenshot


def _generate_batch_id(subsite):
    """生成批次号: {YYYYMMDD}-{subsite}"""
    return f"{datetime.now().strftime('%Y%m%d')}-{subsite}"


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
        except Exception as e:
            logger.debug("diagnose browser close: %s", e)

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


def run_single(config, args):
    """单条查询"""
    setup_environment()
    args.subsite = args.subsite or "zhixing"
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

        # 飞书写入（委托给 writers/feishu.py）
        if args.feishu:
            import writers.feishu as wf
            try:
                wf.write_raw_table(records, args.subsite)
            except Exception as e:
                logger.warning("飞书 raw 表写入失败: %s", e)
            if screenshot_map:
                try:
                    wf.upload_screenshots_for_records(records, str(ss_dir), args.subsite)
                except Exception as e:
                    logger.warning("飞书截图上传失败: %s", e)

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

    from .backfill import ScreenshotBackfiller
    backfiller = ScreenshotBackfiller(config, args.batch_id, args.max_per_session)
    backfiller.run()
    return 0


def run_batch(config, args):
    """批量查询"""
    setup_environment()
    args.subsite = args.subsite or "zhixing"
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
    parser.add_argument("--subsite", default=None,
                        choices=["zhixing", "shixin", "xgl"],
                        help="子站 (默认: zhixing，async 模式下默认全部)")
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
    parser.add_argument("--async", "--parallel", dest="async_mode",
                        action="store_true", default=False,
                        help="异步并发模式：同时查询所有子站（--batch 模式下生效）")
    parser.add_argument("--diagnose", action="store_true", default=False,
                        help="诊断模式：检查 WAF 状态和依赖")
    parser.add_argument("--verbose", "-v", action="store_true", default=False,
                        help="详细日志")

    return parser


def run_async_batch(config, args):
    """异步并发批量查询（所有子站并行）"""
    import sys
    if sys.version_info < (3, 11):
        logger.error("--async 模式需要 Python 3.11+ (asyncio.TaskGroup)，当前: %s", sys.version)
        return 3
    import asyncio
    setup_environment()
    solver = CaptchaSolver(args.captcha_server or config.get("captcha_server", "http://localhost:8001"))

    if not solver.health_check():
        logger.error("captcha-solver 不可用: %s", solver.server_url)
        return 3

    companies = load_company_list(args.batch)
    mode = args.mode

    # 确定要查询的子站
    if args.subsite and args.subsite != "zhixing":
        # 用户指定了子站 → 只查该子站（异步路径，无明显并发收益但行为一致）
        subsites = [args.subsite]
    else:
        subsites = list(config.get("subsites", {}).keys()) or ["zhixing", "shixin", "xgl"]

    # full 模式自动启用飞书
    if mode == "full":
        args.feishu = True

    from .async_runner import run_parallel_subsites

    all_results = asyncio.run(run_parallel_subsites(
        config=config,
        companies=companies,
        subsites=subsites,
        mode=mode,
        feishu_enabled=args.feishu,
        resume=args.resume,
        max_per_session=args.max_per_session,
        output_dir=args.output_dir,
    ))

    # 汇总
    total_success = 0
    total_no = 0
    total_blocked = 0
    total_errors = 0
    for subsite, results in all_results.items():
        s = len(results["success"])
        n = len(results["no_results"])
        b = len(results["blocked"])
        e = len(results["errors"])
        total_success += s
        total_no += n
        total_blocked += b
        total_errors += e
        logger.info("[%s] ✅%d 无结果%d 封禁%d 错误%d", subsite, s, n, b, e)

    logger.info("总计: ✅%d 无结果%d 封禁%d 错误%d",
                total_success, total_no, total_blocked, total_errors)

    if total_blocked > 0 and total_success == 0:
        return 2
    if total_success == 0 and total_no > 0:
        return 1
    if total_errors > 0 and total_success == 0:
        return 1
    return 0


def main():
    parser = build_parser()
    args = parser.parse_args()

    if args.verbose:
        logger.setLevel(logging.DEBUG)

    config = load_config(args.config)

    # --diagnose: 诊断模式
    if args.diagnose:
        return run_diagnose(config, args.subsite or "zhixing")

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
    elif args.async_mode:
        return run_async_batch(config, args)
    else:
        return run_batch(config, args)
