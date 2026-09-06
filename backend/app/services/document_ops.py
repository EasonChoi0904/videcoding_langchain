"""文档/知识库删除的共享清理逻辑(删除必须三处同步:Qdrant 向量 + SQLite/FTS + 磁盘文件)。"""
import logging
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.settings import get_settings
from app.models import Chunk, Document, KnowledgeBase
from app.services import fts, vector_store

logger = logging.getLogger(__name__)


async def _recount_kb(db: AsyncSession, kb_id: int) -> None:
    """重新统计知识库的文档数/分块数(删除或入库后保持展示数据准确)。"""
    kb = await db.get(KnowledgeBase, kb_id)
    if kb is None:
        return
    kb.doc_count = (
        await db.scalar(select(func.count()).select_from(Document).where(Document.kb_id == kb_id))
    ) or 0
    kb.chunk_count = (
        await db.scalar(select(func.count()).select_from(Chunk).where(Chunk.kb_id == kb_id))
    ) or 0


def remove_upload_file(file_path: str) -> None:
    """删除落盘的上传原文件(文件丢失不影响功能,忽略异常)。"""
    try:
        (get_settings().upload_dir / file_path).unlink(missing_ok=True)
    except Exception as e:  # noqa: BLE001
        logger.warning("删除上传文件失败 %s: %s", file_path, e)


async def clear_document_content(db: AsyncSession, doc: Document) -> None:
    """清空一篇文档的解析产物:向量、FTS、分块行;把状态复位为 pending。

    (保留文档行与磁盘原文件,供"重新解析"场景复用。)
    """
    vector_store.delete_points_by_document(doc.id)
    await fts.delete_fts_by_doc(db, doc.id)
    await db.execute(Chunk.__table__.delete().where(Chunk.doc_id == doc.id))
    doc.parse_status = "pending"
    doc.progress_done = 0
    doc.progress_total = 0
    doc.error_msg = None
    doc.chunk_count = 0
    doc.finished_at = None
    await db.flush()


async def delete_document(db: AsyncSession, doc: Document) -> None:
    """删除一篇文档的全部痕迹:向量、FTS、分块行、原文件,并刷新知识库统计。"""
    await clear_document_content(db, doc)
    # 磁盘原文件 + 文档行
    remove_upload_file(doc.file_path)
    kb_id = doc.kb_id
    await db.delete(doc)
    await _recount_kb(db, kb_id)
    # 知识库内容变了 → 语义缓存整体失效
    vector_store.clear_cache_collection()
    await db.commit()


async def delete_kb(db: AsyncSession, kb: KnowledgeBase) -> None:
    """删除整个知识库:先逐个清向量与文件,再让外键级联清空文档与分块。"""
    docs = (await db.scalars(select(Document).where(Document.kb_id == kb.id))).all()
    for doc in docs:
        vector_store.delete_points_by_document(doc.id)
        remove_upload_file(doc.file_path)
    await db.delete(kb)  # documents/chunks 由外键 ON DELETE CASCADE 级联清理
    await db.commit()
    # 语义缓存整体失效
    vector_store.clear_cache_collection()
    logger.info("知识库 %s 已删除(含 %d 篇文档的全部数据)", kb.name, len(docs))


async def mark_kb_changed(db: AsyncSession, kb_id: int) -> None:
    """入库成功后调用:刷新统计 + 清语义缓存。"""
    await _recount_kb(db, kb_id)
    vector_store.clear_cache_collection()
