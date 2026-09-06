"""分块浏览/搜索/删除接口(仅管理员)。

搜索走 FTS5 关键词索引(与管理端"看库里有什么"诉求匹配);
分页基于搜索命中的排序结果,保证翻页顺序稳定。
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import require_admin
from app.db import get_db
from app.models import Chunk, Document, KnowledgeBase
from app.schemas.common import Page
from app.schemas.kb import ChunkOut
from app.services import fts, vector_store
from app.services.document_ops import _recount_kb

router = APIRouter(prefix="/chunks", tags=["分块(管理员)"], dependencies=[Depends(require_admin)])


async def _get_kb_or_404(db: AsyncSession, kb_id: int) -> KnowledgeBase:
    kb = await db.get(KnowledgeBase, kb_id)
    if kb is None:
        raise HTTPException(status_code=404, detail="知识库不存在")
    return kb


@router.get("/kb/{kb_id}", response_model=Page[ChunkOut], summary="分块列表(支持关键词搜索)")
async def list_chunks(
    kb_id: int,
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    q: str | None = Query(None, description="关键词(走 FTS 全文检索)"),
    db: AsyncSession = Depends(get_db),
):
    await _get_kb_or_404(db, kb_id)

    if q and q.strip():
        # ---- 搜索模式:FTS 命中排序 → 在该顺序上分页 ----
        terms = fts.build_keyword_query(q.strip())
        if not terms:
            # 查询太短(如 1-2 字)无法走 trigram,回退为普通包含查询
            stmt = select(Chunk).where(Chunk.kb_id == kb_id, Chunk.text.contains(q.strip()))
            total = await db.scalar(
                select(func.count()).select_from(Chunk).where(
                    Chunk.kb_id == kb_id, Chunk.text.contains(q.strip())
                )
            )
            rows = (
                await db.scalars(
                    stmt.order_by(Chunk.created_at.desc())
                    .offset((page - 1) * size)
                    .limit(size)
                )
            ).all()
            return Page(items=rows, total=total or 0)

        hit_ids = await fts.search_keywords(db, terms, top_k=1000, kb_id=kb_id)
        total = len(hit_ids)
        slice_ids = hit_ids[(page - 1) * size : page * size]
        if not slice_ids:
            return Page(items=[], total=total)
        rows = (await db.scalars(select(Chunk).where(Chunk.id.in_(slice_ids)))).all()
        # 按命中排序还原顺序(数据库 in 查询不保证顺序)
        order_map = {cid: i for i, cid in enumerate(slice_ids)}
        rows = sorted(rows, key=lambda c: order_map[c.id])
        return Page(items=rows, total=total)

    # ---- 浏览模式:按时间倒序分页 ----
    total = await db.scalar(
        select(func.count()).select_from(Chunk).where(Chunk.kb_id == kb_id)
    )
    rows = (
        await db.scalars(
            select(Chunk)
            .where(Chunk.kb_id == kb_id)
            .order_by(Chunk.created_at.desc())
            .offset((page - 1) * size)
            .limit(size)
        )
    ).all()
    return Page(items=rows, total=total or 0)


@router.delete("/{chunk_id}", summary="删除单个分块(向量/索引同步清理)")
async def remove_chunk(chunk_id: str, db: AsyncSession = Depends(get_db)):
    chunk = await db.get(Chunk, chunk_id)
    if chunk is None:
        raise HTTPException(status_code=404, detail="分块不存在")
    kb_id = chunk.kb_id
    vector_store.delete_point(chunk.id)
    await fts.delete_fts(db, chunk.id)
    await db.delete(chunk)
    await _recount_kb(db, kb_id)
    await db.commit()
    return {"message": "分块已删除"}
