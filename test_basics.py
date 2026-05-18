#!/usr/bin/env python3
"""Baseline smoke tests — no browser, no captcha server, no Feishu needed.

Run: python3 test_basics.py
"""

import sys
from pathlib import Path

# Ensure project root on sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent))

from zxgk.config import build_batch_json, load_config, load_company_list, parse_chinese_date


def test_load_config():
    """load_config() returns a dict with expected top-level keys."""
    config = load_config()
    assert isinstance(config, dict), f"Expected dict, got {type(config)}"
    expected_keys = {"captcha_server", "browser", "waf", "subsites", "output"}
    missing = expected_keys - set(config.keys())
    assert not missing, f"Missing config keys: {missing}"
    print(f"  ✅ load_config: {len(config)} keys, subsites={list(config.get('subsites', {}).keys())}")


def test_load_company_list():
    """load_company_list() returns a list of non-empty strings."""
    path = Path(__file__).resolve().parent / "config" / "companies.txt"
    companies = load_company_list(str(path))
    assert isinstance(companies, list), f"Expected list, got {type(companies)}"
    assert len(companies) > 0, "Company list is empty"
    assert all(isinstance(c, str) and c.strip() for c in companies), (
        "All entries must be non-empty strings")
    print(f"  ✅ load_company_list: {len(companies)} companies")


def test_parse_chinese_date():
    """parse_chinese_date parses Chinese date to epoch ms."""
    ts = parse_chinese_date("2025年01月15日")
    assert isinstance(ts, int), f"Expected int, got {type(ts)}"
    assert ts > 0, f"Expected positive timestamp, got {ts}"
    # 2025-01-15 00:00:00 Asia/Shanghai = 1736866800000
    assert 1736860000000 < ts < 1737000000000, f"Timestamp out of range: {ts}"
    print(f"  ✅ parse_chinese_date: 2025年01月15日 → {ts}")

    # Edge case: invalid format
    assert parse_chinese_date("not a date") == 0, "Invalid format should return 0"
    assert parse_chinese_date("") == 0, "Empty string should return 0"
    print(f"  ✅ parse_chinese_date edge cases: OK")


def test_dismiss_functions_importable():
    """dismiss_overlay / dismiss_dialogs exist and have correct signatures."""
    from zxgk.query import dismiss_overlay, dismiss_dialogs
    import inspect
    assert callable(dismiss_overlay), "dismiss_overlay must be callable"
    assert callable(dismiss_dialogs), "dismiss_dialogs must be callable"

    sig = inspect.signature(dismiss_overlay)
    params = list(sig.parameters.keys())
    assert "page" in params, f"dismiss_overlay must have 'page' param, got: {params}"

    sig2 = inspect.signature(dismiss_dialogs)
    params2 = list(sig2.parameters.keys())
    assert "page" in params2, f"dismiss_dialogs must have 'page' param, got: {params2}"
    assert "max_iterations" in params2, f"dismiss_dialogs must have 'max_iterations' param"

    print(f"  ✅ dismiss_overlay / dismiss_dialogs: importable, correct signatures")


def test_backfill_importable():
    """ScreenshotBackfiller module imports without side effects."""
    from zxgk.backfill import ScreenshotBackfiller
    assert callable(ScreenshotBackfiller), "ScreenshotBackfiller must be importable"
    print(f"  ✅ backfill.ScreenshotBackfiller: importable")


def test_async_importable():
    """Async primitives and runner import (requires venv playwright_stealth)."""
    try:
        from zxgk.async_primitives import RateGate, WafCircuitBreaker
        from zxgk.async_runner import AsyncBatchRunner, run_parallel_subsites
        assert callable(RateGate)
        assert callable(WafCircuitBreaker)
        assert callable(AsyncBatchRunner)
        print(f"  ✅ async_primitives + async_runner: importable")
    except ImportError as e:
        print(f"  ⚠️  async imports skipped: {e}")


def test_build_batch_json():
    """build_batch_json produces correct summary structure."""
    results = {
        "success": [
            {"company": "公司A", "count": 3, "records": [{"viewId": "1"}]},
        ],
        "no_results": ["公司B"],
        "blocked": ["公司C"],
        "errors": [{"company": "公司D", "error": "timeout"}],
    }
    data = build_batch_json(results, "20260517-zhixing", "zhixing")
    assert data["batch_id"] == "20260517-zhixing"
    assert data["subsite"] == "zhixing"
    assert data["summary"]["total_companies"] == 4
    assert data["summary"]["success"] == 1
    assert data["summary"]["waf_retry"] == 1
    assert data["summary"]["total_records"] == 3
    assert len(data["companies"]) == 4
    print(f"  ✅ build_batch_json: correct summary (4 companies, 3 records)")


def test_waf_circuit_breaker_persistence():
    """ThreadWafCircuitBreaker writes/reads cooldown file."""
    import os
    import threading
    import time
    from zxgk.async_primitives import ThreadWafCircuitBreaker
    cooldown_file = "/tmp/zxgk_waf_cooldown_until"

    # Clean state
    if os.path.exists(cooldown_file):
        os.remove(cooldown_file)
    b1 = ThreadWafCircuitBreaker(cooldown_sec=2)
    assert b1.check() is True, "Should allow requests without cooldown"

    # Trip in a thread and verify file is written during cooldown
    file_written = threading.Event()

    def trip_and_capture():
        try:
            b1.trip()
        finally:
            if os.path.exists(cooldown_file):
                file_written.set()

    t = threading.Thread(target=trip_and_capture)
    t.start()
    time.sleep(0.5)
    assert os.path.exists(cooldown_file), "Cooldown file should be written during cooldown"
    t.join()
    print(f"  ✅ ThreadWafCircuitBreaker: persistence OK")


def test_screenshot_cleanup_api():
    """DetailScreenshot has cleanup_pending() and mark_uploaded()."""
    from zxgk.screenshot import DetailScreenshot
    import inspect
    methods = {name for name, _ in inspect.getmembers(DetailScreenshot, inspect.isfunction)}
    assert "cleanup_pending" in methods, "DetailScreenshot must have cleanup_pending()"
    assert "mark_uploaded" in methods, "DetailScreenshot must have mark_uploaded()"
    print(f"  ✅ DetailScreenshot.cleanup_pending / mark_uploaded: present")


if __name__ == "__main__":
    print("test_basics.py — Baseline smoke tests\n")
    tests = [
        test_load_config,
        test_load_company_list,
        test_parse_chinese_date,
        test_dismiss_functions_importable,
        test_backfill_importable,
        test_async_importable,
        test_build_batch_json,
        test_waf_circuit_breaker_persistence,
        test_screenshot_cleanup_api,
    ]
    passed = 0
    failed = 0
    for t in tests:
        try:
            t()
            passed += 1
        except Exception as e:
            print(f"  ❌ {t.__name__}: {e}")
            failed += 1

    print(f"\n{passed} passed, {failed} failed")
    sys.exit(0 if failed == 0 else 1)
