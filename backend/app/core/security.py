"""安全工具:密码哈希(bcrypt)、JWT 签发与校验、令牌哈希。

设计说明:
- 密码绝不明文存储,使用 bcrypt(自带盐,抗彩虹表)。
- 访问令牌(短)与刷新令牌(长)分离;刷新令牌只以 SHA-256 哈希落库,
  支持服务端吊销(登出即失效)。
"""
import hashlib
import uuid
from datetime import datetime, timedelta, timezone

import bcrypt
import jwt

from app.core.settings import get_settings


# ==================== 密码 ====================
def hash_password(plain: str) -> str:
    """生成 bcrypt 密码哈希(每次随机盐,同一密码两次结果不同)。"""
    return bcrypt.hashpw(plain.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    """校验明文密码与哈希是否匹配。"""
    try:
        return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))
    except ValueError:
        return False


# ==================== JWT ====================
def _now_utc() -> datetime:
    """带时区的当前 UTC 时间。"""
    return datetime.now(timezone.utc)


def create_access_token(user_id: int, role: str) -> str:
    """签发短时访问令牌,payload 携带用户身份与角色(用于 RBAC 校验)。"""
    s = get_settings()
    payload = {
        "sub": str(user_id),        # subject:用户主键
        "role": role,
        "type": "access",
        "jti": uuid.uuid4().hex,    # 随机唯一 ID:同一秒内签发多次也不会重复
        "iat": _now_utc(),
        "exp": _now_utc() + timedelta(minutes=s.access_token_expire_minutes),
    }
    return jwt.encode(payload, s.secret_key, algorithm=s.jwt_algorithm)


def create_refresh_token(user_id: int) -> str:
    """签发长时刷新令牌,只用来换取新的访问令牌。"""
    s = get_settings()
    payload = {
        "sub": str(user_id),
        "type": "refresh",
        "jti": uuid.uuid4().hex,    # 随机唯一 ID:同一秒内签发多次也不会重复
        "iat": _now_utc(),
        "exp": _now_utc() + timedelta(days=s.refresh_token_expire_days),
    }
    return jwt.encode(payload, s.secret_key, algorithm=s.jwt_algorithm)


def decode_token(token: str, expected_type: str | None = None) -> dict | None:
    """解析 JWT;签名无效 / 过期 / 类型不符返回 None,不做异常上抛。"""
    s = get_settings()
    try:
        payload = jwt.decode(token, s.secret_key, algorithms=[s.jwt_algorithm])
    except jwt.PyJWTError:
        return None
    if expected_type and payload.get("type") != expected_type:
        return None
    return payload


def hash_token(token: str) -> str:
    """刷新令牌入库前的单向哈希:即使库被拖走也无法伪造令牌。"""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()
