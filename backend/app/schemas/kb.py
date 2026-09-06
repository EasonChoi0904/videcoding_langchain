"""知识库域请求/响应模型。"""
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


# ==================== 知识库 ====================
class KbCreate(BaseModel):
    """创建知识库请求。"""

    name: str = Field(..., min_length=1, max_length=128, description="知识库名称")
    description: str | None = Field(None, max_length=2000, description="知识库描述")
    category: str | None = Field(None, max_length=64, description="类目标签(如 3C数码)")


class KbUpdate(BaseModel):
    """更新知识库请求(部分字段可选)。"""

    name: str | None = Field(None, min_length=1, max_length=128)
    description: str | None = Field(None, max_length=2000)
    category: str | None = Field(None, max_length=64)


class KbOut(BaseModel):
    """知识库信息(含冗余统计)。"""

    id: int
    name: str
    description: str | None
    category: str | None
    doc_count: int
    chunk_count: int
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


# ==================== 文档 ====================
class DocumentOut(BaseModel):
    """文档记录(含解析任务状态,前端据此轮询进度)。"""

    id: int
    kb_id: int
    filename: str
    file_type: str
    size_bytes: int
    parse_status: str            # pending / parsing / done / failed
    progress_done: int
    progress_total: int
    error_msg: str | None
    version: int
    chunk_count: int
    sha256: str
    created_at: datetime
    finished_at: datetime | None

    model_config = {"from_attributes": True}


# ==================== 分块 ====================
class ChunkOut(BaseModel):
    """分块信息(管理端浏览/搜索)。"""

    id: str
    doc_id: int
    kb_id: int
    seq: int
    text: str
    meta_json: str | None
    created_at: datetime

    model_config = {"from_attributes": True}


# ==================== 检索调试 ====================
class DebugSearchRequest(BaseModel):
    """调试台请求:输入问题,输出各检索阶段明细。"""

    question: str = Field(..., min_length=1, description="测试问题")
    kb_id: int | None = Field(None, description="限定知识库(为空则全库检索)")


class DebugHit(BaseModel):
    """调试台单条命中(带来源与分数)。"""

    chunk_id: str
    score: float
    source: str = Field(default="", description="来源文件名")
    text: str = Field(default="", description="片段文本(预览节选)")


class DebugSearchResult(BaseModel):
    """调试台响应:展示 向量路 / 关键词路 / RRF 融合 / 重排后 各阶段结果。"""

    vector_hits: list[DebugHit]
    keyword_hits: list[DebugHit]
    fused_hits: list[DebugHit]
    reranked_hits: list[DebugHit]
    refused: bool = Field(..., description="按当前拒答阈值是否应拒答")
    threshold: float
