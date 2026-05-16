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

**Python 版本要求：** Python 3.10+，其中 `--async` 异步并发模式需要 Python 3.11+（`asyncio.TaskGroup`）。

---

## ⚠️ OCR 模型部署警示（Agent 强制执行）

首次使用本技能时，Agent **必须**在运行 `bash setup.sh` 之前，向用户展示以下信息并等待用户明确回复「同意」：

**硬件要求：**
- 内存 ≥ 4GB RAM（PaddleOCR 模型运行时 ~1.5GB + Chromium ~500MB）
- 磁盘 ≥ 3GB 可用空间（模型首次下载约 1.5GB）
- CPU 推理，无需 GPU

**将安装的内容：**
- PaddlePaddle + PaddleOCR（PP-OCRv4 英文/数字模型）
- pip 依赖通过 `requirements.txt` 安装（playwright, opencv-python-headless, numpy, PyYAML 等）

**端口说明：**
- 默认端口 `8001`，可在 `config/zxgk.yaml` 的 `captcha_server` 修改（如 `http://localhost:9001`）
- 若端口被占用，cron 脚本会自动检测并提示，不会静默失败

**替代方案（如不同意）：**
- 跳过安装，用户自行部署 captcha-solver（Docker / 裸机 venv），只需兼容 `/health` + `/solve` 接口
- 或使用其他 OCR 方案（如云端 API），替换 `captcha_server` 配置指向自定义服务

Agent 必须向用户提问确认，示例：
> 「是否同意在本地安装 PaddleOCR 模型（约 1.5GB）？回复「同意」继续安装，或选择跳过自行部署 OCR 服务。」

**用户回复「同意」后方可执行 `bash setup.sh`。回复其他内容则跳过 OCR 安装，引导用户自行部署。**

---

## 首次使用（一次性）

```bash
# 0. 获取项目（如果尚未克隆）
# git clone https://github.com/yourname/zxgk-daily-query.git
# cd zxgk-daily-query

# 1. 安装依赖（pip 通过 requirements.txt + playwright 浏览器）
bash setup.sh

# 2. （可选）配置飞书 token，不配则仅用 SQLite 本地储存
cp .env.example .env
# 编辑 .env 填入你的 FEISHU_APP_TOKEN，或直接 export FEISHU_APP_TOKEN（跳过则默认存 SQLite）

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

> 启用三子站异步并发：`PARALLEL=true bash cron_daily_query.sh`（需 Python 3.11+）

### 验证 Phase A 结果

```bash
cat /tmp/zxgk_summary_$(date +%Y%m%d).json
```

检查各子站的 `total_records` 和 `status`。

### Phase B：截图回填（已在 cron 中自动执行）

Phase B 已集成到 `cron_daily_query.sh` Step 5。如需手动执行：

```bash
source venv/bin/activate && python3 zxgk_query.py --mode backfill --batch-id "$(date +%Y%m%d)-zhixing" --feishu
```

Phase B 内部流程（由 `zxgk/backfill.py` 的 ScreenshotBackfiller 自动完成）：
1. 查案件主表 `filter: {"截图": "isEmpty"}` → 得到缺截图记录
2. 每条记录通过 raw 表「案件主表」DuplexLink 反向查找 → 取真实 viewId
3. 按公司分组，浏览器搜索 → showDetail(viewId) → OpenCV 像素级截图 → 上传飞书
4. 上传成功后自动删除本地截图文件，防止磁盘累积

---

## 并行查询模式（可选）

启用 `--async` 标志后，三个子站（zhixing/shixin/xgl）在独立线程中并行查询：

```bash
# CLI 单条/批量模式
source venv/bin/activate
python3 zxgk_query.py --async --batch config/companies.txt --mode text-only

# cron 脚本模式
PARALLEL=true bash cron_daily_query.sh
```

- 需 Python 3.11+
- 内置 `ThreadRateGate` 速率控制 + `ThreadWafCircuitBreaker` 熔断保护
- WAF 封禁时自动冷却，子站间互不影响

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
source venv/bin/activate && python3 zxgk_query.py --mode backfill --batch-id "$(date +%Y%m%d)-zhixing" --feishu
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

# 冒烟测试（语法/配置/依赖/包导入）
bash smoke_test.sh

# CLI 内置诊断（检查 captcha-solver 和 WAF 状态）
python3 zxgk_query.py --diagnose

# DOM 诊断（三子站表格结构/列数/WAF元素）
python3 diagnose_subsites.py

# 单条查询测试
python3 zxgk_query.py --company "XX公司" --subsite zhixing --mode text-only --output /tmp/test.json
```

---

## 关键文件

| 文件 | 用途 |
|------|------|
| `zxgk_query.py` | CLI 入口（thin wrapper，委托给 `zxgk/` 包） |
| `zxgk/` | 核心模块包 — cli / runner / async_runner / browser / captcha / query / screenshot / backfill / config |
| `requirements.txt` | Python 依赖清单（playwright, opencv-python-headless, numpy, PyYAML, requests, httpx） |
| `setup.sh` | 首次安装 — `pip install -r requirements.txt` + playwright 浏览器 |
| `cron_daily_query.sh` | 编排脚本 — Phase A + B 全流程（支持 PARALLEL=true 异步并发） |
| `smoke_test.sh` | 冒烟测试 — 语法/配置/依赖/环境变量/包导入 |
| `diagnose_subsites.py` | 三子站 DOM 诊断 |
| `writers/sqlite.py` | 本地 SQLite 储存（始终写入，零依赖；`--store-screenshots blob` 存二进制截图） |
| `writers/feishu.py` | 飞书读写 — raw表写入/去重/交叉匹配/截图上传（可选） |
| `writers/` | 可插拔储存层（SQLite/Excel/飞书已有表/飞书自建） |
| `config/zxgk.yaml` | 配置（子站/浏览器/WAF/存储/公司列表） |
| `config/companies.txt` | 公司列表（权威来源） |
| `.env.example` | 环境变量模板 |

## 环境变量

| 变量 | 必须 | 说明 | 获取位置 |
|------|------|------|---------|
| `FEISHU_APP_TOKEN` | 否（可选） | 飞书多维表格 app token；不设则仅用 SQLite 本地储存 | 飞书 Base URL 中提取 |
| `PARALLEL=true` | 否 | 启用三子站异步并发查询（cron 脚本，需 Python 3.11+） | — |

---

## 数据流

```
zxgk.court.gov.cn
      │
      ▼
zxgk/ (模块化包)
      ├── cli.py        — CLI 入口 & 模式路由
      ├── runner.py     — 批量查询编排（同步，单子站逐个）
      ├── async_runner.py — 异步并发编排（三子站并行，Python 3.11+）
      ├── browser.py    — Playwright 浏览器管理（启动/导航/WAF检测/清理）
      ├── captcha.py    — OCR 验证码求解
      ├── query.py      — 查询引擎（填表/OCR/提交/翻页/弹窗处理）
      ├── screenshot.py — OpenCV 像素级弹窗截图提取（全内存，无磁盘 IO）
      ├── backfill.py   — 截图回填（查飞书缺截图 → 逐条补全）
      ├── config.py     — 配置加载 / 环境变量 / 工具函数
      └── exceptions.py — WafBlockedError / SubsiteNavError
      │
      ├── output/zxgk_batch_{date}_{subsite}.json
      │
      ├──▼
      │ writers/sqlite.py  →  output/zxgk_results.db（始终写入，支持 BLOB 截图存储）
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
