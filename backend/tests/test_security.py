"""认证安全核心逻辑测试:密码哈希 / JWT 签发与校验。"""
import time

from app.core.security import (
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    hash_token,
    verify_password,
)


class TestPassword:
    def test_hash_roundtrip(self):
        hashed = hash_password("abc123456")
        assert hashed != "abc123456"
        assert verify_password("abc123456", hashed)

    def test_wrong_password_rejected(self):
        hashed = hash_password("abc123456")
        assert not verify_password("wrong-pass", hashed)

    def test_salt_randomness(self):
        """同一密码两次哈希结果不同(自带随机盐)。"""
        assert hash_password("abc123456") != hash_password("abc123456")


class TestJwt:
    def test_access_token_roundtrip(self):
        token = create_access_token(user_id=42, role="admin")
        payload = decode_token(token, expected_type="access")
        assert payload is not None
        assert payload["sub"] == "42"
        assert payload["role"] == "admin"

    def test_type_mismatch_rejected(self):
        """刷新令牌不能当访问令牌用(类型隔离)。"""
        refresh = create_refresh_token(user_id=42)
        assert decode_token(refresh, expected_type="access") is None

    def test_tampered_token_rejected(self):
        token = create_access_token(user_id=1, role="user")
        assert decode_token(token + "x") is None
        # 篡改 payload(把 role 改成 admin)
        import jwt as pyjwt

        from app.core.settings import get_settings

        parts = token.split(".")
        forged = pyjwt.encode(
            {"sub": "1", "role": "admin", "type": "access"},
            "wrong-secret-key",
            algorithm="HS256",
        )
        assert decode_token(forged, expected_type="access") is None
        assert parts[0]  # 防止 lint 未使用告警

    def test_expired_token_rejected(self):
        """伪造已过期令牌应被拒绝。"""
        import jwt as pyjwt
        from datetime import datetime, timedelta, timezone

        from app.core.settings import get_settings

        s = get_settings()
        expired = pyjwt.encode(
            {
                "sub": "1",
                "role": "user",
                "type": "access",
                "exp": datetime.now(timezone.utc) - timedelta(seconds=5),
            },
            s.secret_key,
            algorithm=s.jwt_algorithm,
        )
        assert decode_token(expired, expected_type="access") is None

    def test_jti_uniqueness(self):
        """同一秒内签发多次令牌必须互不相同(曾因 iat 秒级精度导致撞车)。"""
        tokens = {create_refresh_token(user_id=7) for _ in range(5)}
        assert len(tokens) == 5

    def test_token_hash_deterministic(self):
        assert hash_token("abc") == hash_token("abc")
        assert hash_token("abc") != hash_token("abd")
