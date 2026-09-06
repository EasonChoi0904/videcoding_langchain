"""初始化脚本:建表、FTS 索引、种子数据(管理员账号 + 默认系统设置)。

启动时由 main.py 调用一次,幂等(重复执行无副作用)。
"""
import logging

from sqlalchemy import select, text

from app.core.security import hash_password
from app.db import async_session_maker, engine
from app.models import Base, Setting, User
from app.models.sql import CREATE_FTS_TABLE

logger = logging.getLogger(__name__)

# 管理员账号(答辩要求:admin / 123456)
ADMIN_USERNAME = "admin"
ADMIN_PASSWORD = "123456"

# 默认系统设置(管理端页面可动态修改并写入本表)
DEFAULT_SETTINGS: dict[str, tuple[str, str]] = {
    "rerank_threshold": ("0.45", "拒答阈值:重排分数低于该值则明确答复未找到(防幻觉)"),
    "rerank_top_n": ("5", "重排后保留的引用片段条数"),
    "hybrid_each_top_k": ("20", "混合检索双路(向量/关键词)各自召回条数"),
    "system_prompt": (
        "你是一位专业、耐心的电商智能客服助手,基于提供的商品知识库资料回答用户问题。",
        "系统提示词(追加在角色设定前)",
    ),
    "cache_enabled": ("true", "语义缓存总开关(true/false)"),
}


async def init_db() -> None:
    """建表 + 种子数据。业务代码启动前调用;测试可单独建临时库。"""
    from app.models import RefreshToken  # noqa: F401  确保模块注册到 Base.metadata

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        # FTS5 虚表无法用 ORM 定义,需原生 SQL(trigram 分词,支持中文子串)
        await conn.execute(CREATE_FTS_TABLE)

    async with async_session_maker() as db:
        # ---- 种子:管理员账号 ----
        admin = await db.scalar(select(User).where(User.username == ADMIN_USERNAME))
        if admin is None:
            db.add(
                User(
                    username=ADMIN_USERNAME,
                    password_hash=hash_password(ADMIN_PASSWORD),
                    role="admin",
                )
            )
            logger.info("已创建管理员账号: %s", ADMIN_USERNAME)

        # ---- 种子:默认系统设置 ----
        for key, (value, desc) in DEFAULT_SETTINGS.items():
            exists = await db.get(Setting, key)
            if exists is None:
                db.add(Setting(key=key, value=value, description=desc))
        await db.commit()
