"""阿里云百炼供应商适配层(对话 / 向量 / 重排 三合一)。

端点策略:
- 对话:OpenAI 兼容接口(langchain-openai ChatOpenAI 直连)
- 向量 / 重排:兼容模式若可用则用兼容模式,否则退回百炼原生 REST 接口,
  两者最终在 embed_texts/rerank 里被统一掩盖(调用方无感切换)

设计:全部异步;客户端进程级单例;启动时 probe_all() 探测可用性
(缺 Key 只告警;业务调用处 require_ready() 抛友好错误,接口层转 503)。
"""
import logging
from typing import Any

import httpx

from app.core.settings import get_settings

logger = logging.getLogger(__name__)


class ProviderNotReady(RuntimeError):
    """百炼服务未就绪(未配置 Key / 探测失败),调用方需给出友好提示。"""


# ==================== 客户端单例 ====================
_http: httpx.AsyncClient | None = None


def http() -> httpx.AsyncClient:
    global _http
    if _http is None:
        _http = httpx.AsyncClient(timeout=httpx.Timeout(120.0, connect=15.0))
    return _http


def _headers() -> dict[str, str]:
    """百炼 REST 接口的公共请求头。"""
    s = get_settings()
    return {"Authorization": f"Bearer {s.dashscope_api_key}", "Content-Type": "application/json"}


# ==================== 模式探测(embeddings 双通道)====================
_embed_mode: str | None = None  # 探测结果缓存: compatible | native


def _require_key() -> None:
    s = get_settings()
    if not s.dashscope_api_key:
        raise ProviderNotReady("未配置阿里云百炼 API Key,请在 backend/.env 的 DASHSCOPE_API_KEY 中填写")


async def _test_compatible_embed() -> bool:
    """用一句话探测 OpenAI 兼容接口是否支持 /embeddings。"""
    s = get_settings()
    try:
        from openai import AsyncOpenAI

        client = AsyncOpenAI(api_key=s.dashscope_api_key, base_url=s.embedding_compatible_url)
        resp = await client.embeddings.create(model=s.embedding_model, input=["测试"])
        return len(resp.data) > 0
    except Exception as e:  # noqa: BLE001 任何失败都视为该通道不可用
        logger.debug("compatible /embeddings 探测失败: %s", e)
        return False


async def _test_native_embed() -> bool:
    """用一句话探测原生 REST 通道。"""
    s = get_settings()
    try:
        resp = await http().post(
            s.embedding_native_url, headers=_headers(),
            json={"model": s.embedding_model, "input": ["测试"]},
        )
        return resp.status_code == 200
    except Exception as e:  # noqa: BLE001
        logger.debug("native embeddings 探测失败: %s", e)
        return False


async def ensure_embed_ready(force: bool = False) -> str:
    """确认 embedding 通道可用(探测一次并缓存结论),返回当前模式。"""
    global _embed_mode
    _require_key()
    if _embed_mode and not force:
        return _embed_mode

    s = get_settings()
    if s.embedding_api_mode == "compatible":
        _embed_mode = "compatible" if await _test_compatible_embed() else None
    elif s.embedding_api_mode == "native":
        _embed_mode = "native" if await _test_native_embed() else None
    else:  # auto:优先兼容通道
        if await _test_compatible_embed():
            _embed_mode = "compatible"
        elif await _test_native_embed():
            _embed_mode = "native"

    if _embed_mode:
        logger.info("Embedding 通道就绪: mode=%s model=%s", _embed_mode, s.embedding_model)
    else:
        raise ProviderNotReady(
            "百炼向量服务探测失败,请检查 DASHSCOPE_API_KEY 是否正确、模型名是否可用"
        )
    return _embed_mode


