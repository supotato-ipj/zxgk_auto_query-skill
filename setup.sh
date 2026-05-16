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
python3 -m venv --help > /dev/null 2>&1 || {
    echo "⚠️  python3-venv 未安装，请先运行："
    echo "  Ubuntu: sudo apt install python3-venv python3-pip"
    exit 1
}
if [ ! -d venv ]; then
    python3 -m venv venv
fi
source venv/bin/activate
pip install -q -U pip
pip install -q --default-timeout=120 -r requirements.txt
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
echo "[4/5] captcha-solver OCR 验证码识别服务 ..."
echo ""

CAPTCHA_DIR="$DIR/captcha-solver"
if [ -d "$CAPTCHA_DIR" ]; then
    echo "本地 OCR 模型（PaddleOCR，约 1.5GB）安装选项："
    echo "  [1] 安装推荐的 PaddleOCR（pip install paddlepaddle paddleocr）"
    echo "  [2] 跳过 — 稍后自行部署（Docker 或裸机 venv）"
    echo "  [3] 跳过 — 已有可用的 captcha-solver 在 localhost:8001"
    echo ""
    printf "请选择 [1/2/3]（默认 2）："
    read -r OCR_CHOICE </dev/tty || OCR_CHOICE="2"
    OCR_CHOICE="${OCR_CHOICE:-2}"
    echo ""

    case "$OCR_CHOICE" in
        1)
            echo "  安装 PaddleOCR（首次下载约 1.5GB，请耐心等待）..."
            cd "$CAPTCHA_DIR"
            if [ ! -d venv ]; then
                python3 -m venv venv
            fi
            source venv/bin/activate
            pip install -q -U pip
            pip install -q --default-timeout=120 fastapi uvicorn paddlepaddle paddleocr opencv-python-headless numpy pillow python-multipart
            if python3 -c "from paddleocr import PaddleOCR; print('paddleocr OK')" 2>/dev/null; then
                echo "  captcha-solver ✅"
            else
                echo "  ⚠️  paddleocr 导入失败，OCR 识别可能无法正常工作"
                echo "  手动验证: cd captcha-solver && source venv/bin/activate && python3 -c 'from paddleocr import PaddleOCR'"
            fi
            cd "$DIR"
            ;;
        2)
            echo "  ℹ️  已跳过 OCR 安装。稍后可自行部署："
            echo "    Docker:  cd captcha-solver && docker compose up -d"
            echo "    裸机:    cd captcha-solver && source venv/bin/activate && PORT=8001 python main.py"
            echo ""
            echo "  请确保 localhost:8001 提供以下端点："
            echo "    GET  /health  → {\"status\":\"healthy\"}"
            echo "    POST /solve   → {\"success\":true,\"text\":\"xxxx\"}"
            echo "  captcha-solver ⏭️"
            ;;
        3)
            echo "  ℹ️  已跳过 OCR 安装，假定已有服务运行在 localhost:8001"
            echo "  captcha-solver ⏭️（使用已有服务）"
            ;;
        *)
            echo "  ⚠️  无效选项，跳过安装（默认行为）"
            echo "  captcha-solver ⏭️"
            ;;
    esac
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
