"""管理统计看板接口(仅管理员):系统规模 + 问答运营数据。"""
from datetime import date, timedelta

from fastapi import APIRouter, Depends
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import require_admin
from app.db import get_db
from app.models import (
    Chunk,
    Conversation,
    Document,
    Feedback,
    KnowledgeBase,
    Message,
    User,
)

router = APIRouter(prefix="/admin/stats", tags=["统计看板(管理员)"], dependencies=[Depends(require_admin)])


@router.get("", summary="系统统计总览")
async def get_stats(db: AsyncSession = Depends(get_db)):
    def count(model):
        return (
            db.scalar(select(func.count()).select_from(model))
        ) or 0

    total_users = await count(User)
    total_kbs = await count(KnowledgeBase)
    total_docs = await count(Document)
    total_chunks = await count(Chunk)
    total_convs = await count(Conversation)
    total_msgs = await count(Message)

    # 近 7 天问答消息量(按天聚合,SQLite date() 处理本地时间)
    today = date.today()
    rows = (
        await db.execute(
            text(
                """
                SELECT date(created_at) AS d, COUNT(*) AS c
                FROM messages
                WHERE created_at >= :start
                GROUP BY date(created_at)
                """
            ),
            {"start": today - timedelta(days=6)},
        )
    ).all()
    by_day = {str(r[0]): r[1] for r in rows}
    trend = [
        {"date": str(today - timedelta(days=i)), "count": by_day.get(str(today - timedelta(days=i)), 0)}
        for i in range(6, -1, -1)
    ]

    # 平均生成耗时(ms,取有记录的助手消息)
    avg_latency = await db.scalar(
        select(func.avg(Message.latency_ms)).where(Message.latency_ms.is_not(None))
    )
    # 模型用量(按 model 分组计数)
    usage_rows = (
        await db.execute(
            text(
                "SELECT COALESCE(model, 'N/A') AS m, COUNT(*) AS c FROM messages "
                "WHERE role='assistant' GROUP BY model"
            )
        )
    ).all()
    model_usage = [{"model": m, "count": c} for m, c in usage_rows]

    # 用户反馈统计
    likes = await db.scalar(select(func.count()).select_from(Feedback).where(Feedback.value == 1)) or 0
    dislikes = await db.scalar(select(func.count()).select_from(Feedback).where(Feedback.value == -1)) or 0

    # 知识库分布(按 chunk 数排序)
    kb_dist = (
        await db.execute(
            text(
                "SELECT k.name, k.chunk_count FROM knowledge_bases k ORDER BY k.chunk_count DESC LIMIT 10"
            )
        )
    ).all()

    return {
        "totals": {
            "users": total_users,
            "kbs": total_kbs,
            "docs": total_docs,
            "chunks": total_chunks,
            "conversations": total_convs,
            "messages": total_msgs,
        },
        "trend_7d": trend,
        "avg_latency_ms": round(avg_latency) if avg_latency else None,
        "model_usage": model_usage,
        "feedback": {"likes": likes, "dislikes": dislikes, "total": likes + dislikes},
        "kb_dist": [{"name": name, "chunks": n} for name, n in kb_dist],
    }
