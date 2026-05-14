# 架构说明

> zxgk-daily-query 系统架构，不含任何私人数据。

## 数据流

```
zxgk.court.gov.cn
      │
      ▼
zxgk_query.py (Playwright + playwright-stealth)
      │  captcha → captcha-solver (PaddleOCR, localhost:8001)
      │
      ├── output/zxgk_batch_{date}_{subsite}.json
      │
      ▼
writers/
      ├── sqlite.py     → SQLite 本地备份（零依赖）
      ├── excel.py      → xlsx 导出（openpyxl）
      ├── feishu.py     → 飞书多维表格写入（已有表）
      └── feishu_build.py → 飞书自动建表（新用户一键建表）
```

## 两表模型（飞书）

```
raw 表（每日快照）
  ├── 案号 / 被执行人 / 立案日期
  ├── DuplexLink → 案件主表
  └── 去重：按 (案号, viewId) 对

案件主表（去重汇总）
  ├── 案号提取 / 法院 / 金额
  ├── 是否失信 / 是否限高（交叉匹配）
  ├── 截图（Phase B 回填）
  └── raw_一级（反向 Link → raw 表）
```

## 查询链路

```
主站 goto(networkidle)
  → JS 点击子站 tab（CSS class 定位）
  → 子站加载 (networkidle + extra_wait)
  → 验证码截图 → captcha-solver 识别
  → initCurrentPage() + search()
  → 弹窗轮询 dismiss
  → 结果解析 + 翻页
  → showDetail(viewId) → 截图 → 关闭
```

## 验证码识别

```
Docker 服务（localhost:8001）:
  截图 → 灰度化 → 二值化 → 降噪 → PaddleOCR → 返回文本

优先 Docker 启动，fallback 到裸机 venv。
```

## 关键约束

- **不能用 `form.submit()`**: 必须 `initCurrentPage()` + `search()`
- **不能直接 goto 子站 URL**: 必须从主站 CSS class 定位点击
- **验证码搜索必须在 `#yzm` 父容器内**
- **wait_until 一律 `networkidle`**（不能用 `domcontentloaded`）
- **仅用 playwright-stealth**（不能叠手写 stealth）
- **shixin 需设 `#pProvince`="全部"**
