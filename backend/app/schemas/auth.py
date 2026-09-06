"""认证相关请求/响应模型。"""
from datetime import datetime

from pydantic import BaseModel, Field, field_validator

# 用户名:中英文/数字/下划线,3~32 位(管理员 admin 也符合该规则)
_USERNAME_PATTERN = r"^[a-zA-Z0-9_一-龥]{3,32}$"


class RegisterRequest(BaseModel):
    """注册请求:用户名 + 密码(二次确认密码由前端完成,后端只收一次)。"""

    username: str = Field(..., description="用户名")
    password: str = Field(..., min_length=6, max_length=64, description="密码(6-64 位)")

    @field_validator("username")
    @classmethod
    def check_username(cls, v: str) -> str:
        import re

        if not re.match(_USERNAME_PATTERN, v):
            raise ValueError("用户名需为 3~32 位中文/字母/数字/下划线")
        return v


class LoginRequest(BaseModel):
    """登录请求。"""

    username: str = Field(..., description="用户名")
    password: str = Field(..., description="密码")


class TokenResponse(BaseModel):
    """登录/刷新成功后的令牌响应。"""

    access_token: str = Field(..., description="访问令牌(短效,请求头 Bearer 携带)")
    refresh_token: str = Field(..., description="刷新令牌(长效,仅用于换取新令牌)")
    token_type: str = "bearer"
    expires_in: int = Field(..., description="访问令牌有效期(秒)")


class RefreshRequest(BaseModel):
    """用刷新令牌换取新令牌对(轮换:旧刷新令牌随即吊销)。"""

    refresh_token: str = Field(..., description="刷新令牌")


class ChangePasswordRequest(BaseModel):
    """修改密码:需校验旧密码,防止账号被他人篡改。"""

    old_password: str = Field(..., description="旧密码")
    new_password: str = Field(..., min_length=6, max_length=64, description="新密码(6-64 位)")


class UserOut(BaseModel):
    """用户信息(返回给前端,绝不包含密码哈希)。"""

    id: int
    username: str
    role: str
    is_active: bool
    created_at: datetime

    model_config = {"from_attributes": True}
