"""知识库域表:knowledge_bases 知识库表 / documents 文档表 / chunks 分块表。

chunks 存分块文本与元数据(事实来源),向量存 Qdrant 与该表 id 一一对应;
chunk_fts 为 FTS5 全文索引虚表,由 services/fts.py 同步维护。
"""
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, local_now


class KnowledgeBase(Base, TimestampMixin):
    """知识库表:一组商品文档的集合(如"手机数码库"),支持按库过滤检索。"""

    __tablename__ = "knowledge_bases"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True, comment="知识库主键")
    name: Mapped[str] = mapped_column(String(128), nullable=False, comment="知识库名称(如:手机数码商品库)")
    description: Mapped[str | None] = mapped_column(Text, nullable=True, comment="知识库描述")
    category: Mapped[str | None] = mapped_column(String(64), nullable=True, comment="类目标签(如 3C数码/家电),支持按类目过滤检索")
    doc_count: Mapped[int] = mapped_column(Integer, default=0, comment="文档数(冗余统计,便于列表展示)")
    chunk_count: Mapped[int] = mapped_column(Integer, default=0, comment="分块数(冗余统计)")
    created_by: Mapped[int] = mapped_column(
        ForeignKey("users.id"), nullable=False, comment="创建人"
    )


class Document(Base, TimestampMixin):
    """文档表:上传的原始文件记录,同时承担"解析任务状态机"职责(无独立任务表)。

    状态流转:pending(排队)→ parsing(解析中)→ done(完成)/ failed(失败)。
    """

    __tablename__ = "documents"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True, comment="文档主键")
    kb_id: Mapped[int] = mapped_column(
        ForeignKey("knowledge_bases.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
        comment="所属知识库",
    )
    filename: Mapped[str] = mapped_column(String(255), nullable=False, comment="原始文件名(展示用)")
    file_type: Mapped[str] = mapped_column(String(16), nullable=False, comment="类型:pdf/docx/xlsx/csv/txt/md/html")
    file_path: Mapped[str] = mapped_column(String(512), nullable=False, comment="落盘路径(uuid 命名,防特殊字符)")
    sha256: Mapped[str] = mapped_column(
        String(64), unique=True, nullable=False, comment="文件内容哈希:重传幂等与版本识别"
    )
    size_bytes: Mapped[int] = mapped_column(Integer, default=0, comment="文件大小(字节)")
    parse_status: Mapped[str] = mapped_column(
        String(16), default="pending", index=True, comment="解析状态:pending/parsing/done/failed"
    )
    progress_done: Mapped[int] = mapped_column(Integer, default=0, comment="已入库分块数(进度上报)")
    progress_total: Mapped[int] = mapped_column(Integer, default=0, comment="预计分块总数")
    error_msg: Mapped[str | None] = mapped_column(Text, nullable=True, comment="失败原因")
    version: Mapped[int] = mapped_column(Integer, default=1, comment="版本号(覆盖上传时自增)")
    chunk_count: Mapped[int] = mapped_column(Integer, default=0, comment="实际入库分块数")
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, comment="解析完成时间")


class Chunk(Base):
    """分块表:文档切分后的最小检索单元。

    id 为 uuid 字符串,与 Qdrant 向量 point id 完全一致;删除分块需同步删向量。
    """

    __tablename__ = "chunks"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, comment="uuid 主键(与 Qdrant point id 一致)")
    doc_id: Mapped[int] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), index=True, nullable=False, comment="所属文档"
    )
    kb_id: Mapped[int] = mapped_column(
        ForeignKey("knowledge_bases.id", ondelete="CASCADE"), index=True, nullable=False, comment="所属知识库"
    )
    seq: Mapped[int] = mapped_column(Integer, default=0, comment="块在文档内的顺序号")
    text: Mapped[str] = mapped_column(Text, nullable=False, comment="分块文本(引用展示的唯一事实来源)")
    meta_json: Mapped[str | None] = mapped_column(Text, nullable=True, comment="结构化元数据 JSON:页码/行号/来源文件/商品标识等")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=local_now, comment="入库时间")
