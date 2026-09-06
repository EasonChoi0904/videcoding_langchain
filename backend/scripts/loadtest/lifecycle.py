# -*- coding: utf-8 -*-
"""场景执行:各场景的虚拟用户(VU)行为循环。

约定:每个 VU 独占一个账号 + 一个 httpx 客户端;所有请求经 metrics.record
记录(op/分类/延迟);ask 走 sse_client.ask_sse 并按 18/min/用户节流(产品限流 20/min)。
"""
import asyncio
import random
import time

import httpx

from . import metrics as M
from . import questions as Q
from .config import ASK_BUDGET_PER_MIN, THINK_MEAN_SECONDS
from .seeding import LOADTEST_KB, make_unique_doc_text
from . import users as user_mod
from .sse_client import ask_sse
from .users import Account


def _unwrap_list(body) -> list:
    """兼容消息/会话接口的三种响应形态:裸列表 / {messages:[]} / {items:[]}。"""
    if isinstance(body, list):
        return body
    if isinstance(body, dict):
        for k in ("messages", "items", "conversations"):
            if isinstance(body.get(k), list):
                return body[k]
    return []


# ---------- 公共工具 ----------


class Vu:
    """单个虚拟用户的运行时上下文。"""

    def __init__(self, base: str, account: Account, deadline: float):
        self.base = base
        self.acc = account
        self.deadline = deadline
        self.client = httpx.AsyncClient(timeout=45.0)
        self.conv_id: int | None = None
        self.ask_count = 0
        self._next_ask_at = time.monotonic()
        self.rnd = random.Random()

    async def close(self) -> None:
        await self.client.aclose()

    async def http(self, op: str, method: str, url: str, **kw):
        """带鉴权的 HTTP 请求并记录指标(含 401→refresh 重试)。"""
        t0 = time.monotonic()
        res = await self.acc.request(self.client, self.base, method, url, **kw)
        ms = (time.monotonic() - t0) * 1000
        cls = res["cls"]
        if res["status"] == 429:
            cls = "429"
        elif res["status"] is not None and res["status"] >= 500:
            cls = "5xx"
        elif res["status"] is not None and res["status"] >= 400 and cls == "ok":
            cls = "4xx"
        await M.record(op, cls, res["status"], ms, extra=res.get("err", ""))
        return res

    async def ask(self, question: str, kb_id: int | None = None, op: str = "ask",
                  budget_per_min: float = ASK_BUDGET_PER_MIN) -> dict:
        """一次带节流的流式问答(记录全部时间轴指标)。

        Args:
            budget_per_min: 每分钟提问预算(s0 校准等可临时放宽到 120)
        """
        # 节流:距离上次允许时刻不足则等待到点(桶空由调用方改选其它动作)
        now = time.monotonic()
        if now < self._next_ask_at:
            await asyncio.sleep(self._next_ask_at - now)
        rec = await ask_sse(
            self.client, self.base, self.conv_id, self.acc.access, question, kb_id
        )
        interval = 60.0 / max(budget_per_min, 1e-6)
        self._next_ask_at = time.monotonic() + interval * (0.8 + self.rnd.random() * 0.4)
        self.ask_count += 1
        await M.record(
            op, rec["cls"], rec["http"], rec["total_ms"],
            extra=rec["error"][:150],
            ttfb_ms=rec["t_first_token"],
            tokens=rec["tokens"],
        )
        return rec

    async def ensure_conv(self) -> int:
        """取当前会话,没有则新建并记录。"""
        if self.conv_id is not None:
            return self.conv_id
        res = await self.http("new_conv", "POST", "/conversations", json={"language": "zh"})
        if res["status"] == 200 and res["json"]:
            self.conv_id = res["json"]["id"]
        return self.conv_id if self.conv_id is not None else 0

    async def list_convs(self) -> list[int]:
        """拉会话列表并缓存最新会话 id(兼容列表/包装对象两种响应形态)。"""
        res = await self.http("list_convs", "GET", "/conversations")
        ids = []
        data = res["json"] if isinstance(res["json"], list) else (res["json"] or {}).get("items", [])
        if res["status"] == 200:
            for c in data:
                if isinstance(c, dict):
                    ids.append(c.get("id"))
            if ids and self.conv_id not in ids:
                self.conv_id = ids[0]
        return ids


# ---------- 各场景 VU 主体 ----------


async def s0_calibrate(base: str, account: Account, opts: dict) -> None:
    """S0 校准:单 VU 连续 30 问,输出基线。"""
    vu = Vu(base, account, time.monotonic() + 9999)
    try:
        await vu.ensure_conv()
        # 保持产品限流 20/min,校准同样遵守客户端节流(25 问 ≈ 90s)
        pool = Q.pick_pool(25, seed=1)
        for q in pool:
            rec = await vu.ask(q)
            if rec["cls"] != "ok":
                print(f"  [s0] 异常:{rec['cls']} {rec['error'][:100]}")
    finally:
        await vu.close()


