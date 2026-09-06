"""对话域请求/响应模型。"""
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

# 会话回答语言:跟随提问(auto)/中文/英文
ConversationLanguage = Literal["zh", "en", "auto"]


class ConversationCreate(BaseModel):
    """创建会话请求。"""

    title: str | None = Field(None, max_length=128, description="自定义标题(留空则由首问自动生成)")
    language: ConversationLanguage = Field("auto", description="回答语言")


class ConversationUpdate(BaseModel):
    """更新会话(改名/切换语言)。"""

    title: str | None = Field(None, max_length=128)
    language: ConversationLanguage | None = None


class ConversationOut(BaseModel):
    """会话列表项。"""

    id: int
    title: str
    language: str
    summary_text: str | None
    message_count: int
    last_active_at: datetime
    created_at: datetime
    updated_at: datetime
    preview: str | None = Field(default=None, description="最后一条消息预览(会话列表展示)")

    model_config = {"from_attributes": True}


class MessageOut(BaseModel):
    """单条消息(含引用溯源)。

    citations 为 null 表示"生成中断的半截消息"(citations_json 从未写入);
    正常完成的消息为 [] 或引用列表。
    """

    id: str
    role: str
    content: str
    citations: list[dict] | None = Field(default=None, description="引用片段列表(正文 [n] 标注对应);null=生成中断")
    is_streaming: bool
    latency_ms: int | None
    model: str | None
    created_at: datetime

    model_config = {"from_attributes": True}


class AskRequest(BaseModel):
    """发起问答请求。"""

    content: str = Field(..., min_length=1, max_length=2000, description="用户问题")
    kb_id: int | None = Field(None, description="限定在某知识库内检索(留空 = 全部知识库)")


class FeedbackRequest(BaseModel):
    """消息反馈:点赞/点踩 + 可选意见。"""

    value: Literal[1, -1] = Field(..., description="1=点赞 / -1=点踩")
    comment: str | None = Field(None, max_length=500)
