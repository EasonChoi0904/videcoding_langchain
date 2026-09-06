"""系统设置接口(仅管理员):动态调整检索/问答参数,改动即时生效。

安全:只开放白名单 key;数值字段做类型校验;不允许任意 key 写入。
"""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import require_admin
from app.db import get_db
from app.models import Setting

router = APIRouter(prefix="/settings", tags=["系统设置(管理员)"], dependencies=[Depends(require_admin)])

# 白名单:key → (中文名, 类型)
SETTING_SCHEMA: dict[str, tuple[str, str]] = {
    "rerank_threshold": ("拒答阈值(0~1)", "float"),
    "rerank_top_n": ("引用片段条数(1~10)", "int"),
    "hybrid_each_top_k": ("混合检索每路召回数(5~100)", "int"),
    "system_prompt": ("系统提示词", "text"),
    "cache_enabled": ("语义缓存开关", "bool"),
}

NUMERIC_RANGES: dict[str, tuple[float, float]] = {
    "rerank_threshold": (0.0, 1.0),
    "rerank_top_n": (1.0, 10.0),
    "hybrid_each_top_k": (5.0, 100.0),
}


class SettingItem(BaseModel):
    """设置项(管理员视图)。"""

    key: str
    value: str
    label: str = Field(default="", description="中文名")
    type: str = Field(default="text", description="float/int/text/bool")
    description: str = Field(default="")
    updated_at: str = Field(default="")
    model_config = {"from_attributes": True}


class SettingUpdate(BaseModel):
    """更新一个设置项。"""

    key: str = Field(..., pattern="^[a-z_]+$")
    value: str = Field(..., max_length=4000)


@router.get("", response_model=list[SettingItem], summary="设置列表(白名单内)")
async def list_settings(db: AsyncSession = Depends(get_db)):
    items = []
    for key, (label, typ) in SETTING_SCHEMA.items():
        row = await db.get(Setting, key)
        items.append(
            SettingItem(
                key=key,
                value=row.value if row else _default_value(key),
                label=label,
                type=typ,
                description=row.description if row else "",
                updated_at=(row.updated_at.isoformat() if row and row.updated_at else ""),
            )
        )
    return items


def _default_value(key: str) -> str:
    from app.core.settings import get_settings

    s = get_settings()
    return {
        "rerank_threshold": str(s.rerank_threshold),
        "rerank_top_n": str(s.rerank_top_n),
        "hybrid_each_top_k": str(s.hybrid_each_top_k),
        "system_prompt": "",
        "cache_enabled": "true",
    }[key]


@router.put("", summary="保存设置(可一次提交多项)")
async def update_settings(
    body: list[SettingUpdate],
    db: AsyncSession = Depends(get_db),
):
    for item in body:
        if item.key not in SETTING_SCHEMA:
            raise HTTPException(status_code=400, detail=f"不允许修改的设置项: {item.key}")
        _label, typ = SETTING_SCHEMA[item.key]
        value = item.value.strip()
        # 类型与范围校验(传非法值直接 400,防止把系统调坏)
        try:
            if typ == "float":
                num = float(value)
                lo, hi = NUMERIC_RANGES[item.key]
                if not (lo <= num <= hi):
                    raise ValueError(f"需在 {lo}~{hi} 之间")
            elif typ == "int":
                num = int(value)
                lo, hi = NUMERIC_RANGES[item.key]
                if not (lo <= num <= hi):
                    raise ValueError(f"需在 {int(lo)}~{int(hi)} 之间")
            elif typ == "bool":
                if value.lower() not in ("true", "false"):
                    raise ValueError("需为 true/false")
            elif typ == "text" and not value:
                raise ValueError("不能为空")
        except ValueError as e:
            raise HTTPException(status_code=400, detail=f"{item.key}: {e}") from None

        row = await db.get(Setting, item.key)
        if row is None:
            db.add(Setting(key=item.key, value=value))
        else:
            row.value = value
    await db.commit()
    return {"message": "设置已保存,即时生效"}
