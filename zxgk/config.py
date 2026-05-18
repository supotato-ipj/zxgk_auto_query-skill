"""zxgk 配置加载与工具函数"""
import logging
import os
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

import yaml

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("zxgk_query")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
BROWSER_ARGS = [
    "--no-sandbox",
    "--disable-setuid-sandbox",
    "--disable-dev-shm-usage",
    "--disable-blink-features=AutomationControlled",
    "--disable-features=IsolateOrigins,site-per-process",
    "--disable-web-security",
]

PROXY_VARS = [
    "HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy",
    "ALL_PROXY", "all_proxy",
]

SCRIPT_DIR = Path(__file__).resolve().parent.parent

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def clean_env():
    """清理代理环境变量"""
    for k in PROXY_VARS:
        os.environ.pop(k, None)


def load_config(path=None):
    """加载 YAML 配置，返回 dict。校验必需字段。"""
    if path is None:
        path = SCRIPT_DIR / "config" / "zxgk.yaml"
    config_path = Path(path)
    if not config_path.exists():
        logger.warning("配置文件不存在 %s，使用默认值", config_path)
        return {}
    with open(config_path) as f:
        raw = yaml.safe_load(f) or {}

    if not raw:
        logger.warning("配置文件为空 %s", config_path)
        return {}

    # 展开环境变量引用 ${VAR_NAME}
    def _resolve_env(value):
        if isinstance(value, str) and value.startswith("${") and value.endswith("}"):
            env_var = value[2:-1]
            return os.environ.get(env_var, "")
        if isinstance(value, dict):
            return {k: _resolve_env(v) for k, v in value.items()}
        if isinstance(value, list):
            return [_resolve_env(v) for v in value]
        return value

    config = _resolve_env(raw)
    _validate_config(config, config_path)
    return config


def _validate_config(config, config_path):
    """校验关键配置字段，输出 warning 但不中断。"""
    subsites = config.get("subsites", {})
    if not subsites:
        logger.warning("配置缺少 subsites 定义（%s），查询可能失败", config_path)
    else:
        for key in ("zhixing", "shixin", "xgl"):
            if key not in subsites:
                logger.warning("配置缺少子站定义: %s（%s）", key, config_path)

    browser = config.get("browser", {})
    headless = browser.get("headless")
    if headless is not None and not isinstance(headless, bool):
        logger.warning("browser.headless 应为 bool，实际: %s，已忽略", type(headless).__name__)

    captcha = config.get("captcha_server", "")
    if captcha and "://" not in captcha:
        logger.warning("captcha_server 格式异常（缺少协议）: %s", captcha)

    waf = config.get("waf", {})
    if not isinstance(waf.get("company_interval_sec"), (int, float)):
        logger.warning("waf.company_interval_sec 应为数值类型")


def load_company_list(path):
    """加载公司列表（YAML 或纯文本，每行一个公司名）"""
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"公司列表文件不存在: {path}")
    if p.suffix in (".yaml", ".yml"):
        with open(p) as f:
            data = yaml.safe_load(f)
        if isinstance(data, list):
            return [item if isinstance(item, str) else item.get("name", str(item)) for item in data]
        raise ValueError("YAML 格式错误：应为公司名列表")
    else:
        # 纯文本：每行 公司名
        with open(p) as f:
            return [line.strip() for line in f if line.strip() and not line.startswith("#")]


def parse_chinese_date(text: str) -> int:
    """2026年03月26日 → 1742947200000 (Asia/Shanghai milliseconds)"""
    from zoneinfo import ZoneInfo
    m = re.match(r'(\d{4})年(\d{1,2})月(\d{1,2})日', text)
    if not m:
        return 0
    y, mth, d = int(m[1]), int(m[2]), int(m[3])
    tz = ZoneInfo("Asia/Shanghai")
    dt = datetime(y, mth, d, tzinfo=tz)
    return int(dt.timestamp() * 1000)


def setup_environment():
    clean_env()


# ---------------------------------------------------------------------------
# Shared batch utilities — used by both BatchRunner and AsyncBatchRunner
# ---------------------------------------------------------------------------

def build_batch_json(results, batch_id, subsite):
    """构建合并 batch JSON 结构（供两个 Runner 共用）。"""
    tz = timezone(timedelta(hours=8))
    now = datetime.now(tz).isoformat()

    companies = []
    for c in results.get("success", []):
        companies.append({
            "company": c["company"],
            "status": "ok",
            "total": c["count"],
            "records": c["records"],
        })
    for c in results.get("no_results", []):
        companies.append({
            "company": c if isinstance(c, str) else c["company"],
            "status": "no_results",
            "total": 0,
            "records": [],
        })
    for c in results.get("blocked", []):
        companies.append({
            "company": c if isinstance(c, str) else c,
            "status": "waf_blocked",
            "error": "WAF 封禁",
            "total": 0,
            "records": [],
        })
    for c in results.get("errors", []):
        companies.append({
            "company": c["company"],
            "status": "error",
            "error": c.get("error", "未知错误"),
            "total": 0,
            "records": [],
        })

    total_records = sum(c["total"] for c in companies)
    return {
        "batch_id": batch_id,
        "subsite": subsite,
        "query_time": now,
        "companies": companies,
        "summary": {
            "total_companies": len(companies),
            "success": len(results.get("success", [])),
            "waf_retry": len(results.get("blocked", [])),
            "total_records": total_records,
        },
    }


def save_batch_results(results, batch_id, subsite, output_path):
    """Save batch JSON to output_path (shared)."""
    data = build_batch_json(results, batch_id, subsite)
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w") as f:
        import json
        json.dump(data, f, ensure_ascii=False, indent=2)
    total = data["summary"]["total_companies"]
    recs = data["summary"]["total_records"]
    logger.info("[%s] 合并 JSON 已保存: %s (%d 家公司, %d 条记录)",
                subsite, output_path, total, recs)
