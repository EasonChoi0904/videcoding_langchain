# -*- coding: utf-8 -*-
"""账号层:注册/登录/refresh 轮换/401 重试。每虚拟用户独占一个账号。"""
import asyncio
import json

import httpx

from .config import ACCOUNTS_FILE


async def register(client: httpx.AsyncClient, base: str, username: str, password: str) -> int:
    """注册一个新账号,返回 HTTP 状态码(0=网络层失败)。

    Notes:
        200/201=新建成功;409=同名已存在(等价成功,供重跑复用);调用方自行归类。
    """
    try:
        r = await client.post(f"{base}/auth/register", json={"username": username, "password": password})
        return r.status_code
    except Exception:  # noqa: BLE001
        return 0


async def login(client: httpx.AsyncClient, base: str, username: str, password: str) -> dict | None:
    """登录,返回 {access, refresh} 或 None(网络/凭据错误时由调用方分类)。"""
    try:
        r = await client.post(f"{base}/auth/login", json={"username": username, "password": password})
        if r.status_code == 200:
            d = r.json()
            return {"access": d["access_token"], "refresh": d["refresh_token"]}
        return None
    except Exception:  # noqa: BLE001
        return None


async def refresh(client: httpx.AsyncClient, base: str, refresh_token: str) -> dict | None:
    """用 refresh 换新 token 对(后端轮换制,旧 refresh 即刻吊销)。"""
    try:
        r = await client.post(f"{base}/auth/refresh", json={"refresh_token": refresh_token})
        if r.status_code == 200:
            d = r.json()
            return {"access": d["access_token"], "refresh": d["refresh_token"]}
        return None
    except Exception:  # noqa: BLE001
        return None


class Account:
    """虚拟用户账号:独占令牌,支持 401→refresh→重试 与整 VU 重登录。"""

    def __init__(self, username: str, password: str, role: str = "user"):
        self.username = username
        self.password = password
        self.role = role
        self.access = ""
        self.refresh_tok = ""
        self.reauth_count = 0

    def set_tokens(self, pair: dict | None) -> None:
        if pair:
            self.access, self.refresh_tok = pair["access"], pair["refresh"]

    async def request(self, client: httpx.AsyncClient, base: str, method: str, url: str, **kw) -> dict:
        """带鉴权的请求:401 → refresh 一次重放 → 仍失败整 VU 重登录再重放一次。

        Returns: {"status": int|None, "json": dict|list|None, "cls": 成功时"ok"}
        """
        for _ in range(3):
            if not self.access:
                self.set_tokens(await login(client, base, self.username, self.password))
                if not self.access:
                    return {"status": None, "json": None, "cls": "auth_fail"}
            try:
                r = await client.request(
                    method, f"{base}{url}",
                    headers={"Authorization": f"Bearer {self.access}"}, **kw,
                )
            except Exception as e:  # noqa: BLE001
                return {"status": None, "json": None, "cls": "connect_error", "err": str(e)[:150]}
            if r.status_code != 401:
                return {"status": r.status_code, "json": self._body(r), "cls": "ok"}
            # 401:先 refresh 一次,失败则整账号重登录
            new_pair = await refresh(client, base, self.refresh_tok) if self.refresh_tok else None
            if new_pair:
                self.set_tokens(new_pair)
                continue
            self.reauth_count += 1
            self.access = ""
            self.set_tokens(await login(client, base, self.username, self.password))
        return {"status": 401, "json": None, "cls": "auth_fail"}

    @staticmethod
    def _body(r: httpx.Response):
        try:
            return r.json()
        except Exception:  # noqa: BLE001
            return None


def save_accounts(accounts: list[Account]) -> None:
    """账号表落盘(含角色与令牌,供跨进程/续跑复用)。"""
    data = {
        a.username: {"password": a.password, "role": a.role, "access": a.access, "refresh": a.refresh_tok}
        for a in accounts
    }
    ACCOUNTS_FILE.parent.mkdir(parents=True, exist_ok=True)
    ACCOUNTS_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def load_accounts() -> list[Account]:
    """从磁盘恢复账号池(令牌可能过期,request() 会自动刷新/重登)。"""
    if not ACCOUNTS_FILE.exists():
        return []
    data = json.loads(ACCOUNTS_FILE.read_text(encoding="utf-8"))
    out = []
    for name, d in data.items():
        a = Account(name, d["password"], d.get("role", "user"))
        a.set_tokens({"access": d.get("access", ""), "refresh": d.get("refresh", "")})
        out.append(a)
    return out


async def seed_accounts(base: str, count: int, password: str, per_sec: float = 5.0) -> list[Account]:
    """慢速注册 count 个账号并各自登录一次(避开 bcrypt 混入场景计时)。"""
    accounts: list[Account] = []
    async with httpx.AsyncClient(timeout=30.0) as c:
        for i in range(1, count + 1):
            name = f"lt_u{i:04d}"
            # 409=同名已存在(库未清的重跑),同样视为就绪;注册失败仅告警不中断
            code = await register(c, base, name, password)
            if code not in (200, 201, 409) and code != 0:
                print(f"  [setup] 注册 {name} 返回 {code},继续尝试登录…")
            pair = await login(c, base, name, password)
            acc = Account(name, password)
            acc.set_tokens(pair)
            accounts.append(acc)
            if i % per_sec == 0:
                await asyncio.sleep(1.0)
    return accounts
