"""Async concurrency primitives for parallel subsite execution.

RateGate  — sliding-window rate limiter (replaces time.sleep(company_interval)).
WafCircuitBreaker — coordinated suspension across all subsites on WAF detection.

ThreadRateGate  — thread-safe variant for ThreadPoolExecutor-based parallel mode.
ThreadWafCircuitBreaker — thread-safe circuit breaker for multi-thread coordination.
"""

import asyncio
import logging
import threading
import time

logger = logging.getLogger("zxgk_query")


class RateGate:
    """Sliding-window token-bucket rate limiter.

    Unlike a Semaphore, RateGate cares about "how many operations in the last N seconds".
    Supports a burst allowance so short bursts (e.g. screenshot sequences) don't stall.

    Usage:
        gate = RateGate(rate=1/30, burst=1)  # 1 op per 30s steady-state
        for company in companies:
            await gate.acquire()
            query(company)
    """

    def __init__(self, rate: float, burst: int = 1):
        """
        Args:
            rate:  Maximum steady-state operations per second (e.g. 1/30 = 0.033).
            burst: Number of operations allowed without waiting (initial tokens).
        """
        self._rate = rate
        self._burst = burst
        self._tokens = float(burst)
        self._last = time.monotonic()
        self._lock = asyncio.Lock()

    async def acquire(self):
        """Wait until a token is available, then consume one."""
        async with self._lock:
            now = time.monotonic()
            elapsed = now - self._last
            # Refill tokens based on elapsed time
            self._tokens = min(self._burst, self._tokens + elapsed * self._rate)
            self._last = now

            if self._tokens < 1:
                # Not enough tokens — sleep until one is available
                wait = (1 - self._tokens) / self._rate
                await asyncio.sleep(wait)
                self._tokens = 0.0
                self._last = time.monotonic()
            else:
                self._tokens -= 1.0


class WafCircuitBreaker:
    """Coordinated WAF cooldown across ALL concurrent subsite tasks.

    When ANY subsite hits WAF, trip() pauses ALL tasks for cooldown_sec.
    Tasks call check() before each company query — returns False during cooldown
    so they skip the company rather than hitting the WAF again.

    Usage:
        breaker = WafCircuitBreaker(cooldown_sec=300)
        # Shared across all subsite tasks
        for company in companies:
            if not await breaker.check():
                continue  # still cooling down, skip
            try:
                query(company)
            except WafBlockedError:
                await breaker.trip()  # pauses ALL tasks
    """

    def __init__(self, cooldown_sec: int = 300):
        self._cooldown = cooldown_sec
        self._lock = asyncio.Lock()
        self._event = asyncio.Event()
        self._event.set()  # initially not blocked

    async def check(self) -> bool:
        """Return True if requests are allowed, False if in WAF cooldown."""
        return self._event.is_set()

    async def trip(self):
        """Trigger WAF cooldown — blocks all tasks for cooldown_sec, then auto-resets."""
        async with self._lock:
            if not self._event.is_set():
                return  # already tripped by another task
            self._event.clear()

        logger.warning("WAF 断路器跳闸 — 所有子站暂停 %ds", self._cooldown)
        await asyncio.sleep(self._cooldown)

        async with self._lock:
            self._event.set()
        logger.info("WAF 断路器已重置 — 恢复查询")


# ---------------------------------------------------------------------------
# Thread-safe variants — for ThreadPoolExecutor-based parallel execution
# ---------------------------------------------------------------------------

class ThreadRateGate:
    """Thread-safe sliding-window token-bucket rate limiter.

    Identical algorithm to RateGate but uses threading.Lock + time.sleep
    instead of asyncio primitives. Safe to share across ThreadPoolExecutor workers.

    Usage:
        gate = ThreadRateGate(rate=1/30, burst=1)  # 1 op per 30s steady-state
        for company in companies:
            gate.acquire()
            query(company)
    """

    def __init__(self, rate: float, burst: int = 1):
        self._rate = rate
        self._burst = burst
        self._tokens = float(burst)
        self._last = time.monotonic()
        self._lock = threading.Lock()

    def acquire(self):
        """Block until a token is available, then consume one."""
        with self._lock:
            now = time.monotonic()
            elapsed = now - self._last
            self._tokens = min(self._burst, self._tokens + elapsed * self._rate)
            self._last = now

            if self._tokens < 1:
                wait = (1 - self._tokens) / self._rate
                time.sleep(wait)
                self._tokens = 0.0
                self._last = time.monotonic()
            else:
                self._tokens -= 1.0


class ThreadWafCircuitBreaker:
    """Thread-safe coordinated WAF cooldown across ALL concurrent subsite threads.

    Uses threading.Event + threading.Lock for multi-thread coordination.
    When ANY subsite hits WAF, trip() pauses ALL threads for cooldown_sec.
    """

    def __init__(self, cooldown_sec: int = 300):
        self._cooldown = cooldown_sec
        self._lock = threading.Lock()
        self._event = threading.Event()
        self._event.set()  # initially not blocked

    def check(self) -> bool:
        """Return True if requests are allowed, False if in WAF cooldown."""
        return self._event.is_set()

    def trip(self):
        """Trigger WAF cooldown — blocks all threads for cooldown_sec, then auto-resets."""
        with self._lock:
            if not self._event.is_set():
                return  # already tripped by another thread
            self._event.clear()

        logger.warning("WAF 断路器跳闸 — 所有子站暂停 %ds", self._cooldown)
        time.sleep(self._cooldown)

        with self._lock:
            self._event.set()
        logger.info("WAF 断路器已重置 — 恢复查询")
