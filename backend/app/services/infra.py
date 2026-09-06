"""基础设施装配:应用启动时依次初始化各部分(幂等)。"""
import logging

from app.core.settings import get_settings

logger = logging.getLogger(__name__)


async def init_infra() -> None:
    """启动装配:数据目录 / 向量集合 / 百炼 API 能力探测。"""
    s = get_settings()
    s.data_dir.mkdir(parents=True, exist_ok=True)
    s.upload_dir.mkdir(parents=True, exist_ok=True)

    # ---- 向量库集合 ----
    from app.services import vector_store

    vector_store.ensure_collections()

    # ---- 百炼 API Key 检查与能力探测(缺 Key 只告警不阻塞启动)----
    if not s.dashscope_api_key:
        logger.warning("未配置 DASHSCOPE_API_KEY,AI 问答/入库向量化将在调用时失败。请在 backend/.env 填写。")
    else:
        from app.rag import provider

        await provider.probe_all()
