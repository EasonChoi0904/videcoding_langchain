"""FTS5 全文索引维护与中文关键词查询(混合检索的"关键词路")。

分词策略(FTS5 trigram 以 3 字符滑窗建索引,天然支持中文子串):
- 直接提取"字母/数字/中文连续串"作为候选(≥3 字符):兼容"小米15"这类
  中英混排型号,天然规避分词歧义;
- 同时用 jieba 拆词:≥3 字词直接入列,2 字短词与相邻词合并成词对补足;
- 候选之间用 OR 连接(召回导向):多路候选任一命中即召回,由 BM25 rank 排序,
  精度不足交给后续 RRF 融合与交叉编码重排去兜底(两段式设计的前提)。
"""
import logging
import re
import unicodedata

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.sql import DELETE_FTS, INSERT_FTS

logger = logging.getLogger(__name__)

# 归一化时剔除的标点(避免"iPhone16 / iPhone 16 / iPhone-16"三者断裂)
_PUNCT_RE = re.compile(r"[\s,，。.!！?？;；:：、()（）\[\]【】{}<>《》\"'“”‘’\-_—/\\|·*~`@#$%^&+=]")


def normalize_for_fts(text: str) -> str:
    """FTS 入库与查询共用的归一化:去空白/标点、ASCII 小写。

    目的:让 "iPhone 16 Pro"、"iPhone16Pro"、"iphone-16" 等写法能互相命中
    (trigram 索引要求连续子串,归一化消除了书写差异)。
    """
    # 全角字符转半角(兼容用户输入全角空格/标点)
    text = unicodedata.normalize("NFKC", text)
    text = _PUNCT_RE.sub("", text)
    return text.lower()

# 常见中文停用词(最小集合,保证关键词路质量)
_STOPWORDS = {
    "的", "了", "吗", "呢", "啊", "吧", "呀", "嘛", "哦", "嗯",
    "什么", "怎么", "为什么", "如何", "怎样", "怎么办", "请问", "可以", "能不能", "是否",
    "我", "你", "他", "她", "它", "我们", "你们", "他们", "这", "那", "这个", "那个",
    "是", "在", "有", "和", "与", "及", "或", "把", "被", "就", "都", "而", "等",
    "一个", "一下", "一些", "介绍", "多少", "几", "些", "能", "要", "想", "请", "帮",
    "给", "会", "没", "不", "很", "最", "更", "太", "已经", "比较", "非常", "真的",
}

# 字母/数字/中文连续串(含中英混排型号,如 小米15 / iphone15pro)
_MIXED_RUN_RE = re.compile(r"[A-Za-z0-9一-龥]{3,}")


def _load_jieba():
    """jieba 体积小但导入慢,懒加载只影响首次关键词查询。"""
    import jieba

    return jieba


def build_keyword_query(question: str) -> list[str]:
    """把用户问题拆成一组关键词短语(每个短语 ≥3 字符,FTS trigram 才可匹配)。"""
    terms: list[str] = []

    # ---- 1. 连续串直取(中英混排型号、无分词歧义片段)----
    for run in _MIXED_RUN_RE.findall(question):
        # 纯数字且不足 4 位(如 15)不是有效检索词
        if re.fullmatch(r"[0-9]+", run) and len(run) < 4:
            continue
        # 英文单词过短(如 Pro→3 可留,2 位以下跳过)
        if re.fullmatch(r"[A-Za-z]+", run) and len(run) < 3:
            continue
        terms.append(run)

    # ---- 2. jieba 拆词:≥3 字词 + 相邻词对(覆盖 2 字短词组合)----
    jieba = _load_jieba()
    for part in re.findall(r"[一-龥]{2,}", question):
        words = [
            w
            for w in jieba.cut_for_search(part)
            if w not in _STOPWORDS and len(w) >= 2
        ]
        for w in words:
            if len(w) >= 3:
                terms.append(w)
        for i in range(len(words) - 1):
            pair = words[i] + words[i + 1]
            if len(pair) >= 3:
                terms.append(pair)

    # ---- 3. 去重限长(OR 候选太多噪声大,8 个封顶)----
    seen: set[str] = set()
    result: list[str] = []
    for t in terms:
        if t not in seen:
            seen.add(t)
            result.append(t)
        if len(result) >= 8:
            break
    return result


def build_fts_match(terms: list[str]) -> str:
    """把短语列表拼成 FTS5 MATCH 表达式:任一候选命中即召回(OR + BM25 排序)。

    查询词与索引同样归一化,保证 "iPhone 16" / "iphone16" 写法互通。
    """
    normalized = [normalize_for_fts(t) for t in terms if normalize_for_fts(t)]
    quoted = ['"' + t.replace('"', '""') + '"' for t in normalized]
    return " OR ".join(quoted)


async def add_fts(db: AsyncSession, chunk_id: str, chunk_text: str) -> None:
    """入库后同步写入 FTS 索引(入库前先归一化,统一书写差异)。"""
    await db.execute(
        INSERT_FTS, {"chunk_id": chunk_id, "text": normalize_for_fts(chunk_text)}
    )


async def delete_fts(db: AsyncSession, chunk_id: str) -> None:
    """删除分块时同步移除 FTS 索引。"""
    await db.execute(DELETE_FTS, {"chunk_id": chunk_id})


async def delete_fts_by_doc(db: AsyncSession, doc_id: int) -> None:
    """删除整篇文档的 FTS 索引(先取 chunk_id 列表再逐个删)。"""
    from sqlalchemy import select

    from app.models import Chunk

    chunk_ids = (await db.scalars(select(Chunk.id).where(Chunk.doc_id == doc_id))).all()
    for cid in chunk_ids:
        await delete_fts(db, cid)


async def search_keywords(
    db: AsyncSession, terms: list[str], top_k: int, kb_id: int | None = None
) -> list[str]:
    """FTS5 关键词检索,按 BM25 相关度返回 chunk_id 列表(降序)。"""
    if not terms:
        return []
    match_expr = build_fts_match(terms)
    if not match_expr:
        # 全部候选在归一化后为空(纯标点等)→ 关键词路不产出
        return []
    # kb 过滤:join 回 chunks 表拿 kb_id(分块数规模内 join 开销可忽略)
    sql = """
        SELECT c.id FROM chunks c
        JOIN chunk_fts f ON f.chunk_id = c.id
        WHERE chunk_fts MATCH :match
    """
    params: dict = {"match": match_expr}
    if kb_id is not None:
        sql += " AND c.kb_id = :kb_id"
        params["kb_id"] = kb_id
    sql += " ORDER BY rank LIMIT :limit"
    params["limit"] = top_k
    rows = await db.execute(text(sql), params)
    return [r[0] for r in rows.fetchall()]
