"""数据库引擎与会话管理。

SQLite(WAL 模式)+ SQLAlchemy 2.0 异步 ORM。所有表结构定义在 models 层,
通过 SQLAlchemy 抽象可平滑迁移 PostgreSQL/MySQL(论文可写该设计)。
"""
from collections.abc import AsyncGenerator

from sqlalchemy import event
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool

from app.core.settings import get_settings


def create_engine_and_sessionmaker():
    """创建异步引擎与会话工厂。拆成函数便于测试时替换数据库文件。"""
    settings = get_settings()
    settings.data_dir.mkdir(parents=True, exist_ok=True)

    # 单进程场景不需要连接池(NullPool),每个会话独占一个连接,避免 SQLite 锁竞争
    engine = create_async_engine(
        settings.database_url,
        echo=False,
        poolclass=NullPool,
        connect_args={"timeout": 30},
    )

    # SQLite 每次新连接都启用 WAL:读写并发不互斥,问答高频读写更顺滑
    @event.listens_for(engine.sync_engine, "connect")
    def _set_sqlite_pragma(dbapi_conn, _record):
        cursor = dbapi_conn.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA synchronous=NORMAL")
        cursor.execute("PRAGMA foreign_keys=ON")  # 级联删除依赖外键约束
        cursor.close()

    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    return engine, session_factory


engine, async_session_maker = create_engine_and_sessionmaker()


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI 依赖:每个请求一个独立会话,请求结束自动关闭。"""
    async with async_session_maker() as session:
        yield session
