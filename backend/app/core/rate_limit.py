"""进程内滑动窗口限流器(单机部署,无 Redis,内存实现即可)。

用途:登录接口防爆破、注册接口防刷、问答接口防滥用。
对外只暴露 SlidingWindowLimiter.check(key, limit, window_seconds) -> bool。
"""
import asyncio
import time
from collections import defaultdict, deque


class SlidingWindowLimiter:
    """按 key 维护滑动窗口内的调用时间戳,窗口内超过 limit 次则拒绝。"""

    def __init__(self) -> None:
        self._records: dict[str, deque[float]] = defaultdict(deque)
        self._lock = asyncio.Lock()

    async def check(self, key: str, limit: int, window_seconds: float) -> bool:
        """尝试放行一次调用。返回 True=允许;False=已超限需拒绝。"""
        now = time.monotonic()
        async with self._lock:
            q = self._records[key]
            # 清掉窗口外的旧时间戳(惰性清理,顺带防内存膨胀)
            while q and now - q[0] > window_seconds:
                q.popleft()
            if len(q) >= limit:
                return False
            q.append(now)
            return True


# 进程级单例,各路由共享同一份计数
limiter = SlidingWindowLimiter()
