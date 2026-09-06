"""数据模型包(每张表均含中文注释,便于毕设论文/答辩讲解)。

表清单:
- users            用户表
- refresh_tokens   刷新令牌表
- knowledge_bases  知识库表
- documents        文档表(解析任务状态机)
- chunks           分块表(最小检索单元)
- chunk_fts        FTS5 全文索引虚表(关键词检索路)
- conversations    会话表(多会话/多语言)
- messages         消息表(含引用溯源)
- feedbacks        消息反馈表
- settings         系统设置表
- cache_items      语义缓存表
"""
from app.models.auth import RefreshToken, User
from app.models.base import Base, TimestampMixin
from app.models.chat import Conversation, Feedback, Message
from app.models.kb import Chunk, Document, KnowledgeBase
from app.models.system import CacheItem, Setting

__all__ = [
    "Base",
    "TimestampMixin",
    "User",
    "RefreshToken",
    "KnowledgeBase",
    "Document",
    "Chunk",
    "Conversation",
    "Message",
    "Feedback",
    "Setting",
    "CacheItem",
]