async def s1_login_storm(base: str, accounts: list[Account], opts: dict) -> None:
    """S1 登录风暴:每 VU 登录一次,10% 额外注册一次(bcrypt-12 是观测对象)。"""

    async def one(acc: Account, idx: int) -> None:
        async with httpx.AsyncClient(timeout=45.0) as c:
            from .users import login as _login
            from .users import register as _register

            if opts.get("with_register") and idx % 10 == 0:
                # 注册也是 bcrypt-12 观测对象;409(重跑已存在)视为成功;网络失败单列
                t0 = time.monotonic()
                code = await _register(c, base, f"{acc.username}_r", acc.password)
                ms = (time.monotonic() - t0) * 1000
                if code == 0:
                    cls, shown = "connect_error", None
                elif code in (200, 201, 409):
                    cls, shown = "ok", code
                elif code == 429:
                    cls, shown = "429", code
                elif code >= 500:
                    cls, shown = "5xx", code
                else:
                    cls, shown = "4xx", code
                await M.record("register", cls, shown, ms)
            t0 = time.monotonic()
            pair = await _login(c, base, acc.username, acc.password)
            ms = (time.monotonic() - t0) * 1000
            cls = "ok" if pair else "auth_fail"
            await M.record("login", cls, 200 if pair else None, ms)

    await _run_vus(accounts, one, opts)


async def s2_readers(base: str, accounts: list[Account], opts: dict) -> None:
    """S2 读操作:会话/消息/知识库/导出/me 轮转(admin 用户加打 stats)。"""

    async def one(acc: Account, idx: int) -> None:
        vu = Vu(base, acc, time.monotonic() + opts["duration"])
        try:
            await vu.ensure_conv()
            rnd = vu.rnd
            while time.monotonic() < vu.deadline:
                roll = rnd.random()
                if roll < 0.4:
                    await vu.list_convs()
                elif roll < 0.65:
                    cid = vu.conv_id or await vu.ensure_conv()
                    await vu.http("list_messages", "GET", f"/conversations/{cid}/messages")
                elif roll < 0.75:
                    await vu.http("list_kbs", "GET", "/kb/public")
                elif roll < 0.85:
                    await vu.http("auth_me", "GET", "/auth/me")
                elif roll < 0.95:
                    cid = vu.conv_id or await vu.ensure_conv()
                    await vu.http("export", "GET", f"/conversations/{cid}/export")
                else:
                    cid = vu.conv_id or await vu.ensure_conv()
                    await vu.http(
                        "list_messages", "GET", f"/conversations/{cid}/messages", params={"limit": 50}
                    )
                if acc.role == "admin" and int(time.monotonic()) % 5 == 0:
                    await vu.http("stats", "GET", "/admin/stats")
                await asyncio.sleep(rnd.uniform(0.05, 0.4))
        finally:
            await vu.close()

    await _run_vus(accounts, one, opts)


async def s3_askers(base: str, accounts: list[Account], opts: dict) -> None:
    """S3 mock 问答主场景:每人 1 会话起步,≤18/min 连续 ask,每 10 问换会话。"""

    async def one(acc: Account, idx: int) -> None:
        vu = Vu(base, acc, time.monotonic() + opts["duration"])
        pool = Q.pick_pool(9999, seed=idx)
        qi = 0
        try:
            await vu.ensure_conv()
            while time.monotonic() < vu.deadline:
                rec = await vu.ask(pool[qi % len(pool)])
                qi += 1
                if rec["cls"] == "429":
                    # 客户端节流失效信号:降速并记录(不应发生)
                    await asyncio.sleep(5)
                if vu.ask_count % 3 == 0:  # 模拟前端收尾
                    cid = vu.conv_id or 0
                    if cid:
                        await vu.http("list_messages", "GET", f"/conversations/{cid}/messages")
                        await vu.list_convs()
                if vu.ask_count % 10 == 0:  # 每 10 问换新会话(触发语义缓存首问路径)
                    res = await vu.http("new_conv", "POST", "/conversations", json={"language": "zh"})
                    if res["status"] == 200:
                        vu.conv_id = res["json"]["id"]
                await asyncio.sleep(vu.rnd.uniform(0.1, 0.5))
        finally:
            await vu.close()

    await _run_vus(accounts, one, opts)


