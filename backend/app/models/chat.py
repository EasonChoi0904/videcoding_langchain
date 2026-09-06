"""对话域表:conversations 会话表 / messages 消息表 / feedbacks 消息反馈表。

设计要点:assistant 消息的 citations_json 持久化"引用溯源",保证用户任意时刻
重新登录回看历史时,引用片段与分数依然完整可见。
"""
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, local_now


class Conversation(Base, TimestampMixin):
    """会话表:一个用户可拥有多个独立会话(需求:每个用户多个独立会话)。

    language 控制该会话的回答语言,支撑"多语言对话";auto 表示跟随提问语言。
    """

    __tablename__ = "conversations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True, comment="会话主键")
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False, comment="归属用户(会话按用户隔离)"
    )
    title: Mapped[str] = mapped_column(String(128), default="新会话", comment="会话标题(首问自动生成,可手动改名)")
    language: Mapped[str] = mapped_column(
        String(8), default="auto", comment="回答语言:zh=中文 / en=英文 / auto=跟随提问"
    )
    summary_text: Mapped[str | None] = mapped_column(Text, nullable=True, comment="长会话历史压缩摘要(窗口外早期内容)")
    message_count: Mapped[int] = mapped_column(Integer, default=0, comment="消息条数(冗余,列表展示)")
    last_active_at: Mapped[datetime | None] = mapped_column(
        DateTime, default=local_now, index=True, comment="最后活跃时间(会话列表排序依据)"
    )


class Message(Base):
    """消息表:会话内一问一答记录,任意时间段登录可完整找回历史对话。"""

    __tablename__ = "messages"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, comment="uuid 主键")
    conversation_id: Mapped[int] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
        comment="所属会话",
    )
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, comment="归属用户")
    role: Mapped[str] = mapped_column(String(16), nullable=False, comment="消息角色:user=提问 / assistant=回答")
    content: Mapped[str] = mapped_column(Text, nullable=False, comment="消息正文(assistant 为 Markdown)")
    citations_json: Mapped[str | None] = mapped_column(Text, nullable=True, comment="引用溯源 JSON:回答所引用的知识库片段列表(片段/来源/页码/分数)")
    is_streaming: Mapped[bool] = mapped_column(Boolean, default=False, comment="是否半截消息(流式中断标记,UI 支持重新生成)")
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True, comment="生成耗时(毫秒,统计看板数据源)")
    model: Mapped[str | None] = mapped_column(String(64), nullable=True, comment="本次回答所用模型")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=local_now, comment="消息时间(游标分页排序键)")


class Feedback(Base):
    """消息反馈表:用户对回答点赞/点踩并可选留言,沉淀问答质量数据。"""

    __tablename__ = "feedbacks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True, comment="主键")
    message_id: Mapped[str] = mapped_column(
        ForeignKey("messages.id", ondelete="CASCADE"),
        unique=True,
        nullable=False,
        comment="被反馈的助手消息(一条消息最多一个反馈,再点即覆盖)",
    )
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, comment="反馈用户")
    value: Mapped[int] = mapped_column(Integer, nullable=False, comment="反馈值:1=点赞 / -1=点踩")
    comment: Mapped[str | None] = mapped_column(Text, nullable=True, comment="补充意见")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=local_now, comment="反馈时间")
