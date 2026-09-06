"""问答生成链的纯逻辑测试:语言探测 / 提示词组装 / 历史截断。"""
from app.rag.chain import (
    build_source_block,
    build_system_content,
    detect_language,
    format_history,
    build_user_content,
)


class TestLanguage:
    def test_detect_zh(self):
        assert detect_language("这个手机的电池容量是多少?") == "zh"
        assert detect_language("推荐一款手机") == "zh"

    def test_detect_en(self):
        assert detect_language("What is the price of iPhone 16 Pro?") == "en"

    def test_auto_mixed_short(self):
        assert detect_language("iPhone16 好吗") == "zh"


class TestPromptAssembly:
    def test_system_contains_rules(self):
        content = build_system_content("zh")
        assert "引用" in content and "[n]" in content

    def test_system_language_injection(self):
        zh = build_system_content("zh")
        en = build_system_content("en")
        assert "简体中文" in zh
        assert "English" in en

    def test_source_block_numbering(self):
        block = build_source_block(
            [
                {"doc_name": "规格表.xlsx", "location": "表格第 2 行", "text": "小米15 电池 5400mAh"},
                {"doc_name": "faq.md", "location": "", "text": "整机保修 1 年"},
            ]
        )
        assert block.startswith("[1] 来源:《规格表.xlsx》(表格第 2 行)")
        assert "[2]" in block

    def test_user_content_sections(self):
        content = build_user_content(
            question="电池多大?",
            source_block="[1] xxx",
            summary_text="早期摘要:用户在对比小米与华为",
            history_lines=["用户: 你好", "客服: 您好"],
        )
        assert "【参考资料】" in content
        assert "【更早对话摘要】" in content
        assert "早期摘要" in content
        assert "【对话历史】" in content
        assert "【当前问题】" in content


class TestHistoryFormat:
    def test_truncate_oldest(self):
        """历史过长时保留最近内容(截断更早的)。"""
        history = [
            {"role": "user", "content": "旧问题" + "x" * 600},
            {"role": "assistant", "content": "旧回答" + "y" * 600},
            {"role": "user", "content": "新问题?"},
        ]
        lines = format_history(history)
        joined = "\n".join(lines)
        assert "新问题?" in joined
        # 总长被限制在 _HISTORY_CHAR_CAP 内(超出部分裁掉更早的)
        assert len(joined) <= 4100

    def test_order_preserved(self):
        history = [
            {"role": "user", "content": "第一条"},
            {"role": "assistant", "content": "第二条"},
        ]
        lines = format_history(history)
        assert lines[0].startswith("用户: 第一条")
        assert lines[1].startswith("客服: 第二条")
