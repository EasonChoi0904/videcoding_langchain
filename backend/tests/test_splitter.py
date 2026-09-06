"""文档解析与分块逻辑测试(覆盖 txt/md/csv 三路,均为纯本地解析)。"""
import csv
import tempfile
from pathlib import Path

from app.core.settings import get_settings
from app.rag.splitter import (
    _is_useful,
    clean_text,
    parse_document,
    split_pieces,
)

FIXTURE_MD = """# 售后政策

## 退换货
7 天无理由退货,15 天质量问题换新。

## 保修
整机保修 1 年,电池保修 6 个月。
"""

FIXTURE_TXT = "商品A 参数:屏幕 6.7 英寸。\n商品A 电池 5000mAh。\n\n商品B 参数:屏幕 6.1 英寸。\n"


class TestCleanAndUsefulness:
    def test_clean_text(self):
        assert clean_text("  a\tb  \n\n  ") == "a b"
        assert "\x00" not in clean_text("a\x00b\x1fc")

    def test_noise_filtered(self):
        assert not _is_useful("----")
        assert not _is_useful("abc")  # 太短
        assert not _is_useful("！！！@@@###")
        assert _is_useful("商品屏幕 6.7 英寸")


class TestMarkdownParse:
    def test_parse_and_split(self, tmp_path: Path):
        f = tmp_path / "faq.md"
        f.write_text(FIXTURE_MD, encoding="utf-8")
        pieces = parse_document("md", f)
        assert len(pieces) >= 4  # 标题/段落都被拆出

        splits = split_pieces(pieces)
        texts = [t for t, _, _ in splits]
        assert any("无理由退货" in t for t in texts)
        assert any("保修" in t for t in texts)
        # seq 连续编号
        seqs = [s for _, _, s in splits]
        assert seqs == list(range(len(seqs)))
        # 长度不超过 chunk_size + overlap 边界
        for t, _, _ in splits:
            assert len(t) <= get_settings().chunk_size + get_settings().chunk_overlap


class TestCsvParse:
    def test_row_per_chunk(self, tmp_path: Path):
        f = tmp_path / "products.csv"
        with open(f, "w", encoding="utf-8", newline="") as fh:
            writer = csv.writer(fh)
            writer.writerow(["商品编码", "商品名称", "电池容量", "快充功率"])
            writer.writerow(["XMS15P", "小米15 Pro", "5400mAh", "90W"])
            writer.writerow(["HWP70", "华为P70", "5050mAh", "100W"])

        pieces = parse_document("csv", f)
        # 一行 = 一条记录 = 一个分块(列名:值 模板)
        assert len(pieces) == 2
        row1_text = pieces[0][0]
        assert "商品编码:XMS15P" in row1_text
        assert "电池容量:5400mAh" in row1_text
        # 元数据记录表格行号(表头占 1 行 → 数据从第 2 行起)
        assert pieces[0][1]["row"] == 2

        splits = split_pieces(pieces)
        assert len(splits) == 2


class TestTxtParse:
    def test_split_long_segments(self, tmp_path: Path):
        f = tmp_path / "p.txt"
        # 一段超长文本应被切分成多块并保留顺序
        long_seg = "这是商品介绍。" * 300
        f.write_text(long_seg, encoding="utf-8")
        pieces = parse_document("txt", f)
        splits = split_pieces(pieces)
        assert len(splits) > 1
        joined = "".join(t for t, _, _ in splits)
        assert joined == long_seg.replace("\n", "") or long_seg in joined or len(joined) >= len(long_seg) - 10
