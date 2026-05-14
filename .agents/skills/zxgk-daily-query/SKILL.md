---
name: zxgk-daily-query
description: 每日执行信息查询全流程 — Phase A 文本查询+SQLite/飞书写入 → Phase B 截图回填。固化执行步骤，禁止捷径。
---

# 执行信息查询 — 每日全流程

> 自动化查询三子站，结果写入本地 SQLite（无需飞书）+ 可选飞书多维表格，回填缺失截图。
> 脚本位置：当前目录。所有命令默认已 `cd` 到此目录。

## 前置条件：获取项目文件

如果项目目录尚未存在，先获取代码：

```bash
# 从 GitHub 克隆（开源版）
git clone https://github.com/yourname/zxgk-daily-query.git
cd zxgk-daily-query

# 或：解压分享的 zip
# unzip zxgk-daily-query.zip && cd zxgk-daily-query
```

所有后续命令默认已 `cd` 到此目录。

---

## 首次使用（一次性）

```bash
# 0. 获取项目（如果尚未克隆）
# git clone https://github.com/yourname/zxgk-daily-query.git
# cd zxgk-daily-query

# 1. 安装依赖
bash setup.sh

# 2. （可选）配置飞书 token，不配则仅用 SQLite 本地储存
cp .env.example .env
# 编辑 .env 填入你的 FEISHU_APP_TOKEN（跳过则默认存 SQLite）
source .env

# 3. 验证环境
bash smoke_test.sh
```

> setup.sh 会询问是否安装本地 OCR 模型（PaddleOCR ~1.5GB），可选择跳过用自己的方案。也会提示 `lark-cli auth` 登录飞书。

---

## 核心原则

**按脚本执行，不自由裁量。** 流程中的每一步都是强制性的，不可跳过、不可优化、不可"因为看起来没数据所以不做"。

---

## 强制流程

### Phase A：文本查询 + 写入储存

```bash
cd "$(dirname "$0")" && source venv/bin/activate && bash cron_daily_query.sh
```

此脚本自动完成：
1. 启动 captcha-solver（如未运行）
2. zhixing 子站批量查询 → 输出 batch JSON → **SQLite 本地备份（始终）** → 飞书写入 + 上传截图（仅当 lark-cli 已认证时）
3. shixin 子站批量查询 → 同上 + --cross-ref 更新案件主表「是否失信」
4. xgl 子站批量查询 → 同上 + --cross-ref 更新案件主表「是否限高」
5. **Phase B 截图回填**（仅飞书启用时；自动检查案件主表 empty(截图) 并补全）
6. 生成汇总 JSON → `/tmp/zxgk_summary_{date}.json`

### 验证 Phase A 结果

```bash
cat /tmp/zxgk_summary_$(date +%Y%m%d).json
```

检查各子站的 `total_records` 和 `status`。zhixing 应 5/5 ok。

### Phase B：截图回填（已在 cron 中自动执行）

Phase B 已集成到 `cron_daily_query.sh` Step 5。如需手动执行：

```bash
source venv/bin/activate && python3 -c "
from zxgk_query import ScreenshotBackfiller, load_config
bf = ScreenshotBackfiller(load_config(), '$(date +%Y%m%d)-zhixing')
bf.run()
"
```

Phase B 内部流程（由 ScreenshotBackfiller 自动完成）：
1. 查案件主表 `filter: {"截图": "isEmpty"}` → 得到缺截图记录
2. 每条记录通过 raw 表「案件主表」DuplexLink 反向查找 → 取真实 viewId
3. 按公司分组，浏览器搜索 → showDetail(viewId) → 截图 → 上传飞书

---

## 严禁行为

以下操作一律禁止，无论理由多么合理：

### ❌ 跳过 Phase B
- **错误示范**："今天没有新记录所以不用截图"
- **正确做法**：必须查询案件主表 `empty(截图)`，有则补，无则跳过。不能凭感觉判断。

### ❌ 按案号推测 viewId
- **错误示范**：从 batch JSON 按案号匹配，取第一个 viewId
- **正确做法**：必须走 `案件主表 → raw_一级 DuplexLink → 查一级表 record → 解析「查看」字段` 获取真实 viewId
- **原因**：同名案号可能对应多条 raw 记录，viewId 不同（如 6085074 vs 6085075）

### ❌ 合并同名案号的截图
- **错误示范**："4 条记录共享 3 个 viewId，只截 3 张"
- **正确做法**：每条 case_record 独立处理。即使 viewId 相同也要逐条截图上传。

