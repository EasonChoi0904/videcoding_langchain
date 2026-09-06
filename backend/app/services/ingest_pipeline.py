"""单文档解析入库管道(由 ingestion worker 调用)。

流程:读原文件 → 按格式解析 → 分块 → 批量向量化(百炼)→ 写 Qdrant
→ 落 SQLite 分块行 + FTS 索引,按批提交让前端能看到实时进度。
任一步失败:文档标记 failed,已写入的部分分块被清理(不留脏数据)。
"""
import json
import logging
import uuid
from datetime import datetime

from app.core.settings import get_settings
from app.db import async_session_maker
from app.models import Chunk, Document, KnowledgeBase
from app.models.sql import INSERT_FTS
from app.rag import provider
from app.rag.splitter import clean_text, parse_document, split_pieces
from app.services import vector_store
from app.services.document_ops import mark_kb_changed

logger = logging.getLogger(__name__)


async def run_ingest_pipeline(doc_id: int) -> None:
    """解析入库一篇文档(幂等入口:状态不对直接返回)。"""
    s = get_settings()

    async with async_session_maker() as db:
        doc = await db.get(Document, doc_id)
        if doc is None or doc.parse_status == "parsing":
            return
        doc.parse_status = "parsing"
        doc.progress_done = 0
        doc.progress_total = 0
        doc.error_msg = None
        await db.commit()
        kb = await db.get(KnowledgeBase, doc.kb_id)
        if kb is None:
            doc.parse_status = "failed"
            doc.error_msg = "所属知识库不存在"
            await db.commit()
            return

    file_path = s.upload_dir / doc.file_path
    try:
        # ---- 1. 解析 + 分块(纯本地,不产生费用)----
        pieces = parse_document(doc.file_type, file_path)
        splits = split_pieces(pieces)
        texts = [clean_text(t) for t, _, _ in splits if t.strip()]
        total = len(texts)
        logger.info("文档[%s]解析完成: %d 个分块,开始向量化", doc.filename, total)
        if total == 0:
            async with async_session_maker() as db:
                doc = await db.get(Document, doc_id)
                doc.parse_status = "done"
                doc.chunk_count = 0
                doc.finished_at = datetime.now()
                await db.commit()
            return

        # ---- 2. 分批向量化 + 写 Qdrant + 落库(每批提交一次,进度实时可见)----
        done = 0
        for start in range(0, total, s.embedding_batch_size):
            batch_texts = texts[start : start + s.embedding_batch_size]
            vectors = await provider.embed_texts(batch_texts)

            points: list[tuple[str, list[float], dict]] = []
            rows: list[Chunk] = []
            async with async_session_maker() as db:
                for i, (text, meta, seq) in enumerate(splits[start : start + s.embedding_batch_size]):
                    if not text.strip():
                        continue
                    chunk_id = str(uuid.uuid4())
                    meta_full = {"source": doc.filename, **meta}
                    points.append(
                        (chunk_id, vectors[i], {"kb_id": doc.kb_id, "doc_id": doc_id, "seq": seq})
                    )
                    rows.append(
                        Chunk(
                            id=chunk_id,
                            doc_id=doc_id,
                            kb_id=doc.kb_id,
                            seq=seq,
                            text=text,
                            meta_json=json.dumps(meta_full, ensure_ascii=False),
                        )
                    )
                if points:
                    vector_store.upsert_chunks(points)  # 先向量成功,再落业务行
                db.add_all(rows)
                # FTS 索引逐条写入(与分块行同事务)
                for r in rows:
                    await db.execute(INSERT_FTS, {"chunk_id": r.id, "text": r.text})
                doc = await db.get(Document, doc_id)
                doc.progress_done = done + len(points)
                doc.progress_total = total
                await db.commit()
            done += len(points)

        # ---- 3. 完成:状态 + 统计 + 语义缓存失效 ----
        async with async_session_maker() as db:
            doc = await db.get(Document, doc_id)
            doc.parse_status = "done"
            doc.chunk_count = done
            doc.finished_at = datetime.now()
            await mark_kb_changed(db, doc.kb_id)
            await db.commit()
        logger.info("文档[%s]入库完成: %d 个分块", doc.filename, done)

    except provider.ProviderNotReady as e:
        await _mark_failed(doc_id, f"AI 服务未就绪:{e}", doc.filename)
    except Exception as e:  # noqa: BLE001 单文档失败不阻断 worker
        logger.exception("文档[%s]入库失败", doc.filename)
        await _mark_failed(doc_id, str(e)[:500], doc.filename)
        await _cleanup_partial(doc_id)


async def _mark_failed(doc_id: int, message: str, filename: str) -> None:
    """标记解析失败(保留已入部分由 _cleanup_partial 清理)。"""
    logger.warning("文档[%s]解析失败: %s", filename, message[:200])
    async with async_session_maker() as db:
        doc = await db.get(Document, doc_id)
        if doc:
            doc.parse_status = "failed"
            doc.error_msg = message
            await db.commit()


async def _cleanup_partial(doc_id: int) -> None:
    """解析中途失败时,清理该文档已写入的向量与分块(不留半截数据)。"""
    from app.services.document_ops import _recount_kb
    from sqlalchemy import select

    vector_store.delete_points_by_document(doc_id)
    async with async_session_maker() as db:
        chunk_ids = (
            await db.scalars(select(Chunk.id).where(Chunk.doc_id == doc_id))
        ).all()
        from app.models.sql import DELETE_FTS

        for cid in chunk_ids:
            await db.execute(DELETE_FTS, {"chunk_id": cid})
        await db.execute(Chunk.__table__.delete().where(Chunk.doc_id == doc_id))
        doc = await db.get(Document, doc_id)
        if doc:
            await _recount_kb(db, doc.kb_id)
        await db.commit()
