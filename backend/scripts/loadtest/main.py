# -*- coding: utf-8 -*-
"""压测 CLI 编排入口。

用法(在 backend/ 目录,压测服务器已由 start_*_backend.bat 拉起):
    .venv\\Scripts\\python -m scripts.loadtest.main --scenario setup
    .venv\\Scripts\\python -m scripts.loadtest.main --scenario s0
    .venv\\Scripts\\python -m scripts.loadtest.main --scenario s1 --users 100
    .venv\\Scripts\\python -m scripts.loadtest.main --scenario s5 --duration 600
    .venv\\Scripts\\python -m scripts.loadtest.main --scenario s4 --real   # 真实百炼链路
"""
import argparse
import asyncio
import sys
import time

import httpx

from . import lifecycle as L
from . import metrics as M
from . import questions as Q
from . import report as R
from . import seeding
from . import users as user_mod
from .config import API_BASE, SCENARIOS, USER_PASS

try:
    sys.stdout.reconfigure(encoding="utf-8")  # Windows 控制台 utf-8 输出
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:  # noqa: BLE001
    pass


async def _health(base: str) -> bool:
    try:
        async with httpx.AsyncClient(timeout=5.0) as c:
            r = await c.get(f"{base}/health")
            return r.status_code == 200
    except Exception:  # noqa: BLE001
        return False


async def _check_mock_server() -> None:
    """--expect-mock 时校验服务器确为 mock 模式(读 server.log 的 ASCII 标记)。"""
    import os

    from .config import BACKEND_DIR

    data_dir = os.getenv("DATA_DIR", str(BACKEND_DIR / "data" / "_loadtest"))
    log_path = os.path.join(data_dir, "server.log")
    if not os.path.exists(log_path):
        print("[warn] 未找到 server.log,跳过 mock 校验(确保服务器是 mock 模式启动)")
        return
    with open(log_path, encoding="utf-8", errors="replace") as f:
        content = f.read()
    if "mock provider" not in content:
        raise SystemExit("server.log 中没有 mock provider 安装标记——服务器不是 mock 模式,中止!")


async def s4_real(base: str, opts: dict) -> None:
    """S4 真实链路冒烟:快照库 + 少量新账号 + 真实题库;总 ask 硬上限 150。"""
    cap = 150
    sent = 0
    lock = asyncio.Lock()

    # 在快照库上注册 5 个新用户(默认限流 10/h/IP 内,安全)
    names = [f"lt_real_{i:02d}" for i in range(5)]
    accounts: list[user_mod.Account] = []
    async with httpx.AsyncClient(timeout=30.0) as c:
        for n in names:
            await user_mod.register(c, base, n, USER_PASS)
            pair = await user_mod.login(c, base, n, USER_PASS)
            acc = user_mod.Account(n, USER_PASS)
            acc.set_tokens(pair)
            accounts.append(acc)

    # 预热自检:真实题 10 问,要求 ≥8 命中 citations(命中差说明快照库无演示数据)
    print("[s4] 预热自检(10 问验证检索可用)…")
    vu = L.Vu(base, accounts[0], time.monotonic() + 600)
    hit = 0
    try:
        await vu.ensure_conv()
        for q in Q.real_warmup():
            rec = await vu.ask(q)
            if "citations" in rec["events"] and rec["cls"] == "ok":
                hit += 1
            if rec["cls"] not in ("ok",):
                print(f"  [s4] 预热异常 {rec['cls']}: {rec['error'][:120]}")
        print(f"  [s4] 预热命中 {hit}/10" + ("" if hit >= 8 else "  ← 命中偏低,请检查快照库内容!"))
    finally:
        await vu.close()
    M.reset()

    # 正式冒烟:5 VU × 节流 12/min(真实链路慢,预算要低),总量 ≤150
    async def asker(acc: user_mod.Account, idx: int) -> None:
        nonlocal sent
        v = L.Vu(base, acc, time.monotonic() + opts["duration"])
        v._next_ask_at = time.monotonic()
        pool = Q.pick_pool(9999, mode="real", seed=idx)
        qi = 0
        try:
            await v.ensure_conv()
            while time.monotonic() < v.deadline:
                async with lock:
                    if sent >= cap:
                        return
                    sent += 1
                rec = await v.ask(pool[qi % len(pool)])
                qi += 1
                await asyncio.sleep(2.0 + v.rnd.random() * 3)
        finally:
            await v.close()

    await L._run_vus(accounts[: opts["users"]], asker, opts)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="RAG 系统压测器(100 并发模拟)")
    p.add_argument("--scenario", default="s0",
                   choices=["setup", "s0", "s1", "s2", "s3", "s4", "s5", "s6"],
                   help="场景(setup=造数; s4=真实链路冒烟)")
    p.add_argument("--users", type=int, default=0, help="虚拟用户数(默认按场景)")
    p.add_argument("--duration", type=int, default=0, help="稳态时长秒(默认按场景)")
    p.add_argument("--ramp-per-sec", type=int, default=0, dest="ramp", help="起压斜率(默认按场景)")
    p.add_argument("--base-url", default=API_BASE, dest="base", help="后端 API 地址")
    p.add_argument("--expect-mock", action="store_true", help="断言服务器为 mock 模式")
    p.add_argument("--real", action="store_true", help="真实百炼链路模式(s4 用)")
    return p


