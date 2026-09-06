"""认证相关表:users 用户表 / refresh_tokens 刷新令牌表。"""
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, local_now


class User(Base, TimestampMixin):
    """用户表:区分管理员(可管理知识库)与普通用户(仅问答)。"""

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True, comment="用户主键")
    username: Mapped[str] = mapped_column(
        String(64), unique=True, index=True, nullable=False, comment="登录用户名(唯一)"
    )
    password_hash: Mapped[str] = mapped_column(String(128), nullable=False, comment="bcrypt 密码哈希")
    role: Mapped[str] = mapped_column(
        String(16), default="user", nullable=False, comment="角色:admin=管理员 / user=普通用户"
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, comment="是否启用(失败锁定/停用时置否)")
    failed_login_count: Mapped[int] = mapped_column(Integer, default=0, comment="连续登录失败次数(防爆破)")
    locked_until: Mapped[datetime | None] = mapped_column(
        DateTime, nullable=True, comment="账号锁定截止时间(锁定期间拒绝登录)"
    )


class RefreshToken(Base):
    """刷新令牌表:仅存令牌 SHA-256 哈希,支持服务端吊销(登出即失效)。"""

    __tablename__ = "refresh_tokens"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True, comment="主键")
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False, comment="归属用户"
    )
    token_hash: Mapped[str] = mapped_column(
        String(64), unique=True, nullable=False, comment="刷新令牌的 SHA-256 哈希"
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, comment="过期时间")
    revoked: Mapped[bool] = mapped_column(Boolean, default=False, comment="是否已吊销")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=local_now, comment="签发时间")
