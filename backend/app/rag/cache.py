"""语义缓存:高频相似问题直接回放标准答案,跳过检索与 LLM 调用。

实现:
- 问题向量存 Qdrant question_cache 集合;回答存 SQLite cache_items 表
- 命中判定:相似度 ≥ 阈值 且 知识库内容指纹一致(内容变了缓存即失效)
- 指纹 = 知识库内全部文档 sha256 排序后的 MD5(文档增删改都会变化)

只在"会话的首问"上查缓存(多轮对话上下文不同,缓存不适用)。
"""
import hashlib
import json
import logging
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.settings import get_settings
from app.models import CacheItem, Document
from app.rag import provider
from app.services import vector_store

logger = logging.getLogger(__name__)


def compute_kb_fingerprint(sha256_list: list[str]) -> str:
    """知识库内容指纹:文档集合的唯一标识(顺序无关)。"""
    joined = "|".join(sorted(sha256_list))
    return hashlib.md5(joined.encode("utf-8")).hexdigest()


async def get_fingerprint(db: AsyncSession, kb_id: int | None) -> str:
    """计算当前生效检索范围的内容指纹(kb_id 为空 = 全库)。"""
    stmt = select(Document.sha256)
    if kb_id is not None:
        stmt = stmt.where(Document.kb_id == kb_id)
    shas = (await db.scalars(stmt)).all()
    return compute_kb_fingerprint(list(shas))


async def check_cache(db: AsyncSession, question: str, language: str | None = None) -> dict | None:
    """查询语义缓存。

    Args:
        question: 用户问题
        language: 当前会话的有效回答语言(zh/en)。回答语言随会话设置变化,
            缓存命中必须要求语言一致——否则 en 会话缓存过的英文回答会被
            zh 会话的同义问题命中,绕开会话的语言指令。

    Returns:
        命中:{"answer": str, "citations": list} ;未命中:None
    """
    s = get_settings()
    if not s.cache_enabled:
        logger.debug("[cache-check] cache_enabled=False")
        return None
    q_vector = await provider.embed_one(question)
    hits = vector_store.search_cache(q_vector, top_k=1)
    if not hits or hits[0]["score"] < s.cache_sim_threshold:
        logger.debug("[cache-check] miss(无命中或分数不足): %s", hits[:1] if hits else [])
        return None
    # 语言缺失(历史遗留数据)或与当前会话语言不一致 → 不适用,按新语言重新生成
    logger.debug("[cache-check] hit top1 id=%s score=%.4f lang=%s want=%s",
                hits[0].get("cache_id"), hits[0]["score"], hits[0].get("language"), language)
    if hits[0].get("language") != language:
        return None

    cache_id = int(hits[0]["cache_id"])
    item = await db.get(CacheItem, cache_id)
    if item is None:
        return None
    # TTL 过期即失效
    if item.created_at + timedelta(seconds=s.cache_ttl_seconds) < datetime.now():
        await db.delete(item)
        vector_store.delete_cache_point(cache_id)
        await db.commit()
        return None
    # 指纹一致才有效(kb 指纹来自缓存点 payload 中的 kb_id 组合)
    kb_id = hits[0].get("kb_id")
    fp_now = await get_fingerprint(db, kb_id)
    logger.debug("[cache-check] fingerprint: cached=%s now=%s", item.kb_fingerprint, fp_now)
    if item.kb_fingerprint != fp_now:
        return None
    logger.debug("语义缓存命中: question=%s...", question[:30])
    return {"answer": item.answer, "citations": json.loads(item.citations_json or "[]")}


async def store_cache(
    db: AsyncSession,
    question: str,
    answer: str,
    citations: list[dict],
    kb_id: int | None,
    language: str | None = None,
) -> None:
    """写入语义缓存(问题向量 + 回答 + 引用 + 回答语言)。"""
    s = get_settings()
    if not s.cache_enabled:
        return
    item = CacheItem(
        question=question,
        kb_fingerprint=await get_fingerprint(db, kb_id),
        answer=answer,
        citations_json=json.dumps(citations, ensure_ascii=False),
    )
    db.add(item)
    await db.flush()
    q_vector = await provider.embed_one(question)
    # 注意:qdrant 字符串 point id 必须为 UUID 格式,业务整数 id 直接以 int 存储
    payload: dict = {"question": question[:100], "language": language}
    if kb_id is not None:
        payload["kb_id"] = kb_id
    vector_store.upsert_cache_point(item.id, q_vector, payload)
    await db.commit()
    logger.debug("语义缓存已写入: id=%s", item.id)
