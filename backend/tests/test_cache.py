"""语义缓存纯逻辑测试:知识库指纹计算(顺序无关/内容敏感)。"""
from app.rag.cache import compute_kb_fingerprint


class TestKbFingerprint:
    def test_order_independent(self):
        """指纹与文档 sha256 的排列顺序无关(同一集合指纹相同)。"""
        a = compute_kb_fingerprint(["x1", "x2", "x3"])
        b = compute_kb_fingerprint(["x3", "x1", "x2"])
        assert a == b

    def test_content_sensitive(self):
        """文档集合变化(增/删)指纹必须变化,缓存才能正确失效。"""
        assert compute_kb_fingerprint(["x1"]) != compute_kb_fingerprint(["x1", "x2"])
        assert compute_kb_fingerprint(["x1"]) != compute_kb_fingerprint([])

    def test_empty_set(self):
        assert compute_kb_fingerprint([]) == compute_kb_fingerprint([])
        assert len(compute_kb_fingerprint([])) == 32  # md5 hex