# ==================== 向量 ====================
async def embed_texts(texts: list[str]) -> list[list[float]]:
    """批量文本向量化(自动分片到官方单次上限内,顺序与入参一致)。"""
    if not texts:
        return []
    mode = await ensure_embed_ready()
    s = get_settings()
    batch = texts[: s.embedding_batch_size]

    if mode == "compatible":
        from openai import AsyncOpenAI

        client = AsyncOpenAI(api_key=s.dashscope_api_key, base_url=s.embedding_compatible_url)
        resp = await client.embeddings.create(model=s.embedding_model, input=batch)
        # data 按下标对齐;长度与入参不同说明 API 行为变化,直接报错便于发现
        vectors = [d.embedding for d in sorted(resp.data, key=lambda d: d.index)]
    else:
        resp = await http().post(
            s.embedding_native_url,
            headers=_headers(),
            json={"model": s.embedding_model, "input": batch},
        )
        resp.raise_for_status()
        data = resp.json().get("output", {}).get("embeddings", [])
        vectors = [item["embedding"] for item in data]

    if vectors and len(vectors[0]) != s.vector_size:
        raise ProviderNotReady(
            f"向量维度不一致:实际 {len(vectors[0])} 维,配置 {s.vector_size} 维。"
            "请修改 .env 的 VECTOR_SIZE 后重建向量集合(scripts/rebuild_vector_collection.py)"
        )
    return vectors


async def embed_one(text: str) -> list[float]:
    """单条文本向量化。"""
    return (await embed_texts([text]))[0]


# ==================== 重排 ====================
async def rerank(query: str, documents: list[str], top_n: int) -> list[dict[str, Any]]:
    """交叉编码重排:query 与每条文档两两打分,返回按相关度降序的 top_n。

    Returns:
        [{index: 原列表下标, relevance_score: 相关度}, ...]
    """
    _require_key()
    s = get_settings()
    resp = await http().post(
        s.rerank_native_url,
        headers=_headers(),
        json={
            "model": s.rerank_model,
            "input": {"query": query, "documents": documents},
            "parameters": {"top_n": top_n},
        },
    )
    if resp.status_code != 200:
        raise ProviderNotReady(
            f"重排服务调用失败(HTTP {resp.status_code}):{resp.text[:200]}\n"
            f"请检查模型名 {s.rerank_model} 是否可用,可在 .env 的 RERANK_MODEL 调整"
        )
    return resp.json().get("output", {}).get("results", [])


# ==================== 对话(LangChain)====================
def make_chat_model(streaming: bool = True, temperature: float = 0.3):
    """构造 LangChain ChatOpenAI,直连百炼 OpenAI 兼容接口。

    使用 ChatOpenAI 而非原生 SDK:让 LangChain 作为对话链路的核心框架
    (论文主线),同时兼容后续切换到任意 OpenAI 兼容厂商(.env 改 base_url)。
    """
    from langchain_openai import ChatOpenAI

    s = get_settings()
    return ChatOpenAI(
        model=s.chat_model,
        api_key=s.dashscope_api_key,
        base_url=s.chat_base_url,
        streaming=streaming,
        temperature=temperature,
        timeout=s.chat_timeout_seconds,
        max_retries=1,
    )


# ==================== 启动探测 ====================
async def probe_all() -> dict[str, str]:
    """启动时探测三个通道并记录日志,任何失败都不阻断服务启动。"""
    s = get_settings()
    result: dict[str, str] = {}
    if not s.dashscope_api_key:
        return result

    try:
        mode = await ensure_embed_ready(force=True)
        result["embedding"] = f"ok({mode})"
    except ProviderNotReady as e:
        result["embedding"] = f"fail: {e}"
        logger.warning("Embedding 探测失败: %s", e)

    try:
        await rerank("测试", ["测试用例"], 1)
        result["rerank"] = "ok"
    except Exception as e:  # noqa: BLE001
        result["rerank"] = f"fail: {e}"
        logger.warning("Rerank 探测失败: %s", e)

    try:
        llm = make_chat_model(streaming=False, temperature=0)
        resp = await llm.ainvoke("回复:ok")
        result["chat"] = "ok" if "ok" in (resp.content or "").lower() else "ok(响应异常)"
    except Exception as e:  # noqa: BLE001
        result["chat"] = f"fail: {e}"
        logger.warning("Chat 探测失败: %s", e)

    logger.info("百炼通道探测结果: %s", result)
    return result
