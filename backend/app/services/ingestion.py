"""文档解析入库管理(进程内 asyncio 任务)。

设计说明(无 Celery/Redis 约束下选型):
- lifespan 启动 2 个常驻 worker,从 asyncio.Queue 取"待处理文档 id"
- 解析状态落库(documents.parse_status),前端轮询展示进度
- 失败可单文档重试;应用退出时优雅停止
"""
import asyncio
import logging

from app.core.settings import get_settings
from app.db import async_session_maker
from app.models import Document

logger = logging.getLogger(__name__)


class IngestManager:
    """解析任务调度器:入队 + 常驻 worker 消费 + 优雅停止。"""

    WORKER_COUNT = 2  # 并发解析文档数(受百炼 QPS 与单机 CPU 限制,2 个足够)

    def __init__(self) -> None:
        self._queue: asyncio.Queue[int] = asyncio.Queue()
        self._tasks: list[asyncio.Task] = []
        self._stopping = False

    # ---------- 生命周期 ----------
    async def start(self) -> None:
        """启动常驻 worker,并把库里遗留的 pending 任务重新入队(重启后不丢任务)。"""
        async with async_session_maker() as db:
            from sqlalchemy import select

            rows = await db.scalars(
                select(Document.id).where(Document.parse_status == "pending")
            )
            for doc_id in rows:
                self._queue.put_nowait(doc_id)
            if get_settings().dashscope_api_key:
                leftover = await db.scalars(
                    select(Document.id).where(Document.parse_status == "parsing")
                )
                for doc_id in leftover:
                    # 上次进程中断遗留的 parsing 态,重置为 pending 重新解析
                    doc = await db.get(Document, doc_id)
                    if doc:
                        doc.parse_status = "pending"
            await db.commit()
        for i in range(self.WORKER_COUNT):
            task = asyncio.create_task(self._worker(i), name=f"ingest-worker-{i}")
            self._tasks.append(task)
        logger.info("解析 worker 已启动 ×%d", self.WORKER_COUNT)

    async def stop(self) -> None:
        """置停止标记,等待 worker 处理完当前文档后退出。"""
        self._stopping = True
        for _ in self._tasks:
            self._queue.put_nowait(None)  # 哨兵:逐个唤醒 worker 退出
        for t in self._tasks:
            try:
                await asyncio.wait_for(t, timeout=10)
            except (asyncio.TimeoutError, Exception):  # noqa: BLE001
                t.cancel()
        logger.info("解析 worker 已停止")

    # ---------- 对外接口 ----------
    def enqueue(self, doc_id: int) -> None:
        """把文档投入解析队列(幂等:同任务重复入队由 worker 判状态过滤)。"""
        if not self._stopping:
            self._queue.put_nowait(doc_id)

    # ---------- worker ----------
    async def _worker(self, idx: int) -> None:
        logger.debug("worker %d 就绪", idx)
        while True:
            doc_id = await self._queue.get()
            if doc_id is None or self._stopping:
                return
            try:
                await self._process(doc_id)
            except Exception as e:  # noqa: BLE001 单文档失败不拖垮 worker
                logger.exception("文档 %s 解析异常: %s", doc_id, e)
            finally:
                self._queue.task_done()

    async def _process(self, doc_id: int) -> None:
        """单文档解析入口(完整管道在 M2 里程碑实现)。"""
        from app.services.ingest_pipeline import run_ingest_pipeline

        await run_ingest_pipeline(doc_id)


# 进程级单例
ingest_manager = IngestManager()
