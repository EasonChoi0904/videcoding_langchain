"""知识库接口。

- 管理接口(CRUD/上传/删除…)仅管理员可访问
- 公开只读接口(登录用户可用的知识库名列表,供问答页选择检索范围)
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user, require_admin
from app.db import get_db
from app.models import Chunk, Document, KnowledgeBase, User
from app.schemas.kb import KbCreate, KbOut, KbUpdate
from app.services.document_ops import delete_kb

router = APIRouter(prefix="/kb", tags=["知识库(管理员)"], dependencies=[Depends(require_admin)])
# 登录用户只读路由:必须挂在管理路由之前注册,避免 /kb/{kb_id} 抢先匹配 /kb/public
public_router = APIRouter(prefix="/kb", tags=["知识库(公共)"])


@public_router.get("/public", summary="知识库名列表(登录用户,问答页检索范围选择用)")
async def list_kb_public(db: AsyncSession = Depends(get_db), _user: User = Depends(get_current_user)):
    rows = (
        await db.execute(
            select(KnowledgeBase.id, KnowledgeBase.name).order_by(KnowledgeBase.name.asc())
        )
    ).all()
    return [{"id": kb_id, "name": name} for kb_id, name in rows]


async def _get_kb_or_404(db: AsyncSession, kb_id: int) -> KnowledgeBase:
    kb = await db.get(KnowledgeBase, kb_id)
    if kb is None:
        raise HTTPException(status_code=404, detail="知识库不存在")
    return kb


@router.get("", response_model=list[KbOut], summary="知识库列表(含文档/分块统计)")
async def list_kb(db: AsyncSession = Depends(get_db)):
    rows = await db.scalars(
        select(KnowledgeBase).order_by(KnowledgeBase.updated_at.desc())
    )
    return rows.all()


@router.post("", response_model=KbOut, summary="创建知识库")
async def create_kb(body: KbCreate, db: AsyncSession = Depends(get_db), admin: User = Depends(require_admin)):
    # 同名知识库提示,避免管理员误建重复库
    exists = await db.scalar(select(KnowledgeBase).where(KnowledgeBase.name == body.name))
    if exists:
        raise HTTPException(status_code=409, detail="已存在同名知识库")
    kb = KnowledgeBase(
        name=body.name,
        description=body.description,
        category=body.category,
        created_by=admin.id,
    )
    db.add(kb)
    await db.commit()
    await db.refresh(kb)
    return kb


@router.get("/{kb_id}", response_model=KbOut, summary="知识库详情")
async def get_kb(kb_id: int, db: AsyncSession = Depends(get_db)):
    return await _get_kb_or_404(db, kb_id)


@router.patch("/{kb_id}", response_model=KbOut, summary="更新知识库(名称/描述/类目)")
async def update_kb(kb_id: int, body: KbUpdate, db: AsyncSession = Depends(get_db)):
    kb = await _get_kb_or_404(db, kb_id)
    for field, value in body.model_dump(exclude_none=True).items():
        setattr(kb, field, value)
    await db.commit()
    await db.refresh(kb)
    return kb


@router.delete("/{kb_id}", summary="删除知识库(级联清理文档/分块/向量/缓存)")
async def remove_kb(kb_id: int, db: AsyncSession = Depends(get_db)):
    kb = await _get_kb_or_404(db, kb_id)
    await delete_kb(db, kb)
    return {"message": "知识库已删除"}