async def s5_journey(base: str, accounts: list[Account], opts: dict) -> None:
    """S5 混合旅程:按概率表抽动作 + 指数思考间隔,贴近真实使用。"""

    async def one(acc: Account, idx: int) -> None:
        vu = Vu(base, acc, time.monotonic() + opts["duration"])
        reg_n = [0]  # 本 VU 的注册序号(生成唯一新用户名,避免跨轮重名)
        try:
            await vu.ensure_conv()
            while time.monotonic() < vu.deadline:
                # 思考间隔(指数分布,均值 4s,封顶 20s)
                await asyncio.sleep(min(random.expovariate(1 / THINK_MEAN_SECONDS), 20))
                roll = vu.rnd.random() * 100
                # 分支边界与 config.MIX_S5_CUMULATIVE 一一对应(合计 100)
                if roll < 34:
                    # ask 桶空时自动改选读操作
                    if time.monotonic() < vu._next_ask_at:
                        await vu.list_convs()
                    else:
                        q = Q.pick_pool(1, seed=int(time.time()))[0]
                        kb_id = None
                        if vu.rnd.random() < 0.6:
                            res = await vu.http("list_kbs", "GET", "/kb/public")
                            if res["status"] == 200 and res["json"]:
                                kb_id = vu.rnd.choice(res["json"]).get("id")
                        await vu.ask(q, kb_id)
                elif roll < 48:
                    await vu.list_convs()
                elif roll < 69:
                    cid = vu.conv_id or await vu.ensure_conv()
                    await vu.http("list_messages", "GET", f"/conversations/{cid}/messages")
                elif roll < 78:
                    res = await vu.http("new_conv", "POST", "/conversations", json={"language": "zh"})
                    if res["status"] == 200:
                        vu.conv_id = res["json"]["id"]
                elif roll < 87:
                    await vu.http("list_kbs", "GET", "/kb/public")
                elif roll < 91:
                    # 存量用户重登:成功则换新令牌继续(bcrypt 成本混入混合流,观测口径同 S1)
                    t0 = time.monotonic()
                    pair = await user_mod.login(vu.client, base, acc.username, acc.password)
                    await M.record("login", "ok" if pair else "auth_fail", 200 if pair else None,
                                   (time.monotonic() - t0) * 1000)
                    if pair:
                        acc.set_tokens(pair)
                elif roll < 93:
                    # 新用户注册访问:仅测注册接口不切换身份;409(重跑同名)=视为成功
                    reg_n[0] += 1
                    name = f"n{idx:02d}r{reg_n[0]:03d}"
                    t0 = time.monotonic()
                    code = await user_mod.register(vu.client, base, name, acc.password)
                    ms = (time.monotonic() - t0) * 1000
                    if code in (200, 201, 409):
                        cls, shown = "ok", code
                    elif code == 0:
                        cls, shown = "connect_error", None
                    elif code == 429:
                        cls, shown = "429", code
                    elif code >= 500:
                        cls, shown = "5xx", code
                    else:
                        cls, shown = "4xx", code
                    await M.record("register", cls, shown, ms)
                elif roll < 96:
                    await vu.http("auth_me", "GET", "/auth/me")
                elif roll < 98:
                    cid = vu.conv_id or await vu.ensure_conv()
                    r = await vu.http("list_messages", "GET", f"/conversations/{cid}/messages")
                    data = _unwrap_list(r["json"])
                    if r["status"] == 200 and data:
                        msgs = [m for m in data if isinstance(m, dict)]
                        last = next((m for m in msgs if m.get("role") == "assistant"), None)
                        if last:
                            await vu.http(
                                "feedback", "POST", f"/messages/{last['id']}/feedback",
                                json={"value": 1 if vu.rnd.random() < 0.7 else -1},
                            )
                else:  # 改名会话
                    cid = vu.conv_id or await vu.ensure_conv()
                    if cid:
                        await vu.http(
                            "rename_conv", "PATCH", f"/conversations/{cid}",
                            json={"title": f"会话-{int(time.time()) % 100000}"},
                        )
                if acc.role == "admin" and int(time.monotonic()) % 5 == 0:
                    await vu.http("stats", "GET", "/admin/stats")
        finally:
            await vu.close()

    await _run_vus(accounts, one, opts)


async def s6_uploaders(base: str, accounts: list[Account], opts: dict) -> None:
    """S6 上传风暴:admin 持续上传唯一 txt + 全员 2s 轮询解析进度。"""

    async def one(acc: Account, idx: int) -> None:
        if acc.role != "admin":
            return
        vu = Vu(base, acc, time.monotonic() + opts["duration"])
        kb_id = None
        try:
            # 找压测库
            res = await vu.http("list_kbs_admin", "GET", "/kb")
            if res["status"] == 200:
                for kb in res["json"] or []:
                    if kb["name"] == LOADTEST_KB:
                        kb_id = kb["id"]
                        break
            while time.monotonic() < vu.deadline:
                if kb_id:
                    name, content = make_unique_doc_text()
                    t0 = time.monotonic()
                    rr = await vu.acc.request(
                        vu.client, base, "POST", f"/documents/kb/{kb_id}/upload",
                        params={"replace": "false"},
                        files={"file": (name, content, "text/plain")},
                    )
                    await M.record("upload", rr["cls"], rr["status"], (time.monotonic() - t0) * 1000)
                    await vu.http("docs_list", "GET", f"/documents/kb/{kb_id}")
                await asyncio.sleep(1.0 + vu.rnd.random())
        finally:
            await vu.close()

    await _run_vus(accounts, one, opts)


# ---------- 公共调度 ----------


async def _run_vus(accounts: list[Account], coro_fn, opts: dict) -> None:
    """按 ramp 斜率错峰启动 VU,等待全部结束。"""
    ramp = opts.get("ramp_per_sec", 25)
    delay = 1.0 / max(ramp, 0.001)
    tasks = []
    for i, acc in enumerate(accounts[: opts["users"]]):
        if i > 0:
            await asyncio.sleep(delay)
        tasks.append(asyncio.create_task(coro_fn(acc, i)))
    await asyncio.gather(*tasks)
