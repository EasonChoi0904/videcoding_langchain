"""检索调试台接口(仅管理员):一次调用展示检索全链路的每一级结果。

用于:调参(拒答阈值/召回数量)、排查"为什么答不上来"、
以及答辩现场演示混合检索与重排的效果差异。
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import require_admin
from app.core.settings import get_settings
from app.db import get_db
from app.models import Chunk, Setting
from app.rag.retriever import retrieve
from app.schemas.kb import DebugHit, DebugSearchRequest, DebugSearchResult

router = APIRouter(
    prefix="/debug", tags=["检索调试(管理员)"], dependencies=[Depends(require_admin)]
)

# 片段文本预览长度(调试台无需全文)
_PREVIEW_LEN = 200


async def _get_db_setting(db: AsyncSession, key: str, default: str) -> str:
    """读取运行时配置:DB settings 表优先(管理员可动态改),否则回退默认值。"""
    row = await db.get(Setting, key)
    return row.value if row else default


@router.post("/search", response_model=DebugSearchResult, summary="调试检索:输出各阶段明细")
async def debug_search(body: DebugSearchRequest, db: AsyncSession = Depends(get_db)):
    question = body.question.strip()
    if not question:
        raise HTTPException(status_code=400, detail="问题不能为空")

    # 读取管理端动态配置的拒答阈值(与正式问答链路同一来源)
    threshold = float(
        await _get_db_setting(db, "rerank_threshold", str(get_settings().rerank_threshold))
    )

    chunks, stages = await retrieve(db, question, body.kb_id, debug=True)

    # ---- 汇总所有阶段出现的 chunk_id,一次性取文本 ----
    all_ids: set[str] = set()
    for cid in [h["chunk_id"] for h in stages.get("vector_hits", [])]:
        all_ids.add(cid)
    for cid in [h["chunk_id"] for h in stages.get("keyword_hits", [])]:
        all_ids.add(cid)
    for cid in [h["chunk_id"] for h in stages.get("fused", [])]:
        all_ids.add(cid)
    for rc in chunks:
        all_ids.add(rc.chunk_id)
    texts: dict[str, str] = {}
    if all_ids:
        rows = (await db.scalars(select(Chunk).where(Chunk.id.in_(all_ids)))).all()
        texts = {c.id: c.text for c in rows}

    def build(cid: str, score: float) -> DebugHit:
        return DebugHit(chunk_id=cid, score=score, text=texts.get(cid, "")[:_PREVIEW_LEN])

    vector_hits = [build(h["chunk_id"], h["score"]) for h in stages.get("vector_hits", [])]
    keyword_hits = [build(h["chunk_id"], 0.0) for h in stages.get("keyword_hits", [])]
    fused_hits = [
        build(h["chunk_id"], h["rrf_score"]) for h in stages.get("fused", [])
    ]
    reranked_hits = [build(rc.chunk_id, rc.score) for rc in chunks]

    # 拒答判定:重排最高分低于阈值 → 系统拒答(防幻觉),与问答链路规则一致
    top_score = chunks[0].score if chunks else 0.0
    refused = not chunks or top_score < threshold

    return DebugSearchResult(
        vector_hits=vector_hits,
        keyword_hits=keyword_hits,
        fused_hits=fused_hits,
        reranked_hits=reranked_hits,
        refused=refused,
        threshold=threshold,
    )
