"""问答接口(SSE 流式)—— 系统核心链路。

协议(事件流,顺序固定):
1. citations:检索完成的引用片段(正文 [n] 与之对应,面板即时展示)
2. token × N:生成正文增量
3. done:结束(含 refused 标记)
任意阶段出错 → error 事件,客户端可重试。

健壮性:
- 同一会话并发问答互斥(进程内锁),防止多轮上下文错乱
- 客户端中途断开 → CancelledError → 半截内容落库并标记 is_streaming,
  下次提问视为"重新生成",自动替换
- 全局限流(每用户每分钟)+ 全局并发信号量
"""
import asyncio
import json
import logging
import time
import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.rate_limit import limiter
from app.core.settings import get_settings
from app.db import async_session_maker
from app.models import Conversation, KnowledgeBase, Message, Setting, User
from app.rag import cache as semantic_cache
from app.rag import chain, provider, retriever
from app.schemas.chat import AskRequest

logger = logging.getLogger(__name__)
router = APIRouter(tags=["问答"])

# 同一会话的并发锁(防多轮上下文错乱)
_conversation_locks: dict[int, asyncio.Lock] = {}
_conversation_locks_guard = asyncio.Lock()
# 全局并发生成的信号量(防止瞬时打满百炼 QPS/本地带宽;并发上限可经 STREAM_CONCURRENCY 调整,默认 4)
_stream_semaphore = asyncio.Semaphore(get_settings().stream_concurrency)

# 内容落库周期:流式期间每隔该秒数把累积文本刷进数据库(断线少丢)
_FLUSH_INTERVAL = 1.0


async def _get_conv_lock(conv_id: int) -> asyncio.Lock:
    """取会话锁(进程内注册表,懒创建)。"""
    async with _conversation_locks_guard:
        if conv_id not in _conversation_locks:
            _conversation_locks[conv_id] = asyncio.Lock()
        return _conversation_locks[conv_id]


def sse(event: str, data: dict) -> str:
    """格式化一条 SSE 消息。"""
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


def _location_of(meta_json: str | None) -> str:
    """从分块元数据解析展示位置(页码/表格行)。"""
    if not meta_json:
        return ""
    try:
        meta = json.loads(meta_json)
    except (json.JSONDecodeError, TypeError):
        return ""
    if meta.get("page"):
        return f"第 {meta['page']} 页"
    if meta.get("row"):
        return f"表格第 {meta['row']} 行"
    return ""


async def _effective_settings(db: AsyncSession) -> dict:
    """运行时检索参数:DB settings 优先(管理端可调),默认值兜底。"""
    defaults = {
        "rerank_threshold": str(get_settings().rerank_threshold),
        "rerank_top_n": str(get_settings().rerank_top_n),
        "system_prompt": str(chain.DEFAULT_SYSTEM_PROMPT),
        "cache_enabled": "true",
    }
    for key in defaults:
        row = await db.get(Setting, key)
        if row:
            defaults[key] = row.value
    return defaults


async def _history_context(db: AsyncSession, conv_id: int, exclude_msg_id: str | None) -> tuple[str | None, list[dict]]:
    """取会话历史:早期摘要 + 近 N 轮消息(不含正在生成的这条)。"""
    s = get_settings()
    conv = await db.get(Conversation, conv_id)
    msgs = (
        await db.scalars(
            select(Message)
            .where(Message.conversation_id == conv_id)
            .order_by(Message.created_at.desc(), Message.id.desc())
            .limit(s.history_recent_rounds * 2 + 2)
        )
    ).all()
    history = [
        {"role": m.role, "content": m.content}
        for m in reversed(msgs)
        if m.id != exclude_msg_id and not m.is_streaming and m.content
    ]
    return (conv.summary_text if conv else None), history


