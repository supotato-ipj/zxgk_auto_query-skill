# zxgk-daily-query

自动化查询被执行人/失信被执行人/限制消费人员三子站的每日工具。

> ⚠️ **前置条件**：依赖本地 OCR 验证码识别服务（`localhost:8001`）。
> 可安装内置 PaddleOCR（`setup.sh` 自动处理），或自行部署兼容 `GET /health` + `POST /solve` 接口的服务。

## 系统要求

- **内存 ≥ 4GB RAM**（captcha-solver OCR 模型 ~1.5GB + Chromium ~500MB）
- Python 3.10+（`--async` 并行模式需 Python 3.11+）
- npm、Docker（可选，推荐 OCR 服务使用 Docker）
- OCR 服务：推荐内置 PaddleOCR，也支持自行部署（Docker / 自定义，兼容 localhost:8001 的 `/solve` API）
- 支持 Ubuntu、macOS

## 快速开始

```bash
# 1. 安装依赖
bash setup.sh

# 2. 配置
cp config/companies.example.txt config/companies.txt
cp config/zxgk.example.yaml config/zxgk.yaml
# 编辑 companies.txt 填入你要查的公司

# 3. 运行
bash cron_daily_query.sh
```

## 环境变量

| 变量 | 说明 |
|------|------|
| `FEISHU_APP_TOKEN` | 飞书多维表格 Base token（可选，不设则结果存 SQLite） |
| `PARALLEL=true` | 启用三子站异步并发查询模式（cron 脚本，需 Python 3.11+） |

## CLI 用法

```bash
source venv/bin/activate

# 单条查询
python3 zxgk_query.py --company "XX公司"

# 单条查询 + 飞书写入
python3 zxgk_query.py --company "XX公司" --mode text-only --feishu

# 批量查询（单个子站）
python3 zxgk_query.py --batch config/companies.txt --subsite zhixing \
  --mode text-only --output output/batch.json

# 异步并发模式（三子站同时查询，需 Python 3.11+）
python3 zxgk_query.py --async --batch config/companies.txt --mode text-only

# 全流程模式（文本+截图+飞书）
python3 zxgk_query.py --batch config/companies.txt --mode full --feishu

# 断点续跑
python3 zxgk_query.py --batch config/companies.txt --resume

# 截图回填模式
python3 zxgk_query.py --mode backfill --batch-id "20260510-zhixing" --feishu

# 诊断模式（检查 WAF 状态和依赖）
python3 zxgk_query.py --diagnose
```

## 查询模式

| 模式 | 参数 | 说明 |
|------|------|------|
| 纯文本 | `--mode text-only` | 只收集案件编号、被执行人、日期、viewId，少量网络请求 |
| 截图 | `--mode screenshot` | 文本 + 每条点击详情弹窗截图（OpenCV 像素级裁剪） |
| 全流程 | `--mode full` | 文本 + 截图 + 自动飞书写入 |
| 回填 | `--mode backfill` | 按 batch-id 回填已有记录的截图到飞书 |
| 诊断 | `--diagnose` | 检查 captcha-solver 和 WAF 状态 |

## 异步并发模式

启用 `--async`（或 `PARALLEL=true` 在 cron 脚本中）后，三个子站（zhixing/shixin/xgl）将在独立线程中并行查询，通过 `ThreadPoolExecutor` 实现同步 Playwright API 的安全封装。

- 需 Python 3.11+（`asyncio.TaskGroup`）
- 内置 `ThreadRateGate` 速率控制和 `ThreadWafCircuitBreaker` 熔断保护
- WAF 封禁时自动冷却，子站间互不影响

## 截图技术

弹窗详情截图采用 OpenCV 像素级精准裁剪：

- **全内存处理**：`page.screenshot()` 返回 bytes，Canny 边缘检测 → 轮廓筛选 → 白底检测 → 列投影精裁，全程无中间磁盘 IO
- 单条记录节省约 318KB 磁盘读写
- 上传完成后自动删除本地截图文件，防止磁盘累积

