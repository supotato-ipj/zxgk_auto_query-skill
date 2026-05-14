#!/bin/bash
# cron_daily_query.sh — 被执行人/失信/限高 每日查询编排脚本
#
# 由 OpenClaw cron 调用，AI Agent 只需读汇总 JSON 做报告。
# 用法: bash cron_daily_query.sh

set -u  # 未定义变量报错，但不设 -e（允许子任务非零退出）

WORKSPACE="$HOME/.openclaw/workspace-lead/执行信息查询"
COMPANIES="$WORKSPACE/config/companies.txt"
OUTPUT_DIR="$WORKSPACE/output"
DATE=$(date +%Y%m%d)
SUMMARY_FILE="/tmp/zxgk_summary_${DATE}.json"
LOG_FILE="/tmp/zxgk_cron_${DATE}.log"

# 互斥锁：防止两个实例同时运行（mkdir 原子操作，POSIX 跨平台）
LOCK_DIR="/tmp/zxgk_cron.lockdir"
if ! mkdir "$LOCK_DIR" 2>/dev/null; then
    echo "❌ 另一实例正在运行，退出"
    exit 0
fi
trap "rmdir '$LOCK_DIR' 2>/dev/null || true" EXIT

# 每日 sentinel：防止同日重复执行（AI agent 重试场景）
SENTINEL="/tmp/zxgk_daily_${DATE}.sentinel"
if [ -f "$SENTINEL" ]; then
    echo "❌ 今日查询已完成（sentinel 存在），跳过"
    exit 0
fi

cd "$WORKSPACE"
source venv/bin/activate
mkdir -p "$OUTPUT_DIR"

# 清空日志
: > "$LOG_FILE"

echo "=========================================="
echo "每日执行查询 — $(date '+%Y-%m-%d %H:%M:%S')"
echo "=========================================="

# ────────────────────────────────────
# Step 0: 确保 captcha-solver 在跑
# ────────────────────────────────────
echo "[0] captcha-solver ..."
CAPTCHA_DIR="$WORKSPACE/captcha-solver"

if ! curl -s http://localhost:8001/health > /dev/null 2>&1; then
    echo "  captcha-solver 未运行，启动中 ..."

    # 优先 Docker，fallback 到裸机 venv
    if which docker > /dev/null 2>&1 && [ -f "$CAPTCHA_DIR/docker-compose.yml" ]; then
        cd "$CAPTCHA_DIR"
        if ! docker image inspect captcha-solver:latest > /dev/null 2>&1; then
            docker compose build -q 2>/dev/null || true
        fi
        docker compose up -d 2>/dev/null && echo "  Docker 启动中 ..." || true
    fi

    # 等待就绪（最长 90s）
    for i in $(seq 1 90); do
        if curl -s http://localhost:8001/health > /dev/null 2>&1; then
            echo "  captcha-solver ✅ (${i}s)"
            break
        fi
        sleep 1
    done

    # 如果 Docker 没起来，fallback 到裸机
    if ! curl -s http://localhost:8001/health > /dev/null 2>&1; then
        echo "  Docker 未就绪，fallback 到裸机 ..."
        cd "$CAPTCHA_DIR"
        source venv/bin/activate 2>/dev/null || true
        PORT=8001 nohup python3 main.py > /tmp/captcha_solver.log 2>&1 &
        sleep 4
    fi

    cd "$WORKSPACE"
    source venv/bin/activate
fi

if ! curl -s http://localhost:8001/health > /dev/null 2>&1; then
    echo "❌ captcha-solver 不可用，终止"
    exit 3
fi
echo "[0] captcha-solver ✅"

# ────────────────────────────────────
# Pre-flight: lark-cli 认证检查
# ────────────────────────────────────
if ! lark-cli api GET '/open-apis/authen/v1/user_info' --as user > /dev/null 2>&1; then
    echo "⚠️  lark-cli 未认证，跳过飞书写入（可稍后手动补充）"
    echo "  运行 lark-cli auth 登录飞书后重试"
    SKIP_FEISHU=true
else
    SKIP_FEISHU=false
fi

