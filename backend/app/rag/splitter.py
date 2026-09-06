"""文档解析与分块(四类格式全覆盖):把上传文件切分为"最小检索单元"。

统一输出:分块文本 + 结构化元数据;不同格式采用差异化策略:
- Excel/CSV:一行 = 一条商品记录,整行拼成"列名:值"模板(商品问答最友好)
- PDF/Word/Markdown/HTML/文本:按语义段落切分(中文分隔符优先)

切分组件使用 LangChain 的 RecursiveCharacterTextSplitter
(论文核心框架 LangChain 在解析环节的落地)。
"""
import logging
import re
from pathlib import Path

from langchain_text_splitters import RecursiveCharacterTextSplitter

from app.core.settings import get_settings

logger = logging.getLogger(__name__)

# HTML 中无信息量的标签:直接剔除,避免导航/版权声名进入知识库
_HTML_NOISE_TAGS = ["script", "style", "nav", "header", "footer", "aside", "iframe", "form"]

# 中文语境的分块分隔符(按优先级:整段 > 句子 > 短句 > 空格)
_SPLIT_SEPARATORS = ["\n\n", "\n", "。", "！", "？", "；", "；", " ", ""]


def clean_text(raw: str) -> str:
    """基础清洗:去除控制字符、压缩空白、裁剪首尾。"""
    # 移除零宽/控制字符(保留 \n \t)
    raw = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", raw)
    # 压缩连续空白为单个空格,但保留换行结构
    raw = re.sub(r"[ \t　]+", " ", raw)
    raw = re.sub(r"\n{3,}", "\n\n", raw)
    return raw.strip()


def _is_useful(text: str) -> bool:
    """低信息密度过滤:纯符号/过短/无中英文字符的片段不进知识库。"""
    stripped = text.strip()
    if len(stripped) < 4:
        return False
    # 中英文字符占比过低说明是噪声(表格线、乱码等)
    letters = len(re.findall(r"[一-龥A-Za-z0-9]", stripped))
    return letters / max(len(stripped), 1) > 0.4


def _make_splitter():
    """按配置构造 LangChain 分块器(长度函数以字符计,中文 1 字≈1 token 偏保守)。"""
    s = get_settings()
    return RecursiveCharacterTextSplitter(
        chunk_size=s.chunk_size,
        chunk_overlap=s.chunk_overlap,
        separators=_SPLIT_SEPARATORS,
        length_function=len,
        keep_separator=True,
    )


def _split_long_text(text: str) -> list[str]:
    """把超长文本(单页/单段落)切成 ≤chunk_size 的若干块。"""
    return _make_splitter().split_text(text)


# ==================== 各格式解析器 ====================
def _parse_pdf(path: Path) -> list[tuple[str, dict]]:
    """PDF:逐页抽取文本 + 表格(表格行转文本保留),metadata 记页码。"""
    import fitz  # PyMuPDF

    pieces: list[tuple[str, dict]] = []
    with fitz.open(path) as doc:
        for page_no in range(len(doc)):
            page = doc[page_no]
            page_text = page.get_text("text")
            if _is_useful(page_text):
                pieces.append((page_text, {"page": page_no + 1}))
            # 表格:find_tables 抽出行文本(商品规格表等结构化内容)
            try:
                for table in page.find_tables().tables:
                    for row in table.extract():
                        cells = [str(c).strip() for c in row if c is not None and str(c).strip()]
                        if cells and _is_useful(" ".join(cells)):
                            pieces.append(
                                (" | ".join(cells), {"page": page_no + 1, "type": "table-row"})
                            )
            except Exception as e:  # noqa: BLE001  表格抽取失败不阻断文本解析
                logger.debug("PDF 第 %d 页表格抽取失败: %s", page_no + 1, e)
    return pieces


def _parse_docx(path: Path) -> list[tuple[str, dict]]:
    """Word:段落 + 表格行文本。"""
    import docx

    pieces: list[tuple[str, dict]] = []
    d = docx.Document(str(path))

    def para_text(p) -> str:
        # 保留段落中的换行(如软回车),其余格式信息丢弃
        return "".join(node.text if isinstance(node.text, str) else "" for node in p.runs) or p.text

    for para in d.paragraphs:
        t = para_text(para)
        if _is_useful(t):
            pieces.append((t, {}))
    for tbl in d.tables:
        for row in tbl.rows:
            cells = [c.text.strip() for c in row.cells if c.text.strip()]
            if cells and _is_useful(" ".join(cells)):
                pieces.append((" | ".join(cells), {"type": "table-row"}))
    return pieces