@router.post("/chat/{conv_id}/ask")
async def ask(conv_id: int, body: AskRequest, request: Request):
    """发起问答:SSE 流式返回(引用 → 正文 → 完成)。"""
    s = get_settings()
    # 先做鉴权与会话归属校验(快速失败,不进流)
    from app.core.deps import get_current_user as _auth

    # FastAPI 无法在此处直接复用 Depends,手动鉴权
    auth_header = request.headers.get("authorization", "")
    if not auth_header.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="未登录")
    from app.core.security import decode_token

    payload = decode_token(auth_header[7:], expected_type="access")
    if payload is None:
        raise HTTPException(status_code=401, detail="令牌无效或已过期")
    from app.db import async_session_maker as _sm

    async with _sm() as db:
        user = await db.get(User, int(payload["sub"]))
        conv = await db.get(Conversation, conv_id)
        if user is None or not user.is_active:
            raise HTTPException(status_code=401, detail="账号不可用")
        if conv is None or conv.user_id != user.id:
            raise HTTPException(status_code=404, detail="会话不存在")
        if body.kb_id is not None:
            kb = await db.get(KnowledgeBase, body.kb_id)
            if kb is None:
                raise HTTPException(status_code=404, detail="知识库不存在")

    # 限流:每用户每分钟提问数
    if not await limiter.check(f"ask:{user.id}", s.rate_ask_per_minute, 60):
        raise HTTPException(status_code=429, detail="提问过于频繁,请稍后再试")

    question = body.content.strip()
    lock = await _get_conv_lock(conv_id)
    async with lock:
        return StreamingResponse(
            _stream_with_disconnect_watch(request, user.id, conv_id, question, body.kb_id),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no",  # 关闭反向代理缓冲,保真流式
                "Connection": "keep-alive",
            },
        )


async def _stream_with_disconnect_watch(
    request: Request, user_id: int, conv_id: int, question: str, kb_id: int | None
):
    """包一层"客户端断开监听",把断连信号注入生成循环。

    背景:Starlette 的 StreamingResponse 不会主动读 receive 事件,
    客户端中途关闭连接时生成器往往察觉不到,任务会空转到 LLM 超时。
    这里起一个监听任务(收到 http.disconnect 即置位),生成循环内各阶段
    检查该事件,主动落库收尾,避免悬挂。
    """
    disconnect = asyncio.Event()

    async def watch() -> None:
        try:
            # receive 在连接断开前会一直阻塞,断开后立刻返回 disconnect 消息
            while True:
                msg = await request.receive()
                logger.info("watch 收到消息: type=%s", msg.get("type"))
                if msg.get("type") == "http.disconnect":
                    disconnect.set()
                    logger.info("检测到客户端断开,正在收尾(conv=%s)", conv_id)
                    return
                if msg.get("type") == "http.request" and not msg.get("more_body"):
                    continue  # body 已读完,继续等待断开消息
        except Exception as e:  # noqa: BLE001
            logger.info("watch 异常置位断开: %s", e)
            disconnect.set()

    watcher = asyncio.create_task(watch())
    inner = _ask_stream(user_id, conv_id, question, kb_id, disconnect)
    try:
        async for event_str in inner:
            yield event_str
            # 断开后最多再产出 1 条(让收尾事件尽量送达),随后强制结束
            if disconnect.is_set():
                break
    finally:
        watcher.cancel()
        # 关键:无论以何种方式结束(自然结束/断开/上层 send 失败),都主动关闭
        # 内层生成器 → 触发其 finally 中的收尾逻辑(半截落库或整轮清理)。
        # 若不加这一步,生成器被悬挂后只能等 GC,消息会一直卡在"生成中"。
        try:
            await inner.aclose()
        except Exception:  # noqa: BLE001 收尾失败已在内部兜底,此处忽略
            pass


