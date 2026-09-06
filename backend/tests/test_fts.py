"""关键词检索逻辑测试:查询构造(FTS 前)与 FTS5 全链路(临时 SQLite)。"""
import asyncio
import os
import tempfile

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.services.fts import (
    add_fts,
    build_keyword_query,
    build_fts_match,
    delete_fts,
    search_keywords,
)
from app.models.sql import CREATE_FTS_TABLE


# ---------------- 查询构造(纯函数)----------------
class TestKeywordQuery:
    def test_mixed_model_token(self):
        """中英混排型号(小米15/iphone15pro)应整体保留为检索词。"""
        terms = build_keyword_query("小米15 Pro 多少钱")
        assert any("小米15" in t for t in terms)

    def test_ascii_model_token(self):
        terms = build_keyword_query("iphone15pro 支持吗")
        assert "iphone15pro" in terms

    def test_short_word_pairing(self):
        """2 字词(如"碎了")无法单独 trigram 匹配,应与相邻词组成词对。"""
        terms = build_keyword_query("屏幕碎了怎么办")
        assert any(t.startswith("屏幕") and len(t) >= 3 for t in terms)

    def test_or_semantics(self):
        """候选之间以 OR 连接(任一命中即可召回)。"""
        match = build_fts_match(["小米15", "保修政策"])
        assert '"小米15" OR "保修政策"' == match

    def test_no_useful_terms(self):
        terms = build_keyword_query("嗯嗯")
        assert isinstance(terms, list)


# ---------------- FTS5 全链路(临时库)----------------
@pytest.mark.asyncio
async def test_fts_roundtrip_and_search():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    engine = create_async_engine(f"sqlite+aiosqlite:///{path}")
    Session = async_sessionmaker(engine)

    async with engine.begin() as conn:
        # 分块表(chunks)与 FTS 虚表(chunk_fts)
        await conn.execute(
            text(
                """
                CREATE TABLE chunks (
                    id TEXT PRIMARY KEY, kb_id INT, doc_id INT, seq INT,
                    text TEXT, meta_json TEXT, created_at TEXT
                )
                """
            )
        )
        await conn.execute(CREATE_FTS_TABLE)

    async with Session() as db:
        # 写两个分块并建索引
        await db.execute(text("INSERT INTO chunks VALUES ('c1',1,1,0,'小米15 Pro 支持 90W 快充','','')"))
        await db.execute(text("INSERT INTO chunks VALUES ('c2',2,2,0,'iPhone 16 Pro 支持 40W 快充','','')"))
        await add_fts(db, "c1", "小米15 Pro 支持 90W 快充")
        await add_fts(db, "c2", "iPhone 16 Pro 支持 40W 快充")
        await db.commit()

        # 中文型号命中
        hits = await search_keywords(db, build_keyword_query("小米15 快充"), top_k=5)
        assert hits == ["c1"]
        # 英文型号命中(kb 过滤生效)
        hits2 = await search_keywords(db, build_keyword_query("iphone16"), top_k=5, kb_id=2)
        assert hits2 == ["c2"]
        # kb 过滤隔离(同样的查询在 kb 1 内应无命中)
        hits3 = await search_keywords(db, build_keyword_query("iphone16"), top_k=5, kb_id=1)
        assert hits3 == []
        # 删除索引后不再命中
        await delete_fts(db, "c1")
        await db.commit()
        hits4 = await search_keywords(db, build_keyword_query("小米15"), top_k=5)
        assert hits4 == []

    await engine.dispose()
    os.unlink(path)
