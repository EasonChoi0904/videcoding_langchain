# -*- coding: utf-8 -*-
"""数据准备:演示知识库灌入 + 100 用户造数 + admin 角色提升。

全程走 HTTP(与真实用户一致);压测服务器应指向临时 DATA_DIR(data/_loadtest)。
"""
import asyncio
import os
import sqlite3
import time
import uuid

import httpx

from . import users as user_mod
from .config import (
    ADMIN_PASS,
    ADMIN_SLOTS,
    ADMIN_USER,
    BACKEND_DIR,
    UPLOAD_DOC_CHARS,
    USER_COUNT,
    USER_PASS,
)

LOADTEST_KB = "压测演示库"


def _db_path() -> str:
    """临时压测库的 SQLite 路径(与 loadtest_env.bat 的 DATA_DIR 保持一致)。"""
    data_dir = os.getenv("DATA_DIR", str(BACKEND_DIR / "data" / "_loadtest"))
    return os.path.join(data_dir, "app.db")


async def ensure_demo_kb(client: httpx.AsyncClient, base: str, headers: dict) -> int:
    """找/建压测知识库,必要时上传 demo_files 四份文档并等待解析完成。"""
    r = await client.get(f"{base}/kb", headers=headers)
    for kb in r.json():
        if kb["name"] == LOADTEST_KB:
            return kb["id"]

    r = await client.post(f"{base}/kb", json={"name": LOADTEST_KB, "description": "压测用演示知识库(手机+家电)"}, headers=headers)
    kb_id = r.json()["id"]

    demo_dir = BACKEND_DIR / "scripts" / "demo_files"
    uploaded = []
    for f in demo_dir.iterdir():
        if not f.is_file():
            continue
        with open(f, "rb") as fh:
            rr = await client.post(
                f"{base}/documents/kb/{kb_id}/upload",
                params={"replace": "false"},
                files={"file": (f.name, fh, "application/octet-stream")},
                headers=headers,
            )
        if rr.status_code == 200:
            uploaded.append(rr.json()["id"])

    # 轮询到全部解析完成(mock embedding 免费,一般 10s 内)
    deadline = time.time() + 120
    done_ids: set[int] = set()
    while time.time() < deadline and not set(uploaded) <= done_ids:
        r = await client.get(f"{base}/documents/kb/{kb_id}", headers=headers)
        for d in r.json():
            if d["parse_status"] in ("done", "failed"):
                done_ids.add(d["id"])
                assert d["parse_status"] == "done", f"文档解析失败: {d.get('error_msg')}"
        await asyncio.sleep(0.5)
    assert set(uploaded) <= done_ids, "演示文档解析超时"
    return kb_id


async def promote_admin_slots() -> None:
    """把前两个普通账号直插 DB 提升为 admin(S5/S6 管理场景用,角色是 RBAC 唯一依据)。"""
    db = _db_path()
    conn = sqlite3.connect(db)
    try:
        names = [f"lt_u{i:04d}" for i in ADMIN_SLOTS]
        conn.execute(
            f"UPDATE users SET role='admin' WHERE username IN ({','.join('?' * len(names))})",
            names,
        )
        conn.commit()
    finally:
        conn.close()


async def run_setup(base: str) -> list[user_mod.Account]:
    """完整造数流程:灌库 → 注册登录 100 用户 → 提权 → 账号落盘。"""
    async with httpx.AsyncClient(timeout=60.0) as c:
        # 管理员(种子账号 admin/123456,由服务启动时创建)
        pair = await user_mod.login(c, base, ADMIN_USER, ADMIN_PASS)
        assert pair, "admin 登录失败——压测服务器是否已就绪?"
        admin = user_mod.Account(ADMIN_USER, ADMIN_PASS, role="admin")
        admin.set_tokens(pair)

        print("[setup] 灌入演示知识库…")
        await ensure_demo_kb(c, base, {"Authorization": f"Bearer {pair['access']}"})

        print(f"[setup] 注册并登录 {USER_COUNT} 个压测用户…")
        accounts = await user_mod.seed_accounts(base, USER_COUNT, USER_PASS)

    await promote_admin_slots()
    for acc in accounts:
        if acc.username in {f"lt_u{i:04d}" for i in ADMIN_SLOTS}:
            acc.role = "admin"
    user_mod.save_accounts(accounts)
    print(f"[setup] 完成:知识库已灌入,{len(accounts)} 账号就绪(含 {len(ADMIN_SLOTS)} 个 admin)")
    return accounts


def make_unique_doc_text() -> tuple[str, bytes]:
    """生成内容唯一的 txt 文档(sha256 不重复,避免 409;总字符数≈UPLOAD_DOC_CHARS≈16 分块)。"""
    tag = uuid.uuid4().hex
    line = (
        f"压测素材文档 {tag}:手机商品参数表,华为Mate60Pro 支持卫星通话与5G网络,"
        f"5000mAh电池,昆仑玻璃。\n"
    )
    repeat = max(1, UPLOAD_DOC_CHARS // max(len(line), 1) + 1)
    text = (line * repeat)[:UPLOAD_DOC_CHARS]
    return f"loadtest_{tag}.txt", text.encode("utf-8")
