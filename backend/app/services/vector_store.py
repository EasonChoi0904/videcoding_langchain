"""Qdrant 向量库封装(嵌入式本地模式)。

用 qdrant-client 的本地模式(path=...):不启动独立服务进程,数据直接落在
data/qdrant 目录,API 与生产环境 Qdrant Server 完全一致 —— 论文可写
"开发/答辩单机零运维,部署时仅需改连接串即可切到服务版"。

集合设计:
- product_chunks:商品分块向量。向量 id = chunks 表 uuid;payload 携带
  kb_id / doc_id / seq,用于"按知识库过滤检索"与"按文档删除"。
- question_cache:语义缓存。向量 id = cache_items 主键;命中规则在 rag/cache.py。
"""
import logging
from functools import lru_cache
from typing import Any

from qdrant_client import QdrantClient, models as qm

from app.core.settings import get_settings

logger = logging.getLogger(__name__)

# 单次批量写入的点数(配合 HNSW 索引写入效率)
UPSERT_BATCH_SIZE = 64


@lru_cache
def get_client() -> QdrantClient:
    """进程级单例:本地嵌入式模式,数据落在 settings.qdrant_path。"""
    s = get_settings()
    s.qdrant_path.mkdir(parents=True, exist_ok=True)
    logger.info("Qdrant 本地模式启动,数据目录: %s", s.qdrant_path)
    return QdrantClient(path=str(s.qdrant_path), timeout=30)


def ensure_collections() -> None:
    """启动时确保两个集合存在(幂等);维度必须与 embedding 模型输出一致。"""
    s = get_settings()
    client = get_client()
    for name in (s.vector_collection, s.cache_collection):
        if not client.collection_exists(name):
            client.create_collection(
                collection_name=name,
                vectors_config=qm.VectorParams(
                    size=s.vector_size,
                    distance=qm.Distance.COSINE,
                ),
                hnsw_config=qm.HnswConfigDiff(m=16, ef_construct=128),
            )
            logger.info("已创建向量集合: %s(维度 %d)", name, s.vector_size)


# ==================== 商品分块写入 / 删除 ====================
def upsert_chunks(points: list[tuple[str, list[float], dict[str, Any]]]) -> None:
    """批量写入分块向量。

    Args:
        points: [(chunk_uuid, vector, payload), ...],payload 必含 kb_id/doc_id。
    """
    s = get_settings()
    client = get_client()
    batch: list[qm.PointStruct] = []
    for pid, vector, payload in points:
        batch.append(qm.PointStruct(id=pid, vector=vector, payload=payload))
        if len(batch) >= UPSERT_BATCH_SIZE:
            client.upsert(s.vector_collection, batch)
            batch.clear()
    if batch:
        client.upsert(s.vector_collection, batch)


def delete_points_by_document(doc_id: int) -> None:
    """删除某文档的全部向量(配合文档覆盖/删除)。"""
    s = get_settings()
    get_client().delete(
        s.vector_collection,
        points_selector=qm.FilterSelector(
            filter=qm.Filter(must=[qm.FieldCondition(key="doc_id", match=qm.MatchValue(value=doc_id))])
        ),
    )


def delete_points_by_kb(kb_id: int) -> None:
    """删除某知识库的全部向量(配合知识库删除)。"""
    s = get_settings()
    get_client().delete(
        s.vector_collection,
        points_selector=qm.FilterSelector(
            filter=qm.Filter(must=[qm.FieldCondition(key="kb_id", match=qm.MatchValue(value=kb_id))])
        ),
    )


def delete_point(point_id: str) -> None:
    """删除单个分块向量(管理端 chunk 级删除)。"""
    get_client().delete(collection_name=get_settings().vector_collection, points_selector=[point_id])


def search_dense(
    vector: list[float], top_k: int, kb_id: int | None = None, offset: int = 0
) -> list[dict[str, Any]]:
    """余弦近邻检索。

    Returns:
        [{chunk_id, score, kb_id, doc_id, seq}, ...] 按分数降序。
    """
    s = get_settings()
    filter_ = None
    if kb_id is not None:
        filter_ = qm.Filter(must=[qm.FieldCondition(key="kb_id", match=qm.MatchValue(value=kb_id))])
    # qdrant-client ≥1.10 起检索统一走 query_points API
    resp = get_client().query_points(
        collection_name=s.vector_collection,
        query=vector,
        query_filter=filter_,
        limit=top_k,
        offset=offset,
        with_payload=True,
    )
    return [
        {
            "chunk_id": h.id,
            "score": h.score,
            "kb_id": h.payload.get("kb_id"),
            "doc_id": h.payload.get("doc_id"),
            "seq": h.payload.get("seq"),
        }
        for h in resp.points
    ]


# ==================== 语义缓存(question_cache)====================
def search_cache(vector: list[float], top_k: int = 1) -> list[dict[str, Any]]:
    """在缓存集合中找最相似的历史问题。"""
    s = get_settings()
    resp = get_client().query_points(
        collection_name=s.cache_collection,
        query=vector,
        limit=top_k,
        with_payload=True,
    )
    return [{"cache_id": h.id, "score": h.score, **h.payload} for h in resp.points]


def upsert_cache_point(point_id: int, vector: list[float], payload: dict[str, Any]) -> None:
    """写入一条缓存问题向量(point id 用业务整数主键)。"""
    get_client().upsert(
        get_settings().cache_collection,
        [qm.PointStruct(id=point_id, vector=vector, payload=payload)],
    )


def delete_cache_point(point_id: int) -> None:
    """删除一条缓存。"""
    get_client().delete(
        collection_name=get_settings().cache_collection, points_selector=[point_id]
    )


def clear_cache_collection() -> None:
    """清空语义缓存(知识库内容变更后调用,保证缓存不会命中过期答案)。"""
    s = get_settings()
    client = get_client()
    client.delete_collection(s.cache_collection)
    client.create_collection(
        collection_name=s.cache_collection,
        vectors_config=qm.VectorParams(size=s.vector_size, distance=qm.Distance.COSINE),
    )
