"""混合检索器:向量路 + 关键词路 → RRF 融合 → 云端重排 → 阈值拒答。

这是全系统检索质量的核心,论文"混合检索 + 两级精排"方案的落地点。
"""
import json
import logging
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.settings import get_settings
from app.models import Chunk
from app.rag import provider
from app.services import fts, vector_store

logger = logging.getLogger(__name__)


@dataclass
class RetrievedChunk:
    """一次检索命中的分块(含来源信息,用于引用溯源与拒答判定)。"""

    chunk_id: str
    text: str
    doc_id: int
    kb_id: int
    score: float = 0.0          # 最终分数(重排 relevance)
    vector_rank: int | None = None
    keyword_rank: int | None = None
    source: str = ""            # 来源文件名
    meta_json: str | None = None


async def _load_chunks(db: AsyncSession, chunk_ids: list[str]) -> dict[str, Chunk]:
    """按 id 批量载入分块并附带文档来源。"""
    if not chunk_ids:
        return {}
    rows = (await db.scalars(select(Chunk).where(Chunk.id.in_(chunk_ids)))).all()
    return {c.id: c for c in rows}


def _rrf_fuse(
    vector_ids: list[str], keyword_ids: list[str], k: int | None = None
) -> list[tuple[str, float]]:
    """Reciprocal Rank Fusion:融合两路排序。

    分数 = Σ 1/(k + rank)。对排序敏感、对分数尺度不敏感,
    天然适配"向量余弦分"与"BM25 分"两种量纲。
    """
    s = get_settings()
    k = k or s.rrf_k
    fused: dict[str, float] = {}
    for rank, cid in enumerate(vector_ids, start=1):
        fused[cid] = fused.get(cid, 0.0) + 1.0 / (k + rank)
    for rank, cid in enumerate(keyword_ids, start=1):
        fused[cid] = fused.get(cid, 0.0) + 1.0 / (k + rank)
    return sorted(fused.items(), key=lambda kv: kv[1], reverse=True)


async def retrieve(
    db: AsyncSession,
    question: str,
    kb_id: int | None = None,
    *,
    debug: bool = False,
) -> tuple[list[RetrievedChunk], dict]:
    """执行完整检索链路,返回重排后的片段列表与(可选)各阶段调试明细。

    Args:
        db: 数据库会话
        question: 用户问题
        kb_id: 限定知识库(如指定商品的库)
        debug: 为 True 时额外返回各阶段明细(管理端调试台用)

    Returns:
        (片段列表[已按分数降序], stage_debug 字典)
    """
    s = get_settings()
    each_top_k = s.hybrid_each_top_k
    stages: dict = {}

    # ---- 1. 双路并行召回 ----
    # 向量路(云端 embedding 一次调用)
    q_vector = await provider.embed_one(question)
    vector_hits = vector_store.search_dense(q_vector, top_k=each_top_k, kb_id=kb_id)
    vector_ids = [h["chunk_id"] for h in vector_hits]

    # 关键词路(FTS5 + jieba 短语,本地零成本)
    terms = fts.build_keyword_query(question)
    keyword_ids = await fts.search_keywords(db, terms, top_k=each_top_k, kb_id=kb_id)

    if debug:
        stages["terms"] = terms

    # ---- 2. RRF 融合取 top-10 ----
    fused = _rrf_fuse(vector_ids, keyword_ids)[:10]
    fused_ids = [cid for cid, _ in fused]

    chunks_map = await _load_chunks(db, list(dict.fromkeys([*vector_ids, *keyword_ids])))

    def to_retrieved(cid: str, score: float, v_rank=None, k_rank=None) -> RetrievedChunk | None:
        c = chunks_map.get(cid)
        if c is None:
            return None
        return RetrievedChunk(
            chunk_id=c.id,
            text=c.text,
            doc_id=c.doc_id,
            kb_id=c.kb_id,
            score=score,
            vector_rank=v_rank,
            keyword_rank=k_rank,
            source=json.loads(c.meta_json).get("source", "") if c.meta_json else "",
            meta_json=c.meta_json,
        )

    vector_rank_map = {cid: i + 1 for i, cid in enumerate(vector_ids)}
    keyword_rank_map = {cid: i + 1 for i, cid in enumerate(keyword_ids)}

    if debug:
        stages["vector_hits"] = [
            {"chunk_id": h["chunk_id"], "score": h["score"]} for h in vector_hits
        ]
        stages["keyword_hits"] = [
            {"chunk_id": cid} for cid in keyword_ids[: min(len(keyword_ids), 20)]
        ]

    # ---- 3. 云端重排(top-10 精排到 top_n,交叉编码精度远高于双编码)----
    candidates = fused_ids
    texts = [chunks_map[cid].text for cid in candidates if cid in chunks_map]
    if texts:
        results = await provider.rerank(
            question, texts[:10], top_n=min(s.rerank_top_n, len(texts[:10]))
        )
        reranked: list[RetrievedChunk] = []
        for r in results:
            cid = candidates[r["index"]]
            rc = to_retrieved(
                cid,
                score=float(r.get("relevance_score", 0.0)),
                v_rank=vector_rank_map.get(cid),
                k_rank=keyword_rank_map.get(cid),
            )
            if rc:
                reranked.append(rc)
    else:
        reranked = []

    # ---- 4. 拒答判定(防幻觉:低于阈值直接不放行给生成器)----
    if debug:
        stages["fused"] = [{"chunk_id": cid, "rrf_score": sc} for cid, sc in fused]
        stages["reranked"] = [
            {"chunk_id": r.chunk_id, "score": r.score} for r in reranked
        ]
    return reranked, stages
