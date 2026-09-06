"""FastAPI 依赖注入:鉴权(RBAC)与通用依赖。"""
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import decode_token
from app.db import get_db
from app.models import User

# auto_error=False:拿不到令牌时我们自己抛 401(错误信息更友好)
_bearer = HTTPBearer(auto_error=False)


async def get_current_user(
    db: AsyncSession = Depends(get_db),
    cred: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> User:
    """解析 Bearer 访问令牌并加载用户。任何受保护接口的第一步。"""
    if cred is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="未登录或登录已过期,请重新登录",
        )
    payload = decode_token(cred.credentials, expected_type="access")
    if payload is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="令牌无效或已过期,请重新登录",
        )
    user = await db.get(User, int(payload["sub"]))
    if user is None or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="账号不存在或已被禁用",
        )
    return user


def require_admin(user: User = Depends(get_current_user)) -> User:
    """RBAC:仅管理员可访问(知识库管理所有接口都挂这个依赖)。"""
    if user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="仅管理员可执行该操作",
        )
    return user


async def get_user_or_none(
    db: AsyncSession = Depends(get_db),
    cred: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> User | None:
    """可选鉴权:没有令牌也放行(当前没有这种接口,保留给未来扩展)。"""
    if cred is None:
        return None
    payload = decode_token(cred.credentials, expected_type="access")
    if payload is None:
        return None
    return await db.get(User, int(payload["sub"]))
