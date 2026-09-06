# -*- coding: utf-8 -*-
"""SSE 问答客户端:事件解析 + 阶段时间轴 + 终止分类(纯 asyncio + httpx)。

协议(与 backend/app/api/chat.py 对齐):POST /chat/{conv_id}/ask,
Bearer 鉴权,事件序列 citations → token×N → done/error,空行分帧,无心跳。
"""
import json
import time

import httpx

from .config import SSE_STALL_SECONDS


async def ask_sse(
    client: httpx.AsyncClient,
    base: str,
    conv_id: int,
    token: str,
    question: str,
    kb_id: int | None = None,
) -> dict:
    """发起一次流式问答,返回结构化结果。

    Returns(dict):
        http: HTTP 状态码(正常流为 200);网络层异常时为 None
        cls: 分类标识 ok/5xx/429/4xx/connect_error/sse_disconnect/
             sse_app_error/stall/protocol/sqlite_lock(实际产出,无 timeout)
        events: 收到的 SSE 事件名序列
        t_headers / t_first_token / t_done: 相对 t0 的毫秒时间轴
        total_ms / first_token_ms: 总耗时与首 token 耗时
        tokens / chars: token 事件数与累计字符数
        error: 应用 error 事件消息或异常描述
    """
    t0 = time.monotonic()
    rec = {
        "http": None, "cls": "ok", "events": [], "t_headers": 0.0, "t_first_token": 0.0,
        "t_done": 0.0, "total_ms": 0.0, "first_token_ms": 0.0, "tokens": 0, "chars": 0,
        "error": "", "app_code": "",
    }
    try:
        async with client.stream(
            "POST",
            f"{base}/chat/{conv_id}/ask",
            json={"content": question, "kb_id": kb_id},
            headers={"Authorization": f"Bearer {token}"},
            timeout=httpx.Timeout(15.0, connect=10.0, read=SSE_STALL_SECONDS),
        ) as resp:
            rec["http"] = resp.status_code
            if resp.status_code != 200:
                body = await resp.aread()
                text = body.decode("utf-8", "replace")[:200]
                if resp.status_code == 429:
                    rec["cls"] = "429"
                elif resp.status_code >= 500:
                    rec["cls"] = "5xx"
                else:
                    rec["cls"] = "4xx"
                rec["error"] = text
                rec["total_ms"] = (time.monotonic() - t0) * 1000
                return rec

            rec["t_headers"] = (time.monotonic() - t0) * 1000
            ev, data_lines, got_done = None, [], False
            async for line in resp.aiter_lines():
                if not line:  # 空行 = 帧结束
                    if ev is not None:
                        rec["events"].append(ev)
                        payload = "\n".join(data_lines)
                        if ev == "token":
                            rec["tokens"] += 1
                            try:
                                rec["chars"] += len(json.loads(payload).get("delta", ""))
                            except Exception:  # noqa: BLE001
                                pass
                            if rec["t_first_token"] == 0.0:
                                rec["t_first_token"] = (time.monotonic() - t0) * 1000
                        elif ev == "done":
                            rec["t_done"] = (time.monotonic() - t0) * 1000
                            got_done = True
                        elif ev == "error":
                            rec["cls"] = "sse_app_error"
                            try:
                                rec["app_code"] = json.loads(payload).get("code", "")
                                rec["error"] = json.loads(payload).get("message", "")[:200]
                            except Exception:  # noqa: BLE001
                                rec["error"] = payload[:200]
                    ev, data_lines = None, []
                    continue
                if line.startswith("event: "):
                    ev = line[7:].strip()
                elif line.startswith("data: "):
                    data_lines.append(line[6:])
            # 帧尾兜底(最后一帧无空行结束)
            if ev is not None:
                rec["events"].append(ev)
            if not got_done:
                # 流被对端提前关闭(有头无尾)
                if rec["cls"] == "ok":
                    rec["cls"] = "sse_disconnect"
                if rec["t_done"] == 0.0:
                    rec["t_done"] = (time.monotonic() - t0) * 1000
            # 服务端内部异常可能已作为 error 帧发出,HTTP 仍 200
            if rec["cls"] == "ok" and rec["error"]:
                rec["cls"] = "sse_app_error"
    except httpx.ReadTimeout:
        rec["cls"] = "stall" if rec["cls"] == "ok" else rec["cls"]
        rec["error"] = rec["error"] or "字节空闲超时(服务器长时间无输出)"
        rec["t_done"] = rec["t_done"] or (time.monotonic() - t0) * 1000
    except httpx.ConnectError as e:
        rec["cls"] = "connect_error"
        rec["error"] = str(e)[:200]
        rec["t_done"] = rec["t_done"] or (time.monotonic() - t0) * 1000
    except Exception as e:  # noqa: BLE001
        rec["cls"] = "protocol"
        rec["error"] = f"{type(e).__name__}: {str(e)[:200]}"
        rec["t_done"] = rec["t_done"] or (time.monotonic() - t0) * 1000

    rec["total_ms"] = round((time.monotonic() - t0) * 1000, 1)
    rec["t_first_token"] = round(rec["t_first_token"], 1)
    rec["t_headers"] = round(rec["t_headers"], 1)
    # SQLite 写锁特征归类(服务端 500 或 error 帧含锁错误文案时)
    low = rec["error"].lower()
    if "database is locked" in low or "sqlite_busy" in low or "operationalerror" in low:
        rec["cls"] = "sqlite_lock"
    return rec
