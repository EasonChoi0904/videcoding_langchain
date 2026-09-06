"""认证接口:注册 / 登录 / 刷新 / 登出 / 改密。

安全设计:
- 登录限流(同 IP+用户名 每分钟 5 次)+ 连续失败锁定账号(10 分钟)
- 刷新令牌轮换:每次刷新都吊销旧令牌,泄露窗口最小化
- 修改密码后吊销该用户全部刷新令牌(强制重新登录)
"""
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user
from app.core.rate_limit import limiter
from app.core.security import (
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    hash_token,
    verify_password,
)
from app.core.settings import get_settings
from app.db import get_db
from app.models import RefreshToken, User
from app.schemas.auth import (
    ChangePasswordRequest,
    LoginRequest,
    RefreshRequest,
    RegisterRequest,
    TokenResponse,
    UserOut,
)

router = APIRouter()

# 客户端 IP 取值优先级:反向代理头 > 直连地址(单机部署通常直连)
def _client_ip(request: Request) -> str:
    xff = request.headers.get("x-forwarded-for")
    return xff.split(",")[0].strip() if xff else request.client.host or "unknown"


async def _issue_token_pair(db: AsyncSession, user: User) -> TokenResponse:
    """签发一对新令牌,并把刷新令牌哈希落库(支持服务端吊销)。"""
    s = get_settings()
    access = create_access_token(user.id, user.role)
    refresh = create_refresh_token(user.id)
    db.add(
        RefreshToken(
            user_id=user.id,
            token_hash=hash_token(refresh),
            expires_at=datetime.now() + timedelta(days=s.refresh_token_expire_days),
        )
    )
    await db.commit()
    return TokenResponse(
        access_token=access,
        refresh_token=refresh,
        expires_in=s.access_token_expire_minutes * 60,
    )


@router.post("/register", response_model=UserOut, summary="用户注册(自动成为普通用户)")
async def register(body: RegisterRequest, request: Request, db: AsyncSession = Depends(get_db)):
    s = get_settings()
    # 防刷:同一 IP 每小时最多注册 10 个账号
    if not await limiter.check(f"register:{_client_ip(request)}", s.rate_register_per_hour, 3600):
        raise HTTPException(status_code=429, detail="注册过于频繁,请稍后再试")

    exists = await db.scalar(select(User).where(User.username == body.username))
    if exists:
        raise HTTPException(status_code=409, detail="用户名已被注册")
    # 注册入口创建的都是普通用户;管理员只由种子脚本创建
    user = User(
        username=body.username,
        password_hash=hash_password(body.password),
        role="user",
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user


@router.post("/login", response_model=TokenResponse, summary="登录(返回令牌对)")
async def login(body: LoginRequest, request: Request, db: AsyncSession = Depends(get_db)):
    s = get_settings()
    key = f"login:{_client_ip(request)}:{body.username}"
    if not await limiter.check(key, s.rate_login_per_minute, 60):
        raise HTTPException(status_code=429, detail="尝试过于频繁,请 1 分钟后再试")

    user = await db.scalar(select(User).where(User.username == body.username))

    # 账号不存在也走一次假校验,避免通过响应时间差探测用户名是否存在
    dummy_hash = hash_password("dummy-password")
    if user is None:
        verify_password(body.password, dummy_hash)
        raise HTTPException(status_code=401, detail="用户名或密码错误")

    if not user.is_active:
        raise HTTPException(status_code=403, detail="账号已被禁用,请联系管理员")
    if user.locked_until and user.locked_until > datetime.now():
        raise HTTPException(status_code=423, detail="账号已锁定,请稍后再试")

    if not verify_password(body.password, user.password_hash):
        user.failed_login_count += 1
        # 连续失败达到阈值 → 锁定账号一段时间(防暴力破解)
        if user.failed_login_count >= s.login_max_failures:
            user.locked_until = datetime.now() + timedelta(minutes=s.login_lock_minutes)
            user.failed_login_count = 0
        await db.commit()
        raise HTTPException(status_code=401, detail="用户名或密码错误")

    # 登录成功:清零失败计数并解除锁定
    user.failed_login_count = 0
    user.locked_until = None
    await db.commit()
    return await _issue_token_pair(db, user)


@router.post("/refresh", response_model=TokenResponse, summary="刷新令牌(轮换)")
async def refresh(body: RefreshRequest, db: AsyncSession = Depends(get_db)):
    payload = decode_token(body.refresh_token, expected_type="refresh")
    if payload is None:
        raise HTTPException(status_code=401, detail="刷新令牌无效或已过期")

    stored = await db.scalar(
        select(RefreshToken).where(RefreshToken.token_hash == hash_token(body.refresh_token))
    )
    if stored is None or stored.revoked:
        raise HTTPException(status_code=401, detail="刷新令牌已被吊销")
    if stored.expires_at < __import__("datetime").datetime.now():
        raise HTTPException(status_code=401, detail="刷新令牌已过期")

    user = await db.get(User, int(payload["sub"]))
    if user is None or not user.is_active:
        raise HTTPException(status_code=401, detail="账号不存在或已被禁用")

    # 轮换:吊销旧令牌,发新令牌对
    stored.revoked = True
    await db.commit()
    return await _issue_token_pair(db, user)


@router.post("/logout", summary="登出(吊销当前刷新令牌)")
async def logout(body: RefreshRequest, db: AsyncSession = Depends(get_db)):
    stored = await db.scalar(
        select(RefreshToken).where(RefreshToken.token_hash == hash_token(body.refresh_token))
    )
    if stored:
        stored.revoked = True
        await db.commit()
    return {"message": "已退出登录"}


@router.put("/password", summary="修改密码(需校验旧密码)")
async def change_password(
    body: ChangePasswordRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    if not verify_password(body.old_password, user.password_hash):
        raise HTTPException(status_code=400, detail="旧密码不正确")
    if body.old_password == body.new_password:
        raise HTTPException(status_code=400, detail="新密码不能与旧密码相同")
    user.password_hash = hash_password(body.new_password)
    await db.commit()
    # 安全:改密后吊销该用户全部刷新令牌,旧会话全部失效
    stmt = select(RefreshToken).where(
        RefreshToken.user_id == user.id, RefreshToken.revoked.is_(False)
    )
    for rt in (await db.scalars(stmt)).all():
        rt.revoked = True
    await db.commit()
    return {"message": "密码修改成功,请重新登录"}


@router.get("/me", response_model=UserOut, summary="当前登录用户信息")
async def me(user: User = Depends(get_current_user)):
    return user
