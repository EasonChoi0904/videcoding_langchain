"""文档上传与解析任务接口(仅管理员)。

上传约定:
- 类型白名单(pdf/docx/xlsx/csv/txt/md/html),单文件 ≤ 50MB
- sha256 幂等:重复上传同一文件 → 409;带 replace=true 则覆盖旧版本(重新解析)
- 入库后进入异步解析队列,状态/进度由 GET 轮询
"""
import hashlib
import logging
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import require_admin
from app.core.settings import get_settings
from app.db import get_db
from app.models import Document, KnowledgeBase
from app.schemas.kb import DocumentOut
from app.services.document_ops import clear_document_content, delete_document
from app.services.ingestion import ingest_manager

logger = logging.getLogger(__name__)
router = APIRouter(
    prefix="/documents", tags=["文档解析(管理员)"], dependencies=[Depends(require_admin)]
)


async def _get_doc_or_404(db: AsyncSession, doc_id: int) -> Document:
    doc = await db.get(Document, doc_id)
    if doc is None:
        raise HTTPException(status_code=404, detail="文档不存在")
    return doc


async def _get_kb_or_404(db: AsyncSession, kb_id: int) -> KnowledgeBase:
    kb = await db.get(KnowledgeBase, kb_id)
    if kb is None:
        raise HTTPException(status_code=404, detail="知识库不存在")
    return kb


@router.post("/kb/{kb_id}/upload", response_model=DocumentOut, summary="上传文档并触发解析")
async def upload_document(
    kb_id: int,
    file: UploadFile = File(...),
    replace: bool = Query(False, description="文件已存在时是否覆盖重传"),
    db: AsyncSession = Depends(get_db),
):
    s = get_settings()
    kb = await _get_kb_or_404(db, kb_id)

    # ---- 类型白名单 ----
    ext = Path(file.filename or "").suffix.lower()
    if ext not in s.allowed_extensions:
        raise HTTPException(
            status_code=400,
            detail=f"不支持的文件类型 {ext},支持:{'、'.join(s.allowed_extensions)}",
        )
    file_type = ext.lstrip(".")

    # ---- 流式落盘 + 边写边算 sha256(大文件不占内存)----
    dest_name = f"{uuid.uuid4().hex}{ext}"
    dest = s.upload_dir / dest_name
    sha = hashlib.sha256()
    size = 0
    try:
        with open(dest, "wb") as out:
            while chunk := await file.read(1024 * 1024):  # 1MB 分片读
                size += len(chunk)
                if size > s.max_file_size_mb * 1024 * 1024:
                    raise HTTPException(
                        status_code=413,
                        detail=f"文件超过 {s.max_file_size_mb}MB 上限",
                    )
                sha.update(chunk)
                out.write(chunk)
    except Exception:
        dest.unlink(missing_ok=True)
        raise

    digest = sha.hexdigest()

    # ---- sha256 幂等:内容相同视为同一文件 ----
    existing = await db.scalar(select(Document).where(Document.sha256 == digest))
    if existing is not None:
        dest.unlink(missing_ok=True)
        if existing.kb_id != kb_id:
            raise HTTPException(
                status_code=409,
                detail=f"该文件已存在于知识库「{existing.kb_id}」中(sha256 相同)",
            )
        if not replace:
            raise HTTPException(
                status_code=409,
                detail="该文件之前已上传过,请使用「覆盖重传」以更新内容,或删除旧文档后重传",
            )
        # 覆盖:清理旧版本的全部数据,保留原记录并 version+1
        await delete_document(db, existing)

    doc = Document(
        kb_id=kb_id,
        filename=file.filename or dest_name,
        file_type=file_type,
        file_path=dest_name,
        sha256=digest,
        size_bytes=size,
        version=(existing.version + 1) if existing else 1,
    )
    db.add(doc)
    await db.commit()
    await db.refresh(doc)

    ingest_manager.enqueue(doc.id)
    logger.info("文档上传入队: [%s] kb=%s size=%dKB", doc.filename, kb.name, size // 1024)
    return doc


@router.get("/kb/{kb_id}", response_model=list[DocumentOut], summary="知识库文档列表")
async def list_documents(
    kb_id: int,
    status: str | None = Query(None, description="按解析状态过滤:pending/parsing/done/failed"),
    db: AsyncSession = Depends(get_db),
):
    await _get_kb_or_404(db, kb_id)
    stmt = select(Document).where(Document.kb_id == kb_id)
    if status:
        stmt = stmt.where(Document.parse_status == status)
    rows = await db.scalars(stmt.order_by(Document.created_at.desc()))
    return rows.all()


@router.get("/{doc_id}", response_model=DocumentOut, summary="单文档详情(轮询进度用)")
async def get_document(doc_id: int, db: AsyncSession = Depends(get_db)):
    return await _get_doc_or_404(db, doc_id)


@router.post("/{doc_id}/reparse", response_model=DocumentOut, summary="重新解析(失败重试/内容升级)")
async def reparse_document(doc_id: int, db: AsyncSession = Depends(get_db)):
    doc = await _get_doc_or_404(db, doc_id)
    # 清空旧解析产物(向量/FTS/分块),状态复位为 pending 后重新入队;
    # 保留原文件与文档行,因此 sha256 幂等判断仍然有效
    await clear_document_content(db, doc)
    await db.commit()
    ingest_manager.enqueue(doc.id)
    await db.refresh(doc)
    return doc


@router.delete("/{doc_id}", summary="删除文档(向量/分块/文件一并清理)")
async def remove_document(doc_id: int, db: AsyncSession = Depends(get_db)):
    doc = await _get_doc_or_404(db, doc_id)
    await delete_document(db, doc)
    return {"message": "文档已删除"}
