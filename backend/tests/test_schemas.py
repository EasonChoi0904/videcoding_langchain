"""Pydantic 请求模型校验测试(非法输入直接被 400 拒绝是安全边界)。"""
import pytest
from pydantic import ValidationError

from app.schemas.auth import ChangePasswordRequest, LoginRequest, RegisterRequest
from app.schemas.chat import AskRequest, ConversationUpdate
from app.schemas.kb import KbCreate


class TestAuthSchemas:
    def test_register_ok(self):
        r = RegisterRequest(username="zhang_san01", password="abc123456")
        assert r.username == "zhang_san01"

    @pytest.mark.parametrize("username", ["ab", "a" * 33, "含非法字符!", "中文用户名-"], )
    def test_register_bad_username(self, username):
        with pytest.raises(ValidationError):
            RegisterRequest(username=username, password="abc123456")

    def test_register_short_password(self):
        with pytest.raises(ValidationError):
            RegisterRequest(username="valid_user", password="12345")

    def test_login_fields(self):
        assert LoginRequest(username="u", password="p").password == "p"

    def test_change_password_limits(self):
        with pytest.raises(ValidationError):
            ChangePasswordRequest(old_password="x", new_password="12345")


class TestChatSchemas:
    def test_ask_empty_rejected(self):
        with pytest.raises(ValidationError):
            AskRequest(content="")

    def test_ask_overlong_rejected(self):
        with pytest.raises(ValidationError):
            AskRequest(content="问" * 2001)

    def test_ask_kb_id_optional(self):
        assert AskRequest(content="电池多大").kb_id is None
        assert AskRequest(content="电池多大", kb_id=3).kb_id == 3

    def test_conversation_language_enum(self):
        with pytest.raises(ValidationError):
            ConversationUpdate(language="fr")  # 只允许 zh/en/auto
        assert ConversationUpdate(language="auto").language == "auto"


class TestKbSchemas:
    def test_kb_name_required(self):
        with pytest.raises(ValidationError):
            KbCreate(name="")
