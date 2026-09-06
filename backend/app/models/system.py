"""系统级表:settings 系统设置表 / cache_items 语义缓存表。"""
from datetime import datetime

from sqlalchemy import DateTime, Float, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, local_now


class Setting(Base):
    """系统设置表:key-value 配置,管理员页面可动态调整(检索参数/prompt 等),改动即时生效。"""

    __tablename__ = "settings"

    key: Mapped[str] = mapped_column(String(64), primary_key=True, comment="配置键(如 rerank_threshold)")
    value: Mapped[str] = mapped_column(Text, nullable=False, comment="配置值(统一以字符串存储,读取时转换)")
    description: Mapped[str | None] = mapped_column(String(255), nullable=True, comment="配置项中文说明(管理页展示)")
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=local_now, onupdate=local_now, comment="更新时间")


class CacheItem(Base):
    """语义缓存表:高频相似问题直接回放答案,跳过 LLM 调用(秒回 + 省钱)。

    问题向量镜像存 Qdrant question_cache 集合用于相似度命中;知识库内容变更即清空。
    """

    __tablename__ = "cache_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True, comment="主键")
    question: Mapped[str] = mapped_column(Text, nullable=False, comment="问题原文")
    kb_fingerprint: Mapped[str] = mapped_column(String(64), comment="知识库内容指纹(哈希),判断缓存是否仍有效")
    answer: Mapped[str] = mapped_column(Text, nullable=False, comment="缓存的标准回答")
    citations_json: Mapped[str | None] = mapped_column(Text, nullable=True, comment="缓存回答对应的引用片段")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=local_now, index=True, comment="缓存时间(配合 TTL 过期清理)")
