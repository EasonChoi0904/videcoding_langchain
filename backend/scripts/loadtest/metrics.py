# -*- coding: utf-8 -*-
"""指标采集:逐请求记录(含 ttfb_ms/tokens 结构化列) + 聚合分位 + RPS 窗口 + health 探针。"""
import asyncio
import time

import httpx

# 单条请求记录字段(op, cls, status, latency_ms, extra)
_records: list[dict] = []
_lock = asyncio.Lock()

# health 探针样本(秒级时间戳, ms)
_health: list[dict] = []
_probe_task: asyncio.Task | None = None


async def record(
    op: str, cls: str, status: int | None, latency_ms: float,
    extra: str = "", ttfb_ms: float = 0.0, tokens: int = 0,
) -> None:
    """记录一条请求结果(线程安全)。

    Args:
        ttfb_ms: 仅 ask 有意义——SSE 首帧(TTFB/首 token)耗时,供 A4 门禁判定
        tokens: 仅 ask 有意义——SSE token 事件数
    """
    async with _lock:
        _records.append(
            {
                "ts": round(time.time(), 3),
                "op": op,
                "cls": cls,
                "status": status or "",
                "latency_ms": round(latency_ms, 1),
                "extra": extra,
                "ttfb_ms": round(ttfb_ms, 1),
                "tokens": tokens,
            }
        )


def snapshot() -> list[dict]:
    """取当前全部记录(报告阶段调用,需无并发写入)。"""
    return list(_records)


def percentile(values: list[float], p: float) -> float:
    """普通分位计算(线性插值,与 numpy 默认一致)。"""
    if not values:
        return 0.0
    s = sorted(values)
    k = (len(s) - 1) * p
    lo, hi = int(k), min(int(k) + 1, len(s) - 1)
    return s[lo] + (s[hi] - s[lo]) * (k - lo)


async def start_health_probe(base: str) -> None:
    """旁路事件循环探针:每 100ms 打一次 /api/health,记录延迟样本。"""
    global _probe_task
    if _probe_task is not None:
        return

    async def _probe() -> None:
        try:
            async with httpx.AsyncClient(timeout=5.0) as c:
                while True:
                    t0 = time.monotonic()
                    try:
                        await c.get(f"{base}/health")
                    except Exception:  # noqa: BLE001 服务器忙时记录失败样本
                        pass
                    _health.append({"ts": time.time(), "ms": (time.monotonic() - t0) * 1000})
                    await asyncio.sleep(0.1)
        except asyncio.CancelledError:
            return

    _probe_task = asyncio.create_task(_probe())


async def stop_health_probe() -> None:
    """停掉探针并返回样本列表。"""
    global _probe_task
    if _probe_task is not None:
        _probe_task.cancel()
        try:
            await _probe_task
        except (asyncio.CancelledError, Exception):  # noqa: BLE001
            pass
        _probe_task = None
    return list(_health)


def reset() -> None:
    """场景间重置(报告数据已落盘后调用)。"""
    _records.clear()
    _health.clear()
