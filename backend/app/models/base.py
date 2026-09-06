"""ORM 声明基类与通用混入。"""
from datetime import datetime

from sqlalchemy import DateTime, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def local_now() -> datetime:
    """本地时间(单机部署,数据库直接存本地时间,前端展示无需换算)。"""
    return datetime.now()


class Base(DeclarativeBase):
    """所有 ORM 模型的声明基类。"""


class TimestampMixin:
    """创建/更新时间混入:各表统一维护这两个字段。"""

    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=local_now, comment="创建时间"
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=local_now, onupdate=local_now, comment="更新时间"
    )
