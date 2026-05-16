#!/usr/bin/env python3
"""Baseline smoke tests — no browser, no captcha server, no Feishu needed.

Run: python3 test_basics.py
"""

import sys
from pathlib import Path

# Ensure project root on sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent))

from zxgk.config import load_config, load_company_list, parse_chinese_date


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


if __name__ == "__main__":
    print("test_basics.py — Baseline smoke tests\n")
    tests = [
        test_load_config,
        test_load_company_list,
        test_parse_chinese_date,
        test_dismiss_functions_importable,
        test_backfill_importable,
        test_async_importable,
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
