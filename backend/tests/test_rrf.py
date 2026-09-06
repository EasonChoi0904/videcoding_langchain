"""混合检索 RRF 融合逻辑测试(不依赖向量库)。"""
from app.rag.retriever import _rrf_fuse


def _ids(fused):
    return [cid for cid, _ in fused]


def test_single_leg_order_preserved():
    """只有一路命中时,顺序应保持原召回顺序。"""
    result = _rrf_fuse(["a", "b", "c"], [])
    assert _ids(result) == ["a", "b", "c"]


def test_dual_hit_ranks_first():
    """同时被两路召回(排第 1/第 1)的文档应稳居融合首位。"""
    vector = ["x", "a", "b", "c"]
    keyword = ["x", "c", "d"]
    result = _rrf_fuse(vector, keyword)
    assert _ids(result)[0] == "x"


def test_rrf_rank_position_matters():
    """融合分 = Σ 1/(k+rank):x 在两路都排第 1,应高于只在向量路排第 1 的 a。"""
    vector = ["x", "a"]
    keyword = ["x"]
    fused = dict(_rrf_fuse(vector, keyword))
    # x: 1/(60+1)*2 ≈ 0.0328 > a: 1/61 ≈ 0.0164
    assert fused["x"] > fused["a"]


def test_k_parameter_influence():
    """k 越大融合越"平滑"(同 rank 贡献越低),不影响排序正确性。"""
    vector = ["p", "q"]
    keyword = ["p"]
    assert _ids(_rrf_fuse(vector, keyword, k=10)) == ["p", "q"]
    assert _ids(_rrf_fuse(vector, keyword, k=100)) == ["p", "q"]


def test_empty_inputs():
    assert _rrf_fuse([], []) == []
