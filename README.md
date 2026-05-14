# zxgk-daily-query

自动化查询被执行人/失信被执行人/限制消费人员三子站的每日工具。

> ⚠️ **前置条件**：依赖本地 OCR 验证码识别服务（`localhost:8001`）。
> 可安装内置 PaddleOCR（`setup.sh` 自动处理），或自行部署兼容 `GET /health` + `POST /solve` 接口的服务。

## 系统要求

- **内存 ≥ 4GB RAM**（captcha-solver OCR 模型 ~1.5GB + Chromium ~500MB）
- Python 3.10+、npm、Docker（可选，推荐 OCR 服务使用 Docker）
- OCR 服务：推荐内置 PaddleOCR，也支持自行部署（Docker / 自定义，兼容 localhost:8001 的 `/solve` API）
- 支持 Ubuntu、macOS

## 快速开始

```bash
# 1. 安装依赖
bash setup.sh

# 2. 配置
cp config/companies.example.txt config/companies.txt
# 编辑 companies.txt 填入你要查的公司

# 3. 运行
bash cron_daily_query.sh
```

## 环境变量

| 变量 | 说明 |
|------|------|
| `FEISHU_APP_TOKEN` | 飞书多维表格 Base token（可选，不设则结果存 SQLite） |

## 储存方式（任选一种）

| 方式 | 命令 |
|------|------|
| SQLite（默认） | `python3 -m writers.sqlite --input batch.json` |
| Excel | `python3 -m writers.excel --input batch.json` |
| 飞书自动建表 | `python3 -m writers.feishu_build --input batch.json --app-token xxx` |
| 飞书已有表 | `python3 -m writers.feishu --input batch.json --subsite zhixing` |

## 脚本清单

| 脚本 | 用途 |
|------|------|
| `zxgk_query.py` | 主 CLI — Playwright 浏览器自动化查询 |
| `cron_daily_query.sh` | 每日编排 — 三子站查询 + 写入 + 截图回填 |
| `setup.sh` | 一键安装所有依赖 |
| `smoke_test.sh` | 冒烟测试 — 语法/配置/依赖/环境变量 |
| `diagnose_subsites.py` | 三子站 DOM 诊断 |

## 子站说明

| 子站 | 参数值 | 列数 | 特殊处理 |
|------|--------|------|---------|
| 被执行人 | `zhixing` | 5 列 | — |
| 失信被执行人 | `shixin` | 5 列 | `#pProvince` 设为"全部" |
| 限制消费人员 | `xgl` | 6 列 | 多一列企业信息 |

## 查询示例

```bash
source venv/bin/activate

# 单条查询
python3 zxgk_query.py --company "XX公司"

# 批量查询
python3 zxgk_query.py --batch config/companies.txt --subsite zhixing \
  --mode text-only --output output/batch.json

# 全流程（三子站）
bash cron_daily_query.sh
```

## 配置

```bash
cp config/zxgk.example.yaml config/zxgk.yaml
# 编辑 zxgk.yaml — 填入你的飞书表 ID 和字段映射
# 不填则仅使用 SQLite 本地储存
```

## 返回值

| Exit Code | 含义 |
|-----------|------|
| 0 | 查询成功 |
| 1 | 查询无结果 |
| 2 | WAF 封禁 |
| 3 | captcha-solver 不可用 |
| 4 | 配置/参数错误 |

## 项目结构

```
zxgk-daily-query/
├── zxgk_query.py
├── cron_daily_query.sh
├── setup.sh
├── smoke_test.sh
├── diagnose_subsites.py
├── writers/
│   ├── sqlite.py
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