async def _ask_stream(
    user_id: int,
    conv_id: int,
    question: str,
    kb_id: int | None,
    disconnect: asyncio.Event,
):
    """流式主流程(生成器)。disconnect:客户端断开置位的事件。"""
    s = get_settings()
    started = time.monotonic()
    assistant_id = str(uuid.uuid4())
    user_message_id: str | None = None
    conv_title = None
    buffer: list[str] = []
    finalized = False

    async def abort_cleanup() -> None:
        """客户端断开收尾:有内容则保留半截(供重新生成);无内容则整轮清掉。"""
        logger.info("断连收尾: conv=%s buffer_len=%d", conv_id, len("".join(buffer)) if buffer else 0)
        if buffer:
            await _partial_persist(assistant_id, "".join(buffer), mark_complete=True)
        else:
            # 尚未产出任何内容:删除占位的问答对,不污染会话历史
            async with async_session_maker() as db:
                for mid in (user_message_id, assistant_id):
                    if mid:
                        m = await db.get(Message, mid)
                        if m:
                            await db.delete(m)
                await db.commit()

    try:
        # ---- 1. 会话与历史 ----
        async with async_session_maker() as db:
            conv = await db.get(Conversation, conv_id)
            # 会话标题:首问自动取前 24 字
            if conv and (not conv.title or conv.title == "新会话"):
                conv.title = (question[:24] + "…") if len(question) > 24 else question
            conv_title = conv.title if conv else None
            lang = conv.language if conv else "auto"
            eff = await _effective_settings(db)
            cache_enabled = eff["cache_enabled"].lower() == "true"
            history_msg_count = (
                await db.scalar(
                    select(func.count())
                    .select_from(Message)
                    .where(Message.conversation_id == conv_id)
                )
            ) or 0
            # 语言:auto 模式按本次提问探测
            if lang == "auto":
                lang = chain.detect_language(question)

            # 用户消息 + 助手占位消息(先落库,断线可续)
            user_msg = Message(
                id=str(uuid.uuid4()),
                conversation_id=conv_id,
                user_id=user_id,
                role="user",
                content=question,
            )
            user_message_id = user_msg.id
            assistant_msg = Message(
                id=assistant_id,
                conversation_id=conv_id,
                user_id=user_id,
                role="assistant",
                content="",
                is_streaming=True,
            )
            # 上一轮若留有半截消息(未点停止/断线)→ 视为重新生成,删除旧占位
            unfinished = (
                await db.scalars(
                    select(Message).where(
                        Message.conversation_id == conv_id,
                        Message.is_streaming.is_(True),
                        Message.id != assistant_id,
                    )
                )
            ).all()
            for m in unfinished:
                await db.delete(m)
            db.add(user_msg)
            db.add(assistant_msg)
            conv.last_active_at = datetime.now()
            await db.commit()
            summary_text, history = await _history_context(db, conv_id, exclude_msg_id=user_msg.id)

        if disconnect.is_set():
            await abort_cleanup()
            return

        # ---- 2. 语义缓存(仅对"会话首问"生效,多轮上下文不适用)----
        is_first_turn = history_msg_count == 0
        if cache_enabled and is_first_turn:
            async with async_session_maker() as cdb:
                hit = await semantic_cache.check_cache(cdb, question, language=lang)
            if hit:
                yield sse("citations", {"sources": hit["citations"], "cached": True})
                # 命中即回放,无需 LLM
                answer = hit["answer"]
                yield sse("token", {"delta": answer})
                await _finalize_guarded(
                    assistant_id, conv_id, user_id, answer,
                    hit["citations"], refused=False, model="cache", latency_ms=int((time.monotonic() - started) * 1000),
                    buffer=buffer,
                )
                finalized = True
                yield sse("done", {"message_id": assistant_id, "conversation_id": conv_id, "refused": False, "title": conv_title})
                return

        # ---- 3. 检索(混合检索 + 重排)+ 拒答判定 ----
        sources: list[dict] = []
        refused = False
        kb_rows: dict[int, KnowledgeBase] = {}
        threshold = float(eff["rerank_threshold"])
        async with async_session_maker() as db:
            chunks, _stages = await retriever.retrieve(db, question, kb_id)
            top_score = chunks[0].score if chunks else 0.0
            refused = not chunks or top_score < threshold
            # 只把"够格的片段"作为引用给模型与前端(弱相关噪声不进引用面板);
            # 若最高分已过线但其余都低于阈值,至少保留 top1 支撑回答
            qualified = [rc for rc in chunks if rc.score >= threshold]
            if not refused and not qualified and chunks:
                qualified = [chunks[0]]
            if not refused:
                if kb_id is not None:
                    kb_rows[kb_id] = (await db.get(KnowledgeBase, kb_id))
                for i, rc in enumerate(qualified):
                    sources.append(
                        {
                            "n": i + 1,
                            "chunk_id": rc.chunk_id,
                            "kb_id": rc.kb_id,
                            "kb_name": kb_rows.get(rc.kb_id).name if kb_rows.get(rc.kb_id) else "",
                            "doc_name": rc.source,
                            "location": _location_of(rc.meta_json),
                            "text": rc.text[:400],
                            "score": rc.score,
                        }
                    )
            # 知识库名称批量补齐(引用面板按库分组展示)
            missing = {src["kb_id"] for src in sources} - set(kb_rows)
            if missing:
                kb_rows.update({k.id: k for k in (await db.scalars(select(KnowledgeBase).where(KnowledgeBase.id.in_(missing)))).all()})
            for src in sources:
                src["kb_name"] = kb_rows.get(src["kb_id"]).name if kb_rows.get(src["kb_id"]) else ""

        # 检索完成但用户已离开:不浪费 LLM 调用,整轮清理
        if disconnect.is_set():
            await abort_cleanup()
            return

        # 先发引用(片段面板秒现),再开始生成
        yield sse("citations", {"sources": sources, "cached": False})

        if refused:
            # ---- 4a. 拒答:不调用 LLM,按语言输出兜底话术 ----
            answer = chain.REFUSAL_TEXTS.get(lang, chain.REFUSAL_TEXTS["zh"])
            yield sse("token", {"delta": answer})
            await _finalize_guarded(
                assistant_id, conv_id, user_id, answer, [],
                refused=True, model="", latency_ms=int((time.monotonic() - started) * 1000),
                buffer=buffer,
            )
            finalized = True
            yield sse("done", {"message_id": assistant_id, "conversation_id": conv_id, "refused": True})
            return

        # ---- 4b. 正常生成(LangChain LCEL 流式)----
        system_content = chain.build_system_content(lang, eff["system_prompt"])
        user_content = chain.build_user_content(
            question,
            chain.build_source_block(sources),
            summary_text,
            chain.format_history(history),
            language=lang,
        )

        last_flush = time.monotonic()
        async with _stream_semaphore:
            async for delta in chain.stream_answer(system_content, user_content):
                buffer.append(delta)
                yield sse("token", {"delta": delta})
                # 周期落库:防止客户端中途断线丢全部内容(落库失败不打断生成)
                if time.monotonic() - last_flush >= _FLUSH_INTERVAL:
                    last_flush = time.monotonic()
                    try:
                        await _partial_persist(assistant_id, "".join(buffer))
                    except Exception as e:  # noqa: BLE001
                        logger.warning("周期落库失败(继续生成): %s", e)
                # 客户端断开:保留已生成部分并解除流式标记,不再继续生成
                if disconnect.is_set():
                    try:
                        await _partial_persist(assistant_id, "".join(buffer), mark_complete=True)
                    except Exception as e:  # noqa: BLE001
                        logger.warning("断连落库失败(留待下次兜底): %s", e)
                    return

        answer = "".join(buffer)
        await _finalize_guarded(
            assistant_id, conv_id, user_id, answer, sources,
            refused=False, model=s.chat_model,
            latency_ms=int((time.monotonic() - started) * 1000),
            buffer=buffer,
        )
        finalized = True

        # ---- 5. 语义缓存写库(首问且非拒答;失败不影响主流程)----
        if cache_enabled and is_first_turn and not refused:
            try:
                async with async_session_maker() as cdb:
                    await semantic_cache.store_cache(cdb, question, answer, sources, kb_id, language=lang)
            except Exception as e:  # noqa: BLE001
                logger.warning("语义缓存写入失败(不影响本次回答): %s", e)

        # ---- 6. 长会话压缩检查(后台任务,不阻塞 done 事件)----
        try:
            from app.rag.history import schedule_compress

            schedule_compress(conv_id)
        except Exception:  # noqa: BLE001
            pass

        yield sse("done", {"message_id": assistant_id, "conversation_id": conv_id, "refused": False, "title": conv_title})

    except asyncio.CancelledError:
        raise  # 半截落库统一交给 finally
    except provider.ProviderNotReady as e:
        yield sse("error", {"code": "PROVIDER_NOT_READY", "message": str(e)})
        await _finalize_message(
            assistant_id, conv_id, user_id, f"[系统提示]{e}", [], refused=True,
            model="", latency_ms=0,
        )
        finalized = True
    except Exception as e:  # noqa: BLE001 未知异常也要以 SSE error 收尾而非裸断流
        logger.exception("问答流异常")
        yield sse("error", {"code": "INTERNAL", "message": str(e)[:200]})
    finally:
        # 兜底:任何未正常收尾的路径(异常/GeneratorExit)→ 按断连语义清理
        if not finalized:
            try:
                await abort_cleanup()
            except Exception:  # noqa: BLE001 兜底清理失败不能影响退出本身
                logger.exception("断连收尾失败")


