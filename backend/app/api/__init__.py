"""API 路由聚合。各里程碑新增的路由在此挂载。"""
from fastapi import APIRouter

from app.api import (
    auth,
    chat,
    chunks,
    conversations,
    debug,
    documents,
    kb,
    settings_api,
    stats,
)

api_router = APIRouter()
api_router.include_router(auth.router, prefix="/auth", tags=["认证"])
# 公共知识库只读路由必须排在管理路由之前(避免 /kb/{kb_id} 抢先匹配 /kb/public)
api_router.include_router(kb.public_router)
api_router.include_router(kb.router, tags=["知识库(管理员)"])
api_router.include_router(documents.router, tags=["文档解析(管理员)"])
api_router.include_router(chunks.router, tags=["分块(管理员)"])
api_router.include_router(debug.router, tags=["检索调试(管理员)"])
api_router.include_router(conversations.router)
api_router.include_router(chat.router)
api_router.include_router(settings_api.router)
api_router.include_router(stats.router)