# ────────────────────────────────────────────────────────
# 子站查询函数（独立执行，失败不中断后续任务）
# ────────────────────────────────────────────────────────
run_subsite() {
    local subsite="$1"
    local label="$2"
    local json_path="$3"
    local cross_ref="$4"  # "--cross-ref" or ""

    echo ""
    echo "--- ${label} (${subsite}) ---"

    # 启动前清理残留 Chromium（兜底 Python 层清理不了的情况）
    pkill -f "chromium-browser.*playwright" 2>/dev/null || true
    sleep 2

    # 执行 CLI，日志同时输出到终端和文件
    python3 zxgk_query.py \
        --batch "$COMPANIES" \
        --subsite "$subsite" \
        --mode text-only \
        --output "$json_path" \
        2>&1 | tee -a "$LOG_FILE"
    local exit_code=${PIPESTATUS[0]}

    if [ -f "$json_path" ]; then
        local records=$(python3 -c "import json; print(json.load(open('$json_path'))['summary']['total_records'])" 2>/dev/null || echo 0)
        if [ "$records" -gt 0 ] 2>/dev/null; then
            # 始终写入 SQLite（本地备份，零依赖）
            echo "[${label}] 写入 SQLite (${records} 条) ..."
            python3 -m writers.sqlite --input "$json_path" --db "$OUTPUT_DIR/zxgk_results.db" 2>&1 | tee -a "$LOG_FILE" || true

            # 飞书已认证时同步写入多维表格
            if [ "$SKIP_FEISHU" = false ]; then
                echo "[${label}] 写入飞书 (${records} 条) ..."
                python3 -m writers.feishu --input "$json_path" --subsite "$subsite" $cross_ref \
                    --screenshots "$OUTPUT_DIR/screenshots" 2>&1 | tee -a "$LOG_FILE" || true
            fi
        else
            echo "[${label}] 无记录，跳过写入"
        fi
        echo "[${label}] ✅"
    else
        echo "[${label}] ⚠️  JSON 未生成 (exit=$exit_code)，可能无匹配记录或查询失败"
    fi
}

# ────────────────────────────────────
# Step 1-3: 三子站查询
# ────────────────────────────────────
run_subsite "zhixing" "被执行人"    "$OUTPUT_DIR/zxgk_batch_${DATE}_zhixing.json" ""
run_subsite "shixin"  "失信被执行人" "$OUTPUT_DIR/zxgk_batch_${DATE}_shixin.json"  "--cross-ref"
run_subsite "xgl"     "限制消费人员" "$OUTPUT_DIR/zxgk_batch_${DATE}_xgl.json"     "--cross-ref"

# ────────────────────────────────────
# Step 4: 生成汇总 JSON 供 AI 读取
# ────────────────────────────────────
echo ""
echo "[4] 生成汇总 ..."

python3 -c "
import json, os, sys
from datetime import datetime

summary = {
    'date': '${DATE}',
    'generated_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
    'subsites': {}
}

for key, path, name in [
    ('zhixing', '${OUTPUT_DIR}/zxgk_batch_${DATE}_zhixing.json', '被执行人'),
    ('shixin',  '${OUTPUT_DIR}/zxgk_batch_${DATE}_shixin.json', '失信被执行人'),
    ('xgl',     '${OUTPUT_DIR}/zxgk_batch_${DATE}_xgl.json', '限制消费人员'),
]:
    if os.path.exists(path):
        with open(path) as f:
            data = json.load(f)
        companies = []
        for c in data.get('companies', []):
            companies.append({
                'company': c['company'],
                'status': c.get('status', '?'),
                'total': c.get('total', 0),
            })
        summary['subsites'][key] = {
            'name': name,
            'companies': companies,
            'total_records': data.get('summary', {}).get('total_records', 0),
            'total_companies': len(companies),
        }
    else:
        summary['subsites'][key] = {
            'name': name,
            'status': 'no_data',
            'note': 'JSON 未生成，可能无匹配记录或查询失败',
        }

with open('${SUMMARY_FILE}', 'w') as f:
    json.dump(summary, f, ensure_ascii=False, indent=2)
print(f'汇总已保存: ${SUMMARY_FILE}')
"

# ────────────────────────────────────
# Step 5: Phase B — 截图回填（仅在飞书启用时执行）
# ────────────────────────────────────
if [ "$SKIP_FEISHU" = false ]; then
    echo ""
    echo "[5] 等待飞书计算完成 (30s) ..."
    sleep 30

    echo "[5] Phase B 截图回填 ..."
    python3 -c "
import sys; sys.path.insert(0, '$WORKSPACE')
from zxgk_query import ScreenshotBackfiller, load_config
config = load_config()
backfiller = ScreenshotBackfiller(config, batch_id='${DATE}-zhixing')
backfiller.run()
" 2>&1 | tee -a "$LOG_FILE" || true
fi

# 标记今日完成（sentinel 防止同日重跑）
touch "$SENTINEL"

# 清理旧文件：progress (7d), 单公司JSON (7d), 单次汇总 (7d), batch JSON (30d), 截图 (30d)
find "$OUTPUT_DIR" -name ".progress_*" -mtime +7 -delete 2>/dev/null || true
find "$OUTPUT_DIR" -name "query_*.json" -mtime +7 -delete 2>/dev/null || true
find "$OUTPUT_DIR" -name "summary_*.json" -mtime +7 -delete 2>/dev/null || true
find "$OUTPUT_DIR" -maxdepth 1 -name "zxgk_batch_*.json" -mtime +30 -delete 2>/dev/null || true
find "$OUTPUT_DIR/screenshots" -name "*.png" -mtime +30 -delete 2>/dev/null || true

echo ""
echo "=========================================="
echo "查询完成 — $(date '+%Y-%m-%d %H:%M:%S')"
echo "汇总文件: $SUMMARY_FILE"
echo "详细日志: $LOG_FILE"
echo "=========================================="
