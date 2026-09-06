"""会话与消息管理接口(本人会话隔离):
创建/列表(带预览)/改名/切语言/删除/消息分页/搜索/导出。
"""
import json
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import bindparam, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user
from app.db import get_db
from app.models import Conversation, Feedback, Message, User
from app.schemas.chat import (
    ConversationCreate,
    ConversationOut,
    ConversationUpdate,
    FeedbackRequest,
    MessageOut,
)

router = APIRouter(tags=["会话"])


async def _get_own_conv(db: AsyncSession, conv_id: int, user: User) -> Conversation:
    """取会话并校验归属(会话数据严格按用户隔离)。"""
    conv = await db.get(Conversation, conv_id)
    if conv is None or conv.user_id != user.id:
        raise HTTPException(status_code=404, detail="会话不存在")
    return conv


async def _count_messages(db: AsyncSession, conv_id: int) -> int:
    return (
        await db.scalar(select(func.count()).select_from(Message).where(Message.conversation_id == conv_id))
    ) or 0


def _msg_to_out(m: Message) -> MessageOut:
    """Message → MessageOut(把 citations_json 反序列化为列表)。

    约定:completed 消息 citations 为 [] 或列表;NULL(从未写入)= 生成中断
    的半截消息,前端据此展示"回答中断,可重新生成"。
    """
    return MessageOut(
        id=m.id,
        role=m.role,
        content=m.content,
        citations=json.loads(m.citations_json) if m.citations_json is not None else None,
        is_streaming=m.is_streaming,
        latency_ms=m.latency_ms,
        model=m.model,
        created_at=m.created_at,
    )