# ==================== 落库辅助 ====================
async def _finalize_guarded(
    assistant_id: str,
    conv_id: int,
    user_id: int,
    content: str,
    citations: list[dict],
    refused: bool,
    model: str,
    latency_ms: int,
    buffer: list[str],
) -> None:
    """完成落库的带保护版本:失败时降级为快照落库并解除流式标记(不丢内容)。"""
    try:
        await _finalize_message(
            assistant_id, conv_id, user_id, content, citations,
            refused, model, latency_ms,
        )
    except Exception as e:  # noqa: BLE001
        logger.warning("完成落库失败,降级为快照落库: %s", e)
        try:
            await _partial_persist(assistant_id, content or "".join(buffer), mark_complete=True)
        except Exception as e2:  # noqa: BLE001
            logger.warning("快照落库也失败(留待启动/下次提问兜底): %s", e2)


async def _partial_persist(assistant_id: str, content: str | None, mark_complete: bool = False) -> None:
    """流式中途快照落库(防断线丢内容)。

    Args:
        content: 已生成内容;None = 不改内容
        mark_complete: True 时解除"生成中"标记(断线/异常收尾场景)
    """
    async with async_session_maker() as db:
        msg = await db.get(Message, assistant_id)
        if msg is None:
            return
        if content is not None:
            msg.content = content
        if mark_complete:
            msg.is_streaming = False
        await db.commit()


async def _finalize_message(
    assistant_id: str,
    conv_id: int,
    user_id: int,
    content: str,
    citations: list[dict],
    refused: bool,
    model: str,
    latency_ms: int,
) -> None:
    """回答完成:写入最终内容与引用,解除流式标记,刷新会话活跃度。"""
    async with async_session_maker() as db:
        msg = await db.get(Message, assistant_id)
        if msg is None:
            return
        msg.content = content
        msg.citations_json = json.dumps(citations, ensure_ascii=False) if citations else "[]"
        msg.is_streaming = False
        msg.model = model
        msg.latency_ms = latency_ms
        conv = await db.get(Conversation, conv_id)
        if conv:
            conv.last_active_at = datetime.now()
            conv.message_count = (
                await db.scalar(
                    select(func.count()).select_from(Message).where(Message.conversation_id == conv_id)
                )
            ) or 0
        await db.commit()
