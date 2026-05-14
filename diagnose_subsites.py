#!/usr/bin/env python3
"""Diagnostic: probe DOM structure of all three subsites (zhixing/shixin/xgl).

Usage: python3 diagnose_subsites.py
Requires: captcha-solver on port 8001
"""

import json
import logging
import os
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import yaml

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("diagnose")

SCRIPT_DIR = Path(__file__).resolve().parent

def load_subsites():
    """从 config/zxgk.yaml 加载子站配置"""
    config_path = SCRIPT_DIR / "config" / "zxgk.yaml"
    if config_path.exists():
        with open(config_path) as f:
            raw = yaml.safe_load(f) or {}
        yaml_subsites = raw.get("subsites", {})
        subsites = {}
        for key, info in yaml_subsites.items():
            subsites[key] = {
                "name": info.get("name", key),
                "css": info.get("css_selector", ""),
                "extra_wait": info.get("extra_wait_sec", 5),
            }
        if subsites:
            return subsites
    # fallback
    return {
        "zhixing": {"name": "被执行人", "css": "div.bzxrxx_nor", "extra_wait": 5},
        "shixin":  {"name": "失信被执行人", "css": "div.sxbzxr_nor",  "extra_wait": 5},
        "xgl":     {"name": "限制消费人员", "css": "div.xzxfry_nor",  "extra_wait": 5},
    }

SUBSITES = load_subsites()

BROWSER_ARGS = [
    "--no-sandbox", "--disable-setuid-sandbox", "--disable-dev-shm-usage",
    "--disable-blink-features=AutomationControlled",
    "--disable-features=IsolateOrigins,site-per-process",
    "--disable-web-security",
]

def _cleanup_orphans():
    """清理所有 Playwright 启动的 Chromium 进程（含子进程）"""
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