# ==================== 会话 ====================
@router.post("/conversations", response_model=ConversationOut, summary="创建会话")
async def create_conversation(
    body: ConversationCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    conv = Conversation(
        user_id=user.id,
        title=body.title or "新会话",
        language=body.language,
    )
    db.add(conv)
    await db.commit()
    await db.refresh(conv)
    return conv


@router.get("/conversations", response_model=list[ConversationOut], summary="我的会话列表(按活跃度排序,含最后消息预览)")
async def list_conversations(db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    convs = (
        await db.scalars(
            select(Conversation)
            .where(Conversation.user_id == user.id)
            .order_by(Conversation.last_active_at.desc(), Conversation.id.desc())
        )
    ).all()
    if not convs:
        return []

    # 批量取每个会话的最后一条消息作预览(窗口函数,一次查询避免 N+1)
    conv_ids = [c.id for c in convs]
    sql = text(
        """
        WITH ranked AS (
            SELECT id, conversation_id, content,
                   ROW_NUMBER() OVER (
                       PARTITION BY conversation_id
                       ORDER BY created_at DESC, id DESC
                   ) AS rn
            FROM messages
            WHERE conversation_id IN :ids
        )
        SELECT conversation_id, content FROM ranked WHERE rn = 1
        """
    ).bindparams(bindparam("ids", expanding=True))
    rows = await db.execute(sql, {"ids": conv_ids})
    preview_map = {r[0]: (r[1] or "") for r in rows.fetchall()}

    out = []
    for c in convs:
        item = ConversationOut.model_validate(c, from_attributes=True)
        preview = preview_map.get(c.id)
        item.preview = (preview[:60] + "…") if preview and len(preview) > 60 else preview
        out.append(item)
    return out


@router.get("/conversations/search", summary="搜索会话(按标题或消息内容)")
async def search_conversations(
    q: str = Query(..., min_length=1, max_length=100),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    like = f"%{q.strip()}%"
    sql = text(
        """
        SELECT DISTINCT c.* FROM conversations c
        LEFT JOIN messages m ON m.conversation_id = c.id
        WHERE c.user_id = :uid AND (c.title LIKE :like OR m.content LIKE :like)
        ORDER BY c.last_active_at DESC
        """
    )
    rows = (await db.execute(sql, {"uid": user.id, "like": like})).mappings().all()
    result = []
    for r in rows:
        result.append(
            ConversationOut(
                id=r["id"], title=r["title"], language=r["language"],
                summary_text=r["summary_text"], message_count=r["message_count"],
                last_active_at=r["last_active_at"], created_at=r["created_at"],
                updated_at=r["updated_at"], preview=None,
            )
        )
    return result


@router.patch("/conversations/{conv_id}", response_model=ConversationOut, summary="修改会话(标题/回答语言)")
async def update_conversation(
    conv_id: int,
    body: ConversationUpdate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    conv = await _get_own_conv(db, conv_id, user)
    if body.title is not None:
        conv.title = body.title.strip() or "新会话"
    if body.language is not None:
        conv.language = body.language
    await db.commit()
    await db.refresh(conv)
    return conv


@router.delete("/conversations/{conv_id}", summary="删除会话(含全部消息)")
async def delete_conversation(
    conv_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    conv = await _get_own_conv(db, conv_id, user)
    await db.delete(conv)  # 消息由外键级联清理
    await db.commit()
    return {"message": "会话已删除"}


# ==================== 消息 ====================
@router.get("/conversations/{conv_id}/messages", summary="会话消息(keyset 游标分页,返回时间正序)")
async def list_messages(
    conv_id: int,
    cursor: str | None = Query(None, description="上一页末尾的 created_at,id,如 2026-09-05T19:00:00,abc-uuid"),
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    await _get_own_conv(db, conv_id, user)
    stmt = select(Message).where(Message.conversation_id == conv_id)
    if cursor:
        try:
            ts_raw, mid = cursor.rsplit(",", 1)
            cursor_ts = datetime.fromisoformat(ts_raw)
        except ValueError:
            raise HTTPException(status_code=400, detail="游标格式错误") from None
        # keyset:(created_at, id) 字典序比游标小 → 更早的消息
        stmt = stmt.where(
            (Message.created_at < cursor_ts)
            | ((Message.created_at == cursor_ts) & (Message.id < mid))
        )
    rows = (
        await db.scalars(
            stmt.order_by(Message.created_at.desc(), Message.id.desc()).limit(limit + 1)
        )
    ).all()
    has_more = len(rows) > limit
    page = list(rows[:limit])
    page.reverse()  # 时间正序返回,前端直接追加渲染

    items = [_msg_to_out(m) for m in page]
    next_cursor = None
    if has_more and page:
        last = page[-1]
        next_cursor = f"{last.created_at.isoformat()},{last.id}"
    return {"items": items, "next_cursor": next_cursor}


@router.post("/messages/{message_id}/feedback", summary="消息反馈(点赞/点踩,重复提交即覆盖)")
async def submit_feedback(
    message_id: str,
    body: FeedbackRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    msg = await db.get(Message, message_id)
    if msg is None or msg.user_id != user.id:
        raise HTTPException(status_code=404, detail="消息不存在")
    if msg.role != "assistant":
        raise HTTPException(status_code=400, detail="仅可对客服回答反馈")

    fb = await db.scalar(select(Feedback).where(Feedback.message_id == message_id))
    if fb is None:
        fb = Feedback(message_id=message_id, user_id=user.id)
        db.add(fb)
    fb.value = body.value
    fb.comment = body.comment
    await db.commit()
    return {"message": "感谢您的反馈", "value": fb.value}


# ==================== 导出 ====================
@router.get("/conversations/{conv_id}/export", summary="导出会话为 Markdown")
async def export_conversation(
    conv_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    conv = await _get_own_conv(db, conv_id, user)
    msgs = (
        await db.scalars(
            select(Message)
            .where(Message.conversation_id == conv_id)
            .order_by(Message.created_at.asc(), Message.id.asc())
        )
    ).all()

    lines = [f"# 会话:{conv.title}", f"- 创建时间:{conv.created_at:%Y-%m-%d %H:%M}", ""]
    for m in msgs:
        if m.role == "user":
            lines += [f"## 用户提问({m.created_at:%H:%M})", m.content, ""]
        else:
            lines += [f"## 客服回答({m.created_at:%H:%M})", m.content, ""]
            if m.citations_json:
                cites = json.loads(m.citations_json)
                lines.append("> 引用来源:")
                for c in cites:
                    lines.append(f"> - 《{c.get('doc_name', '')}》{c.get('location', '')}")
                lines.append("")
    return {"filename": f"{conv.title}.md", "content": "\n".join(lines)}