async def main() -> None:
    args = build_parser().parse_args()
    base = args.base
    sc = args.scenario

    if not await _health(base):
        raise SystemExit(f"服务器不可达: {base}/health —— 请先启动压测服务器(start_*_backend.bat)")

    if sc == "s4" or args.real:
        # 真实链路:不放大限流、不造数;直接走 s4_real
        opts = {"users": args.users or 5, "duration": args.duration or 240,
                "ramp_per_sec": args.ramp or 1}
        print(f"[s4] 真实百炼链路冒烟: {opts['users']} VU × {opts['duration']}s (总量 ≤150 asks)")
        await s4_real(base, opts)
        health = await M.stop_health_probe()
        R.finalize({"scenario": "s4", "real_api": True, "opts": opts}, health, tag=f"s4-real-{int(time.time())}")
        return

    if args.expect_mock:
        await _check_mock_server()

    accounts = user_mod.load_accounts()
    if not accounts and sc != "setup":
        print("[main] 未发现账号表,先执行造数(setup)…")
        accounts = await seeding.run_setup(base)
    if sc == "setup":
        await seeding.run_setup(base)
        return

    cfg = SCENARIOS.get(sc, SCENARIOS["s0"])
    opts = {
        "users": args.users or cfg["users"],
        "duration": args.duration or cfg["duration"],
        "ramp_per_sec": args.ramp or cfg["ramp_per_sec"],
        "with_register": True,
    }
    # 账号不足时补齐(一般不会)
    while len(accounts) < opts["users"]:
        more = await user_mod.seed_accounts(base, opts["users"] - len(accounts), USER_PASS)
        accounts.extend(more)

    print(f"[{sc}] {cfg['desc']}: {opts['users']} VU × {opts['duration']}s ramp={opts['ramp_per_sec']}/s")
    t0 = time.monotonic()
    await M.start_health_probe(base.replace("/api", ""))
    runner = {
        "s0": lambda: L.s0_calibrate(base, accounts[0], opts),
        "s1": lambda: L.s1_login_storm(base, accounts, opts),
        "s2": lambda: L.s2_readers(base, accounts, opts),
        "s3": lambda: L.s3_askers(base, accounts, opts),
        "s5": lambda: L.s5_journey(base, accounts, opts),
        "s6": lambda: L.s6_uploaders(base, accounts, opts),
    }[sc]
    await runner()
    health = await M.stop_health_probe()
    print(f"[{sc}] 执行结束,耗时 {time.monotonic() - t0:.0f}s,正在汇总…")
    meta = {"scenario": sc, "users": opts["users"], "duration": opts["duration"],
            "mock": True, "server": base}
    R.finalize(meta, health, tag=f"{sc}-{opts['users']}u-{int(time.time())}")


if __name__ == "__main__":
    asyncio.run(main())
