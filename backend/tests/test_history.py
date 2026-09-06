"""长会话压缩的纯逻辑测试:消息渲染行(截断/空内容过滤/角色标注)。"""
from app.models import Message
from app.rag.history import _render_lines

_SRC_MSG_CAP = 240  # 与实现保持一致


def _msg(role: str, content: str) -> Message:
    m = Message(id="m", conversation_id=1, user_id=1, role=role, content=content)
    return m


class TestRenderLines:
    def test_role_mapping(self):
        lines = _render_lines([_msg("user", "你好"), _msg("assistant", "您好")])
        assert lines[0].startswith("用户: 你好")
        assert lines[1].startswith("客服: 您好")

    def test_empty_and_blank_content_dropped(self):
        lines = _render_lines([_msg("user", ""), _msg("user", "   "), _msg("user", "有效内容")])
        assert len(lines) == 1

    def test_long_message_truncated(self):
        """超长消息被截断到 _SRC_MSG_CAP,避免摘要原料膨胀。"""
        long_content = "x" * 1000
        lines = _render_lines([_msg("user", long_content)])
        assert len(lines) == 1
        assert len(lines[0]) < _SRC_MSG_CAP + 20

    def test_newlines_flattened(self):
        """消息内换行被拍平为空格(便于压缩模型阅读)。"""
        lines = _render_lines([_msg("user", "第一行\n第二行")])
        assert "\n" not in lines[0]
