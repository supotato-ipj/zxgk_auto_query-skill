# Async Runner Bug — Playwright Sync API Conflict

**Date:** 2026-05-16
**Found by:** 测试执行
**Priority:** High (async 模式完全不可用)
**Status:** Open

---

## 现象

```bash
python3 zxgk_query.py --async --batch config/companies.txt --feishu --mode text-only
```

三子站全部报错，0 条查询成功：

```
[zhixing] 子站任务异常: It looks like you are using Playwright Sync API inside the asyncio loop.
          Please use the Async API instead.

[shixin]  子站任务异常: It looks like you are using Playwright Sync API inside the asyncio loop.
          Please use the Async API instead.

[xgl]     子站任务异常: It looks like you are using Playwright Sync API inside the asyncio loop.
          Please use the Async API instead.

总计: ✅0 无结果0 封禁0 错误3
```

## 根因

`zxgk/async_runner.py` — `AsyncBatchRunner.run()` 方法中，浏览器生命周期（`BrowserManager.launch()` / `navigate()`）在 `async def run()` 方法体内直接同步调用，Playwright Sync API 检测到运行中的 asyncio event loop 立即拒绝。

```python
# async_runner.py ~L80-99 — 问题代码
class AsyncBatchRunner:
    async def run(self):
        ...
        self._bm = BrowserManager(self.config)   # ← async 上下文
        self._bm.launch()                         # ← Playwright 检测到 event loop → 报错
        self._bm.navigate(self.subsite)           # ← 同上

        self._engine = QueryEngine(...)           # ← 同上

        for idx, company in enumerate(pending):
            ...
            records = await asyncio.to_thread(    # ← asyncio.to_thread 也无法隔离
                self._query_one_company, company) #    线程中 event loop 仍然可见
```

`asyncio.to_thread()` 创建的线程仍处于 asyncio 事件循环的上下文中，Playwright 能检测到并拒绝。

## 影响范围

- `--async` / `--parallel` 模式：**100% 失败**
- 顺序模式（`--batch` 不带 `--async`）：不受影响，正常工作
- 测试环境：Python 3.11+, Playwright 1.58.0

## 修复方向

将整个浏览器生命周期（launch → navigate → query loop → close）完全移出 asyncio 上下文，让 Playwright Sync API 在纯 OS 线程中运行。

可选方案：
1. 用 `concurrent.futures.ThreadPoolExecutor` + `loop.run_in_executor()` 包裹整个 subsite runner，而非仅包裹单条查询
2. 用 `multiprocessing.Process` 每个子站一个独立进程，彻底隔离
3. 改用 Playwright Async API（`playwright.async_api`），但涉及较大改动

---

## 附：测试中发现的次优先级问题

### 飞书去重查询 filter.conditions 超限

当单次查询返回记录数较多时（如 40 条、22 条），飞书 API 报：

```
API error: [99992402] field validation failed
field_violations: the max len is 10
```

飞书 filter.conditions 数组最多允许 10 条条件，批量去重时超过此限制会跳过。不影响数据写入，但去重逻辑对大批量记录失效。

**位置：** `writers/feishu.py` 去重查询逻辑