def _dismiss_overlay(page):
    """在弹窗容器内查找并点击 确定/关闭 按钮"""
    page.evaluate("""
    () => {
        const dialogs = document.querySelectorAll(
            '.dialog, .modal, .popup, [role="dialog"], [role="alertdialog"], '
            + '.layui-layer-dialog, .layui-layer, .ui-dialog'
        );
        const containers = dialogs.length > 0 ? Array.from(dialogs) : [document.body];
        for (const d of containers) {
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

def _dismiss_dialogs(page, max_iterations=8):
    """轮询关闭页面上可能出现的弹窗"""
    for _ in range(max_iterations):
        _dismiss_overlay(page)
        time.sleep(0.5)


def probe_subsite(page, name, info):
    """Navigate to a subsite and probe its DOM structure."""
    logger.info("=== 导航到: %s ===", name)

    page.goto("http://zxgk.court.gov.cn", wait_until="networkidle", timeout=30000)
    page.wait_for_timeout(2000)

    # Click subsite
    css = info["css"]
    ok = page.evaluate(f"""
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
        return {"error": f"subsite link not found: {css}"}

    page.wait_for_load_state("networkidle", timeout=30000)
    extra = info["extra_wait"]
    if extra:
        page.wait_for_timeout(extra * 1000)

    result = {}

    # 1. Check WAF elements
    result["has_yzm"] = page.evaluate("() => !!document.getElementById('yzm')")
    result["has_pName"] = page.evaluate("() => !!document.getElementById('pName')")
    result["has_captchaId"] = page.evaluate("() => !!document.getElementById('captchaId')")

    # 2. Check extra form fields
    result["has_pProvince"] = page.evaluate("() => !!document.getElementById('pProvince')")
    if result["has_pProvince"]:
        result["pProvince_options"] = page.evaluate("""
        () => {
            const sel = document.getElementById('pProvince');
            if (!sel) return [];
            return Array.from(sel.options).map(o => ({
                value: o.value, text: o.textContent?.trim()
            }));
        }
        """)
        result["pProvince_selected"] = page.evaluate(
            "() => document.getElementById('pProvince')?.value"
        )

    # 3. Check table structure
    result["tables"] = page.evaluate("""
    () => {
        const tables = [];
        const ids = ['tb-1', 'tb-2', 'result-table', 'tbody-result'];
        for (const id of ids) {
            const el = document.getElementById(id);
            tables.push({
                id: id,
                exists: !!el,
                tagName: el?.tagName || null,
                rowCount: el?.tagName === 'TBODY' ? el.querySelectorAll('tr').length
                        : el?.querySelectorAll('tr').length || 0,
            });
        }
        // Column count and header text from first data row
        const rows = document.querySelectorAll('#tbody-result tr');
        if (rows.length > 0) {
            const tds = rows[0].querySelectorAll('td');
            tables.push({
                id: '_column_info',
                colCount: tds.length,
                headers: Array.from(tds).map((td, i) =>
                    `${i}: "${td.innerText?.trim().substring(0, 40)}"`
                ),
            });
        }
        return tables;
    }
    """)

    # 4. Check #result-block
    result["result_block"] = page.evaluate("""
    () => {
        const rb = document.getElementById('result-block');
        if (!rb) return {exists: false};
        return {
            exists: true,
            visible: rb.offsetParent !== null,
            innerText: (rb.innerText || '').substring(0, 500),
        };
    }
    """)

    # 5. Check pagination
    result["pagination"] = page.evaluate("""
    () => {
        const btn = document.getElementById('next-btn');
        return {
            next_btn_exists: !!btn,
            next_btn_tag: btn?.tagName || null,
            next_btn_disabled: btn?.disabled || false,
            next_btn_visible: btn?.offsetParent !== null || false,
        };
    }
    """)

    # 6. Check search button onclick
    result["search_onclick"] = page.evaluate("""
    () => {
        const btns = document.querySelectorAll('button, input[type="button"], a');
        for (const b of btns) {
            const oc = b.getAttribute('onclick') || '';
            if (oc.includes('search()')) {
                return oc;
            }
        }
        return '(not found)';
    }
    """)

    # 7. Try to find a test record — enter keyword "张" (common surname)
    page.fill("#pName", "张")

    # Get captcha
    cap_b64 = page.evaluate("""
    () => {
        const y = document.getElementById('yzm');
        if (!y) return null;
        const p = y.closest('.form-group') || y.parentElement.parentElement;
        for (const i of p.querySelectorAll('img')) {
            const w = i.naturalWidth || i.width;
            const h = i.naturalHeight || i.height;
            if (w > 20 && w < 300 && h > 10 && h < 100) {
                const c = document.createElement('canvas');
                c.width = w; c.height = h;
                c.getContext('2d').drawImage(i, 0, 0);
                return c.toDataURL('image/png');
            }
        }
        return null;
    }
    """)

    if not cap_b64:
        result["query_test"] = {"error": "could not extract captcha"}
        return result

    import requests
    raw = cap_b64.split(",", 1)[1] if cap_b64.startswith("data:") else cap_b64
    r = requests.post("http://localhost:8001/solve/base64",
                      json={"image": raw, "preprocess": "gray"}, timeout=10)
    ocr = r.json()
    text = ocr.get("text", "")
    logger.info("OCR result: '%s' conf=%.3f", text, ocr.get("confidence", 0))

    if not text or not text.strip():
        result["query_test"] = {"error": f"OCR empty: {ocr}"}
        return result

    page.fill("#yzm", text)

    # Submit
    try:
        page.evaluate("initCurrentPage()")
    except Exception:
        pass
    try:
        page.evaluate("search()")
    except Exception as e:
        result["query_test"] = {"error": f"search() failed: {e}"}
        return result

    # 等待并关闭弹窗
    _dismiss_dialogs(page)
    try:
        page.wait_for_load_state("networkidle", timeout=15000)
    except Exception:
        pass

    # Collect result
    result["query_test"] = page.evaluate("""
    () => {
        const rb = document.getElementById('result-block');
        const result_text = rb?.innerText || '';
        const no_result = result_text.includes('没有找到');
        const captcha_err = result_text.includes('验证码错误') || result_text.includes('验证码已过期');

        // Collect first 3 rows
        const rows = document.querySelectorAll('#tbody-result tr');
        const samples = [];
        for (let i = 0; i < Math.min(3, rows.length); i++) {
            const tds = rows[i].querySelectorAll('td');
            samples.push(Array.from(tds).map((td, j) =>
                `${j}: "${td.innerText?.trim().substring(0, 50)}"`
            ));
        }

        // Check showDetail link
        const first_link = document.querySelector('a[onclick*="showDetail"]');
        const onclick = first_link?.getAttribute('onclick') || '';

        return {
            result_text: result_text.substring(0, 300),
            no_result: no_result,
            captcha_error: captcha_err,
            row_count: rows.length,
            col_count: rows.length > 0 ? rows[0].querySelectorAll('td').length : 0,
            samples: samples,
            showDetail_onclick: onclick,
        };
    }
    """)

    # Check pagination after query
    result["pagination_after_query"] = page.evaluate("""
    () => {
        const btn = document.getElementById('next-btn');
        return {
            next_btn_exists: !!btn,
            next_btn_disabled: btn?.disabled || false,
            next_btn_visible: btn?.offsetParent !== null || false,
        };
    }
    """)

    return result


def main():
    for k in ["HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy",
              "ALL_PROXY", "all_proxy"]:
        os.environ.pop(k, None)

    # 清理残留 Chromium 进程
    _cleanup_orphans()

    all_results = {}
    pw = sync_playwright().start()
    browser = pw.chromium.launch(
        executable_path="/usr/bin/chromium-browser",
        headless=True,
        args=BROWSER_ARGS,
    )
    context = browser.new_context(
        viewport={"width": 1920, "height": 1080},
        locale="zh-CN",
    )
    page = context.new_page()
    Stealth(
        navigator_platform_override="Linux x86_64",
        navigator_languages_override=("zh-CN", "zh", "en-US", "en"),
        navigator_vendor_override="Google Inc.",
        webgl_vendor_override="Intel Inc.",
        webgl_renderer_override="Intel Iris OpenGL Engine",
    ).apply_stealth_sync(page)

    for key, info in SUBSITES.items():
        try:
            logger.info("\n\n========== %s ==========", key)
            result = probe_subsite(page, key, info)
            all_results[key] = result
            # Print key findings immediately
            qt = result.get("query_test", {})
            logger.info("结果: rows=%d, cols=%d, no_result=%s, captcha_err=%s",
                        qt.get("row_count", 0), qt.get("col_count", 0),
                        qt.get("no_result"), qt.get("captcha_error"))
            if qt.get("samples"):
                logger.info("第1行列: %s", qt["samples"][0])
            if qt.get("showDetail_onclick"):
                logger.info("showDetail onclick: %s", qt["showDetail_onclick"])
            tables = result.get("tables", [])
            for t in tables:
                if t.get("id") == "_column_info":
                    logger.info("默认列: %s", t.get("headers"))
            for t in tables:
                if t["id"] in ("tb-1", "tb-2") and t["exists"]:
                    logger.info("%s: exists=True, rows=%d", t["id"], t["rowCount"])
        except Exception as e:
            logger.error("%s 诊断异常: %s", key, e, exc_info=True)
            all_results[key] = {"error": str(e)}

        # 跨子站清理弹窗，等待页面稳定
        _dismiss_dialogs(page)
        time.sleep(2)

    browser.close()
    pw.stop()

    # 清理残留
    _cleanup_orphans()

    # Save full results
    out_path = os.path.join(os.path.dirname(__file__), "diagnose_results.json")
    with open(out_path, "w") as f:
        json.dump(all_results, f, ensure_ascii=False, indent=2)
    logger.info("\n完整结果已保存: %s", out_path)

    # Print summary
    print("\n" + "=" * 60)
    print("诊断摘要")
    print("=" * 60)
    for key, r in all_results.items():
        qt = r.get("query_test", {})
        print(f"\n--- {key} ---")
        print(f"  WAF: yzm={r.get('has_yzm')} pName={r.get('has_pName')}")
        print(f"  pProvince: {r.get('has_pProvince')} "
              f"(selected={r.get('pProvince_selected')})")
        print(f"  columns: {qt.get('col_count', '?')}")
        if qt.get("samples"):
            print(f"  row1: {qt['samples'][0]}")
        print(f"  no_result={qt.get('no_result')} "
              f"captcha_err={qt.get('captcha_error')}")
        print(f"  search_onclick: {r.get('search_onclick', '?')}")
        pag = r.get("pagination_after_query", {})
        print(f"  pagination: next_btn={pag.get('next_btn_exists')} "
              f"disabled={pag.get('next_btn_disabled')}")
        tables = r.get("tables", [])
        for t in tables:
            if t["id"] in ("tb-1", "tb-2") and t["exists"]:
                print(f"  {t['id']}: rows={t['rowCount']}")


if __name__ == "__main__":
    main()
