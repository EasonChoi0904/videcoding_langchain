"""通用响应模型:分页等。"""
from typing import Generic, TypeVar

from pydantic import BaseModel, Field

T = TypeVar("T")


class Page(BaseModel, Generic[T]):
    """通用游标/页码分页响应。"""

    items: list[T]
    total: int = Field(..., description="总条数")


class PageParams(BaseModel):
    """列表页通用参数。"""

    page: int = Field(1, ge=1, description="页码(从 1 开始)")
    size: int = Field(20, ge=1, le=100, description="每页条数")