def _parse_spreadsheet(path: Path, is_csv: bool) -> list[tuple[str, dict]]:
    """Excel/CSV:一行一条记录 → "列名:值 | 列名:值" 模板,列名与值一并入文本。

    优点:商品问答时"参数叫什么、值多少"都被向量与关键词覆盖;
    表格首列(通常是商品名/编码)额外记入 metadata 便于溯源展示。
    """
    import pandas as pd

    if is_csv:
        df = pd.read_csv(path, dtype=str)
    else:
        df = pd.read_excel(path, dtype=str)
    df = df.fillna("")
    # 去掉全空列(表头噪声)
    df = df.loc[:, (df != "").any(axis=0)]

    pieces: list[tuple[str, dict]] = []
    for idx, row in df.iterrows():
        cells = []
        first_value = ""
        for col in df.columns:
            value = str(row[col]).strip()
            if not value:
                continue
            if not first_value:
                first_value = value
            cells.append(f"{col}:{value}")
        if not cells:
            continue
        text = " | ".join(cells)
        if _is_useful(text):
            # 行记录太大(单个单元格超长)时再细切
            if len(text) <= get_settings().chunk_size * 2:
                pieces.append((text, {"row": idx + 2, "primary": first_value}))
            else:
                for sub in _split_long_text(text):
                    if _is_useful(sub):
                        pieces.append((sub, {"row": idx + 2, "primary": first_value}))
    return pieces


def _parse_html(path: Path) -> list[tuple[str, dict]]:
    """HTML:剔除导航/脚本等噪声标签后取正文文本,再按段落切分。

    编码容错:优先按 UTF-8 解码;失败(如 GBK 老页面)自动回退 gbk。
    """
    from bs4 import BeautifulSoup

    raw = path.read_bytes()
    try:
        html_text = raw.decode("utf-8")
    except UnicodeDecodeError:
        html_text = raw.decode("gbk", errors="ignore")
    soup = BeautifulSoup(html_text, "lxml")
    for tag in _HTML_NOISE_TAGS:
        for node in soup.find_all(tag):
            node.decompose()
    title = soup.title.get_text(strip=True) if soup.title else ""
    body = soup.get_text("\n")
    pieces: list[tuple[str, dict]] = []
    if title:
        pieces.append((title, {"title": title}))
    return pieces + [(seg, {"title": title}) for seg in body.split("\n") if _is_useful(seg)]


def _parse_plain(path: Path) -> list[tuple[str, dict]]:
    """TXT / Markdown:按换行分段(兼容 \r\n)。"""
    with open(path, encoding="utf-8", errors="ignore") as f:
        content = f.read()
    segs = [s for s in content.replace("\r\n", "\n").split("\n") if _is_useful(s)]
    return [(s, {}) for s in segs]


# ==================== 统一入口 ====================
def parse_document(file_type: str, path: Path) -> list[tuple[str, dict]]:
    """按类型分发解析,返回 [(文本, 元数据), ...] 列表(未切分,按自然段)。"""
    parser = {
        "pdf": _parse_pdf,
        "docx": _parse_docx,
        "xlsx": _parse_spreadsheet,
        "csv": _parse_spreadsheet,
        "html": _parse_html,
        "txt": _parse_plain,
        "md": _parse_plain,
    }.get(file_type)
    if parser is None:
        raise ValueError(f"不支持的文件类型: {file_type}")

    pieces = parser(path, is_csv=(file_type == "csv")) if file_type in ("xlsx", "csv") else parser(path)
    return pieces


def split_pieces(pieces: list[tuple[str, dict]]) -> list[tuple[str, dict, int]]:
    """把解析出的自然段切分为检索分块。

    Returns: [(text, metadata, seq), ...] —— 长度超过阈值的段落被切成多块。
    """
    s = get_settings()
    splitter = _make_splitter()
    results: list[tuple[str, dict, int]] = []
    seq = 0
    for text, meta in pieces:
        # 表格行等本就是整行粒度,只有超长才再切
        if len(text) <= s.chunk_size:
            results.append((text, meta, seq))
            seq += 1
        else:
            for chunk in splitter.split_text(text):
                chunk = clean_text(chunk)
                if _is_useful(chunk):
                    results.append((chunk, dict(meta), seq))
                    seq += 1
    return results
