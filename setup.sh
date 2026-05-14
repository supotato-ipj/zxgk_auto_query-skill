#!/bin/bash
# setup.sh — 一键安装所有依赖（macOS / Ubuntu 通用）
set -e

DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$DIR"

echo "=========================================="
echo "zxgk-daily-query 安装脚本"
echo "=========================================="
echo ""

# ── 前置检查 ──
OS="$(uname -s)"

for cmd in python3 npm; do
    if ! which "$cmd" > /dev/null 2>&1; then
        if [ "$OS" = "Darwin" ]; then
            echo "❌ 需要 $cmd，请先运行: brew install $cmd"
        else
            echo "❌ 需要 $cmd，请先运行: sudo apt install -y python3 python3-venv python3-pip npm"
        fi
        exit 1
    fi
done

# ── Step 1: Python venv + pip 依赖 ──
echo "[1/5] Python 虚拟环境 ..."
if [ ! -d venv ]; then
    python3 -m venv venv
fi
source venv/bin/activate
pip install -q -U pip
pip install -q playwright==1.58.0 playwright-stealth==2.0.3 PyYAML==6.0.3 requests==2.33.1
echo "  ✅"

# ── Step 2: Playwright Chromium ──
echo "[2/5] Chromium 浏览器（Playwright 内置）..."
playwright install chromium --with-deps
echo "  ✅"

# ── Step 3: lark-cli ──
echo "[3/5] lark-cli ..."
if ! which lark-cli > /dev/null 2>&1; then
    npm install -g @larksuite/cli
fi
echo "  ✅"

# ── Step 4: captcha-solver ──
echo "[4/5] captcha-solver OCR 服务 ..."

# captcha-solver，如果本地没有则跳过安装
CAPTCHA_DIR="$DIR/captcha-solver"
if [ -d "$CAPTCHA_DIR" ]; then
    cd "$CAPTCHA_DIR"
    if [ ! -d venv ]; then
        python3 -m venv venv
    fi
    source venv/bin/activate
    pip install -q -U pip
    pip install -q fastapi uvicorn paddlepaddle paddleocr opencv-python-headless numpy pillow python-multipart
    echo "  captcha-solver ✅"
else
    echo "  ⚠️  captcha-solver 目录未找到，跳过（可稍后手动安装）"
fi
cd "$DIR"

# ── Step 5: lark-cli 认证检查 ──
echo "[5/5] lark-cli 飞书认证检查 ..."
if ! lark-cli api GET '/open-apis/authen/v1/user_info' --as user > /dev/null 2>&1; then
    echo ""
    echo "⚠️  需要人工登录飞书。请按以下步骤操作："
    echo ""
    echo "    1. 运行:  lark-cli auth"
    echo "    2. 浏览器扫码或输入密码登录飞书"
    echo "    3. 登录成功后重新运行:  bash setup.sh"
    echo ""
    exit 1
fi
echo "  ✅"

# ── 环境变量检查 ──
echo ""
if [ -f .env ]; then
    source .env 2>/dev/null || true
    if [ -n "${FEISHU_APP_TOKEN:-}" ]; then
        echo "✅ FEISHU_APP_TOKEN 已设置"
    else
        echo "⚠️  .env 文件存在但 FEISHU_APP_TOKEN 未设置"
    fi
else
    echo "⚠️  未检测到 .env 文件。如需飞书写入，请创建："
    echo "    cp .env.example .env"
    echo "    # 编辑 .env 填入你的 FEISHU_APP_TOKEN"
    echo "    source .env"
fi

echo ""
echo "=========================================="
echo "安装完成 ✅"
echo "=========================================="
echo ""
echo "首次运行："
echo "  1. source .env                # 加载飞书 token"
echo "  2. bash cron_daily_query.sh    # 运行全流程"