### ❌ 用 batch JSON 替代飞书 API 查询
- **错误示范**：从 batch JSON 取数据推测 viewId / caseNo
- **正确做法**：所有数据以飞书 API 查询结果为准。batch JSON 仅供 Phase A 写入使用。

### ❌ 跳过 captcha-solver 健康检查
- **错误示范**：假设 captcha-solver 在运行就直接查
- **正确做法**：`curl -s http://localhost:8001/health` 确认可用

---

## 故障处理

### 查询中断（SIGKILL / Browser Crash）

```bash
# 重新运行 cron 脚本（sentinel 会阻止同日重复，需先删除 sentinel）
rm -f /tmp/zxgk_daily_$(date +%Y%m%d).sentinel
bash cron_daily_query.sh
```

### Phase B 失败

Phase B 可独立重跑，不影响 Phase A 数据：
```bash
source venv/bin/activate && python3 -c "
from zxgk_query import ScreenshotBackfiller, load_config
ScreenshotBackfiller(load_config(), '$(date +%Y%m%d)-zhixing').run()
"
```

### Phase A 写入失败（401 / lark-cli auth）

> 数据已存入本地 SQLite（`output/zxgk_results.db`），不会丢失。飞书仅影响远程同步。

```bash
# 检查 lark-cli 授权状态
lark-cli api GET '/open-apis/authen/v1/user_info' --as user

# 如果返回 401 或 error，需要重新登录：
lark-cli auth

# 重新登录后可手动补写飞书：
source venv/bin/activate
python3 -m writers.feishu --input output/zxgk_batch_$(date +%Y%m%d)_zhixing.json --subsite zhixing
```

### 验证码服务异常

> 如使用自己的 OCR 方案，确保 localhost:8001 提供 `GET /health` 和 `POST /solve` 接口，两者兼容即可。

```bash
# Docker 方式（推荐）
cd captcha-solver
docker compose up -d

# 裸机方式（fallback）
cd captcha-solver && source venv/bin/activate
PORT=8001 nohup python3 main.py > /tmp/captcha_solver.log 2>&1 &
sleep 4 && curl -s http://localhost:8001/health
```

---

## 诊断工具

```bash
source venv/bin/activate

# 冒烟测试（语法/配置/依赖/环境变量）
bash smoke_test.sh

# DOM 诊断（三子站表格结构/列数/WAF元素）
python3 diagnose_subsites.py

# 单条查询测试
python3 zxgk_query.py --company "XX公司" --subsite zhixing --mode text-only --output /tmp/test.json
```

---

## 关键文件

| 文件 | 用途 |
|------|------|
| `setup.sh` | 首次安装 — 依赖全自动装好 |
| `zxgk_query.py` | 主 CLI — 查询/截图/Phase B |
| `cron_daily_query.sh` | 编排脚本 — Phase A + B 全流程 |
| `writers/sqlite.py` | 本地 SQLite 储存（始终写入，零依赖） |
| `writers/feishu.py` | 飞书读写 — raw表写入/去重/交叉匹配/截图上传（可选） |
| `writers/` | 可插拔储存层（SQLite/Excel/飞书已有表/飞书自建） |
| `diagnose_subsites.py` | DOM 诊断 |
| `smoke_test.sh` | 冒烟测试 |
| `config/zxgk.yaml` | 配置（子站/飞书字段/WAF参数/公司列表） |
| `config/companies.txt` | 公司列表（权威来源，5 家） |
| `.env.example` | 环境变量模板 |

## 环境变量

| 变量 | 必须 | 说明 | 获取位置 |
|------|------|------|---------|
| `FEISHU_APP_TOKEN` | 否（可选） | 飞书多维表格 app token；不设则仅用 SQLite 本地储存 | 飞书 Base URL 中提取 |

---

## 数据流

```
zxgk.court.gov.cn
      │
      ▼
zxgk_query.py (Playwright)
      │
      ├── output/zxgk_batch_{date}_{subsite}.json
      │
      ├──▼
      │ writers/sqlite.py  →  output/zxgk_results.db（始终写入，零依赖）
      │
      └──▼ (仅当 FEISHU_APP_TOKEN 已配置且 lark-cli 已认证)
        writers/feishu.py
            ├── raw 表 (tbl_raw_xxxxx) — 每日快照
            │     └── DuplexLink「案件主表」
            │           │
            │           ▼
            └── 案件主表 (tbl_case_xxxxx)
                  ├── 案号提取 / 是否失信 / 是否限高
                  ├── 截图 (Phase B 回填)
                  └── raw_一级 (反向 Link → raw 表)
```
