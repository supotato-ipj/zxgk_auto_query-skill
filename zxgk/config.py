"""zxgk 配置加载与工具函数"""
import logging
import os
import re
import sys
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
    """加载 YAML 配置，返回 dict"""
    if path is None:
        path = SCRIPT_DIR / "config" / "zxgk.yaml"
    config_path = Path(path)
    if not config_path.exists():
        logger.warning("配置文件不存在 %s，使用默认值", config_path)
        return {}
    with open(config_path) as f:
        raw = yaml.safe_load(f) or {}

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
    return _resolve_env(raw)


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
