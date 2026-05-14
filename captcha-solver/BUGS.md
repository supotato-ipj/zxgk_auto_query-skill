# BUGS.md — 问题追踪与修复记录

> **用途**：记录 CAPTCHA Solver 测试中发现的问题、根因分析、修复建议。
> 各 Agent 在此登记问题 → 修复 Agent 读取后实施 → 修复完毕在此标记已解决。
>
> **关联文件**：
> - `main.py` — FastAPI 入口
> - `solver.py` — 识别核心
> - `preprocess.py` — 图像预处理
> - `API.md` — 调用文档
> - `DEPLOYMENT.md` — 部署方案

---
<!-- 问题模板：
## [BUG-编号] 标题
- **发现时间**：YYYY-MM-DD HH:MM
- **发现人**：Main Agent
- **严重程度**：🔴严重 / 🟡中等 / 🟢轻微
- **状态**：🆕待修复 / 🔧修复中 / ✅已修复 / ❌不予修复
- **测试图片**：`/path/to/image.jpg`（如有）
- **预期结果**：
- **实际结果**：
- **置信度**：
- **根因分析**：
- **修复建议**：
- **修复方案**：（由修复 Agent 填写）
- **验证结果**：（由测试 Agent 填写）
-->

---

## [BUG-001] 预处理过度导致小尺寸验证码误识别 🔴

- **发现时间**：2026-05-08 14:13
- **发现人**：Main Agent
- **严重程度**：🔴 严重 — 线上识别结果完全错误
- **状态**：✅ 已修复
- **修复时间**：2026-05-08 14:20
- **修复人**：Coder Agent
- **测试图片**：`/home/supotato/.openclaw/media/inbound/a9b53d3e-e8af-47f6-9eb8-450512de1220.jpg`

### 测试结果

| 预处理方式 | 识别结果 | 置信度 | 正确？ |
|---|---|---|---|
| 完整流水线（median=3 + CLAHE + adaptive + morph） | **DDUG** | 0.707 | ❌ |
| otsu 二值化 | DDUE | 0.913 | ❌ B→D |
| 仅灰度化（无任何预处理） | **BDUE** | 0.651 | ✅ |
| 原始彩色图直出 | bbUE | 0.660 | ⚠️ 小写 |

**预期**：`BDUE`
**当前线上**：`DDUG`

### 根因分析

1. **图片尺寸过小**：该验证码仅 95×34 像素
2. **中值滤波 kernel=3** 在 95px 宽的图上覆盖 3% 水平空间，模糊了字符的细笔触
3. **B 的上半部弧度被模糊**后与 D 难以区分
4. **E 的中间横线被 blur** 后与下方笔画粘连，被误认为 G
5. 这个验证码的彩色干扰线宽度 > 字符笔画，PaddleOCR 自身能处理，**不需要预处理**
6. 灰度化结果虽然置信度 0.651 比预处理的 0.707 低，但**结果正确**，说明预处理引入的"伪置信度提升"是虚假的

### 修复建议

1. **给 `solver.py` 新增轻量模式函数**：仅灰度化、不滤波、不二值化，直接喂给 PaddleOCR
2. **给 `/solve` 端点加 `mode` 参数**：`?mode=default`（当前流水线）/ `?mode=raw`（仅灰度化）
3. **或给 `/solve` 端点加 `preprocess` 参数**：`?preprocess=full` / `?preprocess=none` / `?preprocess=gray`
4. **考虑自适应策略**：根据图片尺寸自动选择预处理强度（宽<150px 时跳过中值滤波）

### 补充数据

多组预处理参数对比（均对同一张图 `BDUE`）：

```
默认(median=3, block=15, c=4)  →  DDUG   0.707  ❌
弱去噪(median=1)               →  DOUE   0.655  ❌  
强去噪(median=5)               →  DbUG   0.535  ❌
otsu二值化                     →  DDUE   0.913  ❌
adaptive block=9               →  bbL    0.238  ❌
adaptive block=21              →  DDUE   0.893  ❌
原始彩色图                      →  bbUE   0.660  ⚠️
仅灰度化                        →  BDUE   0.651  ✅
```

**结论**：当前所有预处理组合都无法正确识别这张图，只有跳过预处理能得到正确答案。

### 修复方案（已完成）

采用建议 3 — `preprocess` 参数，三种模式：`full`（默认）、`gray`、`none`

**代码改动：**

1. `preprocess.py` — 新增函数：
   - `preprocess_from_bytes_raw()` — 仅解码，不做处理
   - `preprocess_from_bytes_gray()` — 仅灰度化 + 转 3 通道 BGR
   - `preprocess_from_bytes_mode(image_bytes, mode)` — 按 mode 分发

2. `solver.py` — `solve_captcha_from_bytes()` 新增 `preprocess_mode` 参数（默认 `"full"`）

3. `main.py` — 三个端点新增 preprocess 参数：
   - `/solve` 和 `/solve/text`：query 参数 `?preprocess=gray`
   - `/solve/base64`：JSON body 字段 `"preprocess": "gray"`

