#!/bin/bash
# smoke_test.sh — 执行信息查询系统冒烟测试
# 用法: bash smoke_test.sh

set -u
WORKSPACE="$(cd "$(dirname "$0")" && pwd)"
FAIL=0

green() { echo -e "\033[32m$1\033[0m"; }
red()   { echo -e "\033[31m$1\033[0m"; }

echo "=========================================="
echo "执行信息查询 — 冒烟测试"
echo "=========================================="

# ── 1. Python 语法检查 ──
echo ""
echo "[1] Python 语法检查"
for py in zxgk_query.py writers/feishu.py diagnose_subsites.py; do
    if python3 -c "import py_compile; py_compile.compile('$py', doraise=True)" 2>/dev/null; then
        green "  $py ✅"
    else
        red "  $py ❌"
        FAIL=1
    fi
done

# ── 2. Shell 语法检查 ──
echo ""
echo "[2] Shell 语法检查"
for sh in cron_daily_query.sh smoke_test.sh; do
    if bash -n "$sh" 2>/dev/null; then
        green "  $sh ✅"
    else
        red "  $sh ❌"
        FAIL=1
    fi
done

# ── 3. 配置文件 YAML 格式验证 ──
echo ""
echo "[3] 配置文件验证"
CONFIG="$WORKSPACE/config/zxgk.yaml"
if python3 -c "
import yaml, sys
with open('$CONFIG') as f:
    data = yaml.safe_load(f)
print(f'  sections: {list(data.keys())}')
subsites = data.get('subsites', {})
print(f'  subsites: {list(subsites.keys())}')
for k, v in subsites.items():
    print(f'    {k}: extra_wait={v.get(\"extra_wait_sec\", \"?\")}')
companies = data.get('companies', [])
print(f'  companies: {len(companies)} 家')
" 2>/dev/null; then
    green "  $CONFIG ✅"
else
    red "  $CONFIG ❌ (YAML 解析失败)"
    FAIL=1
fi

# ── 4. 公司列表检查 ──
echo ""
echo "[4] 公司列表"
COMPANIES="$WORKSPACE/config/companies.txt"
if [ -f "$COMPANIES" ]; then
    count=$(grep -c . "$COMPANIES" 2>/dev/null || echo 0)
    green "  companies.txt: ${count} 家 ✅"
else
    red "  companies.txt 缺失 ❌"
    FAIL=1
fi

# 确认 companies.yaml 已删除
if [ -f "$WORKSPACE/config/companies.yaml" ]; then
    red "  companies.yaml 仍存在（应为单一 companies.txt） ⚠️"
fi

# ── 5. 环境变量检查 ──
echo ""
echo "[5] 环境变量"
if [ -n "${FEISHU_APP_TOKEN:-}" ]; then
    green "  FEISHU_APP_TOKEN: 已设置 ✅"
else
    red "  FEISHU_APP_TOKEN: 未设置 ❌"
    FAIL=1
fi

# ── 6. venv 检查 ──
echo ""
echo "[6] venv 依赖"
VENV="$WORKSPACE/venv"
if [ -d "$VENV" ]; then
    green "  venv: 存在 ✅"
    if "$VENV/bin/python" -c "import playwright, yaml, requests" 2>/dev/null; then
        green "  依赖 (playwright, yaml, requests): ✅"
    else
        red "  依赖缺失 ❌"
        FAIL=1
    fi
else
    red "  venv 目录不存在 ❌"
    FAIL=1
fi

# ── 7. captcha-solver 健康检查 ──
echo ""
echo "[7] captcha-solver"
if curl -s http://localhost:8001/health > /dev/null 2>&1; then
    green "  http://localhost:8001/health ✅"
else
    echo "  ⚠️  captcha-solver 未运行（cron 会自动启动）"
fi

# ── 8. Batch JSON 格式验证 ──
echo ""
echo "[8] Batch JSON 格式"
LATEST_BATCH=$(ls -t "$WORKSPACE/output"/zxgk_batch_*.json 2>/dev/null | head -1)
if [ -n "$LATEST_BATCH" ]; then
    if python3 -c "
import json, sys
with open('$LATEST_BATCH') as f:
    data = json.load(f)
assert 'companies' in data, 'missing: companies'
assert 'summary' in data, 'missing: summary'
for c in data['companies']:
    assert 'company' in c, 'missing company name'
    assert 'status' in c, 'missing status'
    assert 'records' in c, 'missing records'
    for r in c['records']:
        assert 'caseNo' in r, 'missing caseNo'
        assert 'viewId' in r, 'missing viewId'
        assert 'timestamp' in r, 'missing timestamp'
print(f'  {len(data[\"companies\"])} companies, {data[\"summary\"][\"total_records\"]} records: valid')
" 2>/dev/null; then
        green "  $(basename "$LATEST_BATCH") ✅"
    else
        red "  $(basename "$LATEST_BATCH") ❌ (格式异常)"
        FAIL=1
    fi
else
    echo "  (无 batch JSON 文件，跳过)"
fi

# ── 结果 ──
echo ""
echo "=========================================="
if [ "$FAIL" -eq 0 ]; then
    green "冒烟测试全部通过 ✅"
else
    red "冒烟测试存在失败 ❌"
fi
echo "=========================================="
exit $FAIL