## 储存方式（任选一种）

| 方式 | 命令 |
|------|------|
| SQLite（默认） | `python3 -m writers.sqlite --input batch.json` |
| SQLite（BLOB 截图） | `python3 -m writers.sqlite --input batch.json --store-screenshots blob` |
| Excel | `python3 -m writers.excel --input batch.json` |
| 飞书自动建表 | `python3 -m writers.feishu_build --input batch.json --app-token xxx` |
| 飞书已有表 | `python3 -m writers.feishu --input batch.json --subsite zhixing` |

> `--store-screenshots blob` 将截图二进制存入 SQLite，写入成功后自动删除本地文件。

## 配置

```bash
cp config/zxgk.example.yaml config/zxgk.yaml
```

关键配置项：

| 配置节 | 说明 |
|--------|------|
| `subsites` | 子站 CSS 选择器、等待时间 |
| `browser` | 浏览器路径、headless、viewport |
| `waf` | 公司间隔、封禁冷却、最大重试 |
| `captcha_server` | OCR 服务地址（默认 `http://localhost:8001`） |
| `screenshots` | 截图启用/禁用 |
| `storage` | 截图存储方式（`file`/`blob`/`both`） |

## 子站说明

| 子站 | 参数值 | 列数 | 特殊处理 |
|------|--------|------|---------|
| 被执行人 | `zhixing` | 5 列 | — |
| 失信被执行人 | `shixin` | 5 列 | `#pProvince` 设为"全部" |
| 限制消费人员 | `xgl` | 6 列 | 多一列企业信息 |

## 返回值

| Exit Code | 含义 |
|-----------|------|
| 0 | 查询成功 |
| 1 | 查询无结果 |
| 2 | WAF 封禁 |
| 3 | captcha-solver 不可用 |
| 4 | 配置/参数错误 |

## 脚本清单

| 脚本 | 用途 |
|------|------|
| `zxgk_query.py` | 主 CLI — 查询/截图/回填/诊断 |
| `cron_daily_query.sh` | 每日编排 — 三子站查询 + 写入 + 截图回填（支持 PARALLEL 模式） |
| `setup.sh` | 一键安装所有依赖（pip -r requirements.txt + playwright 浏览器） |
| `smoke_test.sh` | 冒烟测试 — 语法/配置/依赖/环境变量/包导入 |
| `diagnose_subsites.py` | 三子站 DOM 诊断 |

## 依赖管理

使用 `requirements.txt` 集中管理 Python 依赖：

```
playwright, playwright-stealth, PyYAML, requests,
opencv-python-headless, numpy, httpx
```

## 项目结构

```
zxgk-daily-query/
├── zxgk_query.py              # CLI 入口（thin wrapper）
├── zxgk/                      # 核心包
│   ├── cli.py                 # CLI 参数解析与入口
│   ├── runner.py              # 批量查询编排（同步）
│   ├── async_runner.py        # 异步并发编排（三子站并行）
│   ├── async_primitives.py    # 线程安全的 RateGate / CircuitBreaker
│   ├── browser.py             # Playwright 浏览器生命周期管理
│   ├── captcha.py             # OCR 验证码求解器
│   ├── query.py               # 查询引擎（填表/OCR/提交/翻页）
│   ├── screenshot.py          # OpenCV 弹窗截图提取
│   ├── backfill.py            # 截图回填
│   ├── config.py              # 配置加载与工具函数
│   └── exceptions.py          # 自定义异常
├── cron_daily_query.sh
├── setup.sh
├── smoke_test.sh
├── diagnose_subsites.py
├── requirements.txt
├── writers/
│   ├── sqlite.py              # SQLite（支持 BLOB 截图存储）
│   ├── excel.py
│   ├── feishu.py
│   └── feishu_build.py
├── config/
│   ├── zxgk.example.yaml
│   └── companies.example.txt
├── captcha-solver/
└── docs/
    └── architecture.md
```

## License

MIT — 详见 [LICENSE](LICENSE)
