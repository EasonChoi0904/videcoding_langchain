"""压测专用 Mock 供应商层(dev-only,默认完全不生效)。

用途:LOADTEST_MOCK_PROVIDER=1 时由 app.main 的 lifespan 调用 install(),
把 provider / chain / history 三个模块里的阿里云百炼调用点替换为本地假实现,
使 100 并发压力测试完全不依赖外部网络与额度,聚焦系统自身容量瓶颈
(SQLite 单写者、Qdrant 同步调用阻塞、事件循环、落库节奏等)。

设计要点:
- 假 embedding 是"同文本同向量"的确定性向量(sha256 作随机种子);不同文本在高维空间
  近似正交(随机单位向量),语义缓存机制因此保持真实:重复问题命中回放路径,
  不同问题走完整生成路径;
- 假 rerank 分数恒高于拒答阈值(0.92-0.02*i),保证走"citations→token→done"完整协议,
  而不是大量触发拒答兜底;检索"质量"不在压测范围,"机制"全部真实执行;
- mock LLM 以 env 可调节奏产出增量,形态逼近真实流式(首包延迟 + 逐 chunk);
- 本模块不被任何产品路径 import,install() 幂等;关闭开关后零影响。

压测节奏 env(可选,不进 Settings 避免污染正式配置面):
  LOADTEST_MOCK_LLM_FIRST_DELAY_MS  首包延迟(默认 250)
  LOADTEST_MOCK_LLM_CHUNK_DELAY_MS  相邻 chunk 间隔(默认 15;主场景建议 45)
  LOADTEST_MOCK_LLM_CHUNK_SIZE      每 chunk 字符数(默认 8)
  LOADTEST_MOCK_LLM_TOTAL_CHARS     单轮回答总字符数(默认 320;主场景建议 520)
"""
import asyncio
import hashlib
import logging
import os
import random
from types import SimpleNamespace

from app.core.settings import get_settings

logger = logging.getLogger(__name__)

_installed = False  # install() 幂等守卫

# 回答模板:内容基于提问生成确定性文本,形态含引用标注,逼近真实回答
_TEMPLATE = (
    "已为您检索到相关商品资料。根据资料[1][2]显示,"
    "{q} 相关内容说明如下:该商品支持页面所述功能,"
    "主要参数与规格以商品详情页标注为准;如需对比其他型号或了解售后政策,"
    "可继续向我提问,我会在知识库内为您查找。"
)


# ==================== 假向量 ====================
def _mock_vector_of(text: str) -> list[float]:
    """对文本生成确定性单位向量(sha256 种子 + L2 归一化,维度与正式配置一致)。"""
    s = get_settings()
    seed = int.from_bytes(hashlib.sha256(text.encode("utf-8")).digest()[:8], "big")
    rnd = random.Random(seed)
    vec = [rnd.random() * 2 - 1 for _ in range(s.vector_size)]
    norm = sum(v * v for v in vec) ** 0.5 or 1.0
    return [v / norm for v in vec]


async def _mock_embed_one(text: str) -> list[float]:
    """单条文本向量化(与 provider.embed_one 同签名)。"""
    return _mock_vector_of(text)


async def _mock_embed_texts(texts: list[str]) -> list[list[float]]:
    """批量文本向量化(保留真实 provider 的批量截断语义,行为一致)。"""
    if not texts:
        return []
    s = get_settings()
    return [_mock_vector_of(t) for t in texts[: s.embedding_batch_size]]


# ==================== 假重排 ====================
async def _mock_rerank(query: str, documents: list[str], top_n: int) -> list[dict]:
    """假重排:按 query 种子确定性打乱顺序,分数恒高于拒答阈值。

    返回结构与真实 provider.rerank 一致:[{index, relevance_score}, ...]
    """
    if not documents or top_n <= 0:
        return []
    seed = int.from_bytes(hashlib.sha256(query.encode("utf-8")).digest()[:8], "big")
    order = list(range(len(documents)))
    random.Random(seed).shuffle(order)
    picked = order[: min(top_n, len(documents))]
    return [
        {"index": idx, "relevance_score": 0.92 - 0.02 * i} for i, idx in enumerate(picked)
    ]


