"""FastAPI 应用入口。

启动流程(lifespan):
1. 初始化日志
2. 建表 + 种子数据(管理员 admin/123456、默认设置)
3. 初始化向量库(Qdrant 嵌入式本地模式,建集合/探测百炼 API 能力)
4. 启动文档解析后台 worker
"""
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import api_router
from app.core.logging import setup_logging
from app.core.settings import get_settings

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期:启动时初始化基础设施,退出时清理。"""
    settings = get_settings()
    # ---- 1. 目录与日志 ----
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    setup_logging()

    # ---- 2. 建表 + 种子 ----
    from app.seed import init_db

    await init_db()
    logger.info("数据库初始化完成(含管理员与默认设置种子)")

    # ---- 2.5 启动维护:上次进程退出时遗留的"生成中"消息解除标记 ----
    from sqlalchemy import update

    from app.db import async_session_maker
    from app.models import Message

    async with async_session_maker() as db:
        result = await db.execute(
            update(Message).where(Message.is_streaming.is_(True)).values(is_streaming=False)
        )
        if result.rowcount:
            logger.info("已清理 %d 条遗留的半截消息(解除生成中标记)", result.rowcount)
        await db.commit()

    # ---- 2.75 压测 mock 层(仅 LOADTEST_MOCK_PROVIDER=1 时生效,dev-only)----
    # 挂在 init_infra 之前:mock 层就位后再初始化向量库/启动 worker,
    # 保证任何业务外呼发生前已全部替换为本地假实现
    if settings.loadtest_mock_provider:
        from app.rag import mock_provider

        mock_provider.install()

    # ---- 3. 向量库与百炼 API 探测(M2 起生效)----
    from app.services import infra  # noqa: F401
    await infra.init_infra()

    # ---- 4. 解析 worker(M2 起生效)----
    from app.services.ingestion import ingest_manager
    await ingest_manager.start()

    yield

    # ---- 退出清理 ----
    await ingest_manager.stop()


app = FastAPI(
    title=get_settings().app_name,
    description=(
        "基于 LangChain 的 RAG 企业级电商知识库问答系统 —— 支持知识库管理(仅管理员)、"
        "带引用溯源的流式问答、多会话多语言对话与历史找回。"
    ),
    version="1.0.0",
    lifespan=lifespan,
)

# 前端开发服务器跨域(Vite 默认 5173 端口)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router, prefix=get_settings().api_prefix)


@app.get("/", include_in_schema=False)
async def root():
    return {"service": get_settings().app_name, "docs": "/docs", "health": "/api/health"}


@app.get("/api/health", tags=["系统"], summary="健康检查")
async def health():
    return {"status": "ok"}
