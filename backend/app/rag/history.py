"""长会话管理:历史窗口 + 后台摘要压缩。

设计:提示词只携带"最近 N 轮 + 早期摘要",早期消息在后台由 LLM 压缩成
结构化要点存入 conversations.summary_text。效果:
- 上下文不随轮数无限膨胀(稳定延迟与成本)
- 早期关键信息(用户偏好、已确认的商品范围)不会因窗口裁剪而丢失

触发:每次问答完成后检查;压缩在后台任务执行,不阻塞回答。
"""
import asyncio
import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.settings import get_settings
from app.models import Conversation, Message
from app.rag.provider import make_chat_model

logger = logging.getLogger(__name__)

# 提示词携带的最近轮数(一问一答为一轮)
RECENT_ROUNDS = 10
# 窗口外累计超过该条数才触发一次压缩
COMPRESS_MIN_EXTRA = 8
# 单条消息进入摘要时的截断长度(压缩原料过长会吃掉摘要收益)
_SRC_MSG_CAP = 240


def _render_lines(messages: list[Message]) -> list[str]:
    """历史消息 → 可送 LLM 压缩的文本行。"""
    lines = []
    for m in messages:
        role = "用户" if m.role == "user" else "客服"
        content = (m.content or "").replace("\n", " ")[:_SRC_MSG_CAP]
        if content.strip():
            lines.append(f"{role}: {content}")
    return lines


async def maybe_compress(db: AsyncSession, conv_id: int) -> None:
    """检查会话是否需要压缩:窗口外消息足够多时执行一次压缩。"""
    s = get_settings()
    conv = await db.get(Conversation, conv_id)
    if conv is None:
        return

    messages = (
        await db.scalars(
            select(Message)
            .where(Message.conversation_id == conv_id, Message.is_streaming.is_(False))
            .order_by(Message.created_at.asc(), Message.id.asc())
        )
    ).all()
    # 保留窗口内 RECENT_ROUNDS 轮,窗口外的旧消息是压缩对象
    keep = RECENT_ROUNDS * 2
    prefix = messages[:-keep] if len(messages) > keep else []
    if len(prefix) < COMPRESS_MIN_EXTRA:
        return

    lines = _render_lines(prefix)
    if not lines:
        return
    old_summary = conv.summary_text or ""

    # 压缩请求在独立任务中执行(单次摘要调用,失败只影响摘要不阻塞)
    try:
        summary = await asyncio.wait_for(_summarize(lines, old_summary), timeout=60)
    except Exception as e:  # noqa: BLE001
        logger.warning("会话摘要压缩失败(conv=%s): %s", conv_id, e)
        return
    conv.summary_text = summary
    await db.commit()
    logger.info("会话 %s 历史已压缩:%d 条消息 → 摘要(窗口外保留 %d 轮)", conv_id, len(prefix), RECENT_ROUNDS)


async def _summarize(lines: list[str], old_summary: str) -> str:
    """把早期消息压缩成要点式摘要(供后续轮次的提示词携带)。"""
    llm = make_chat_model(streaming=False, temperature=0.2)
    parts = [
        "你是会话摘要引擎。下面是某电商客服会话的早期消息(用户/客服交替)以及更早的摘要。",
        "请提炼为简洁的中文要点式摘要(300 字内),保留:用户已询问/已确认的商品范围、"
        "关键事实、用户的诉求与情绪;不要保留寒暄与重复内容;不要臆造。",
    ]
    if old_summary:
        parts.append(f"【已有摘要】\n{old_summary}")
    parts.append(f"【本次消息】\n" + "\n".join(lines[-80:]))  # 原料再封顶 80 行
    resp = await llm.ainvoke("\n\n".join(parts))
    return (resp.content or "").strip()[:2000]


async def schedule_compress(conv_id: int) -> None:
    """问答完成后调度一次后台压缩检查(不等待结果)。"""
    try:
        from app.db import async_session_maker

        async def _run() -> None:
            async with async_session_maker() as db:
                await maybe_compress(db, conv_id)

        asyncio.create_task(_run())
    except Exception as e:  # noqa: BLE001
        logger.debug("压缩任务调度失败(忽略): %s", e)