# ==================== 假通道状态 ====================
async def _mock_ensure_embed_ready(force: bool = False) -> str:
    """假 embedding 通道恒可用,返回 mock 模式标识(与真实签名一致)。"""
    return "mock"


async def _mock_probe_all() -> dict[str, str]:
    """假启动探测:直接返回空结果,零真实外呼。"""
    return {}


# ==================== 假对话模型 ====================
class _FakeChatModel:
    """极简假 LLM:仅实现 history 压缩路径用到的 ainvoke(...).content。"""

    def __init__(self, model: str = "mock", **_: object):
        self.model = model

    async def ainvoke(self, prompt: str) -> SimpleNamespace:
        # 压缩摘要路径只取 .content;加一次微小 sleep 贴近真实网络时延
        await asyncio.sleep(0.005)
        text = str(prompt)[:120]
        return SimpleNamespace(content=f"【摘要】{text}...", usage_metadata=None)


def _mock_make_chat_model(streaming: bool = True, temperature: float = 0.3, **_):
    """假模型工厂(与 provider.make_chat_model 同签名,streaming 由调用方控制)。"""
    return _FakeChatModel()


# ==================== 假流式生成 ====================
def _env_int(name: str, default: int, lo: int = 0, hi: int = 2**31 - 1) -> int:
    """读整数 env 并钳制到 [lo, hi],防止误设过大值拖垮压测节奏。"""
    try:
        return min(max(int(os.getenv(name, str(default))), lo), hi)
    except ValueError:
        return default


async def _mock_stream_answer(system_content: str, user_content: str, temperature: float = 0.3):
    """假流式回答:按 env 节奏逐 chunk 产出文本(替代 chain.stream_answer)。

    Args:
        system_content: 系统提示词(真实链路同源构造,此处仅用于拼装确定性内容)
        user_content: 用户提示词(含资料与问题,从中抽取片段保证输出与输入相关)

    Yields:
        str: 与真实链路一致的正文增量(chat.py 逐段拼装并落库)
    """
    first_delay = _env_int("LOADTEST_MOCK_LLM_FIRST_DELAY_MS", 250, 0, 30_000) / 1000
    chunk_delay = _env_int("LOADTEST_MOCK_LLM_CHUNK_DELAY_MS", 15, 0, 5_000) / 1000
    chunk_size = _env_int("LOADTEST_MOCK_LLM_CHUNK_SIZE", 8, 1, 1024)
    total_chars = _env_int("LOADTEST_MOCK_LLM_TOTAL_CHARS", 320, 1, 100_000)

    # 从用户提示词里取问题片段,产出与输入相关的确定性回答(引用编号贴近真实形态)
    q = next((ln for ln in user_content.splitlines() if ln.strip()), user_content)
    q = q.strip()[:80]
    base = _TEMPLATE.format(q=q)
    text = (base * ((total_chars // max(len(base), 1)) + 1))[:total_chars]

    await asyncio.sleep(first_delay)
    for i in range(0, len(text), chunk_size):
        yield text[i : i + chunk_size]
        await asyncio.sleep(chunk_delay)
        # 主动让出事件循环:与真实流式一样不独占 loop
        await asyncio.sleep(0)


# ==================== 安装入口 ====================
def install() -> None:
    """把三处调用点替换为 mock 实现(幂等,重复调用无副作用)。"""
    global _installed
    if _installed:
        return

    from app.rag import chain as _chain
    from app.rag import history as _history
    from app.rag import provider as _provider

    # 模块属性式调用点(retriever/cache/ingest_pipeline 运行时取 provider.X)
    _provider.embed_one = _mock_embed_one
    _provider.embed_texts = _mock_embed_texts
    _provider.rerank = _mock_rerank
    _provider.ensure_embed_ready = _mock_ensure_embed_ready
    _provider.probe_all = _mock_probe_all
    _provider.make_chat_model = _mock_make_chat_model

    # 直接导入式调用点(chain/history 各自命名空间内绑定,须逐个替换)
    _chain.make_chat_model = _mock_make_chat_model
    _chain.stream_answer = _mock_stream_answer
    _history.make_chat_model = _mock_make_chat_model

    _installed = True
    logger.info("[loadtest] mock provider 已安装(假 embedding/rerank/LLM,零真实外呼)")