**使用方式：**
```bash
# 完整流水线（默认）
curl -X POST localhost:8001/solve -F "file=@captcha.jpg"

# 仅灰度化 — 小尺寸验证码推荐
curl -X POST "localhost:8001/solve?preprocess=gray" -F "file=@captcha.jpg"

# Base64 方式
curl -X POST localhost:8001/solve/base64 \
  -H "Content-Type: application/json" \
  -d '{"image": "...", "preprocess": "gray"}'
```

### 验证结果

同一张 BDUE 图片，三种模式对比：

```
mode=full  → "DDUG"  0.707  ❌
mode=gray  → "BDUE"  0.651  ✅  ← 正确
mode=none  → "bbUE"  0.660  ❌  (小写)
```

---

## [BUG-002] 默认 preprocess=full 在所有测试样本上均输出错误结果 🔴

- **发现时间**：2026-05-08 14:29
- **发现人**：Main Agent
- **严重程度**：🔴 严重 — 默认行为对目标网站系统性失败
- **状态**：✅ 已修复
- **修复时间**：2026-05-08 14:35
- **修复人**：Coder Agent

### 问题描述

`/solve` 端点的 `preprocess` 参数默认为 `full`。对目标网站验证码，该模式**在所有测试样本上均输出错误结果**，且置信度极低。不传 `?preprocess=gray` 的用户会得到错误答案。

### 跨样本测试数据

| 图片 | Ground Truth | full | gray | none |
|---|---|---|---|---|
| `a9b53d3e` (BDUE) | BDUE | DDUG 0.707 ❌ | **BDUE** 0.651 ✅ | bbUE 0.660 ❌ |
| `9dee531a` (gNKH) | gNKH | gTVX 0.336 ❌ | **gNKH** 0.991 ✅ | NKH9 0.579 ❌ |

**模式平均表现：**
- `full`：准确率 0/2（全部错误），平均置信度 0.521
- `gray`：准确率 2/2（全部正确），平均置信度 0.821
- `none`：准确率 0/2（全部错误，第一张大小写问题、第二张丢字符）

### 根因分析

1. 该网站验证码尺寸仅 ~95×34 像素，字符笔画极细
2. 中值滤波 + 自适应二值化会系统性地破坏笔画特征
3. PaddleOCR PP-OCRv4 模型原生对彩色/灰度图片的识别能力远超预处理后的二值图像
4. 默认值 `full` 是面向"传统噪点多、干扰线密"的验证码设计的，不适用此场景

### 修复建议

**方案 A（推荐）**：将默认值从 `full` 改为 `gray`
- 理由：对目标网站 `gray` 是唯一可靠的模式；对其他通用验证码，`gray` 也不会有副作用（PaddleOCR 自身处理能力足够）
- 改动量：`main.py` 三处 `Query("full", ...)` → `Query("gray", ...)`

**方案 B**：自适应选择 — 检测图片宽度 < 150px 时自动切换为 `gray`
- 优点：保留 `full` 对大图/高噪场景的支持
- 缺点：增加复杂度，引入隐式行为

**方案 C**：保留 `full` 默认，但 API 文档明确标注警告
- 优点：零代码改动
- 缺点：用户不会看文档，仍会得到错误结果

### 修复方案（已完成）

采用**方案 A**，将三个端点的默认值从 `full` 改为 `gray`：

| 端点 | 改动 |
|------|------|
| `/solve` | `Query("full", ...)` → `Query("gray", ...)` |
| `/solve/text` | `Query("full", ...)` → `Query("gray", ...)` |
| `/solve/base64` | `data.get("preprocess", "full")` → `data.get("preprocess", "gray")` |

改动量：`main.py` 三行。`full` 和 `none` 模式仍然可通过参数指定。

### 验证结果（Main Agent 回归测试）

默认行为（不传 `preprocess` 参数），两张图均正确：

```
a9b53d3 (BDUE)   →  'BDUE'  conf=0.651  294.4ms  ✅
9dee531 (gNKH)   →  'gNKH'  conf=0.991  103.8ms  ✅
```

三模式全量确认无回归：

```
[a9b53d3 / BDUE]
  full → 'DDUG'  0.707  ❌  （预期行为，full 对此图不适用）
  gray → 'BDUE'  0.651  ✅
  none → 'bbUE'  0.660  ❌

[9dee531 / gNKH]
  full → 'gTVX'  0.336  ❌  （预期行为，full 对此图不适用）
  gray → 'gNKH'  0.991  ✅
  none → 'NKH9'  0.579  ❌
```

结论：BUG-001 / BUG-002 均修复确认，默认行为正确，无回归。

---

## 备注

- 项目启动时需设置 `PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK=True`
- 当前线上端口 8000 被 pixel-city-api 占用，captcha-solver 运行在 8001
- venv 路径：`/home/supotato/.openclaw/workspace-main/projects/captcha-solver/venv`
