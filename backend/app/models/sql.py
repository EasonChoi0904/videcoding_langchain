"""模型之外的手写 SQL 片段(主要是 FTS5 全文索引的建表与同步)。

SQLite FTS5 trigram 分词器:以 3 字符滑窗建索引,天然支持中文子串匹配,
无需外部分词组件即可命中"手机屏幕"等中文片段(配合 jieba 拆词效果更佳)。
"""
from sqlalchemy import text

# FTS5 虚表:chunk_id 不入索引(UNINDEXED),仅对 text 建 trigram 索引
CREATE_FTS_TABLE = text(
    """
    CREATE VIRTUAL TABLE IF NOT EXISTS chunk_fts
    USING fts5(chunk_id UNINDEXED, text, tokenize='trigram');
    """
)

INSERT_FTS = text("INSERT INTO chunk_fts (chunk_id, text) VALUES (:chunk_id, :text)")
DELETE_FTS = text("DELETE FROM chunk_fts WHERE chunk_id = :chunk_id")
