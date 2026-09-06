# -*- coding: utf-8 -*-
"""手动压测向导:自动起/停 mock 服务器、自动造数、交互选场景、自动打开 HTML 报告。

入口:backend 目录下  .venv\\Scripts\\python -m scripts.loadtest.main --manual
或双击 scripts\\loadtest\\manual_test.bat
"""
import asyncio
import os
import time

from . import seeding
from . import server_mgr
from . import users as user_mod
from .config import API_BASE, REPORT_ROOT, SCENARIOS, USER_PASS
from .main import build_parser, run_scenario

SCENARIO_NAMES = {
    "s0": "校准冒烟(1 人连续问答,约 90s)",
    "s1": "登录风暴(100 人同时登录)",
    "s2": "读操作并发(会话/消息/知识库浏览)",
    "s3": "mock 问答 100 并发(主场景,默认 5 分钟)",
    "s5": "混合用户旅程 100 人(问答+浏览+管理,默认 5 分钟)",
    "s6": "上传风暴(admin 持续上传,可选)",
    "s4": "真实百炼链路冒烟(需快照库,指引式)",
}

SCENARIO_DEFAULT_DURATION = {"s1": 60, "s2": 180, "s3": 300, "s5": 300, "s6": 120}


def _ask(text: str, default: str = "") -> str:
    """带默认值的交互输入(回车=默认)。"""
    if default:
        prompt = f"{text}[默认 {default}]: "
    else:
        prompt = f"{text}: "
    try:
        return input(prompt).strip() or default
    except EOFError:
        return default


def _open_html(tag: str) -> None:
    """尽力用系统默认浏览器打开 HTML 报告(失败仅提示不报错)。"""
    path = REPORT_ROOT / tag / "index.html"
    if path.exists():
        print(f"\n▶ HTML 报告: {path}")
        try:
            os.startfile(str(path))  # noqa: S606 Windows 专用
        except Exception as e:  # noqa: BLE001
            print(f"(自动打开失败,可手动双击上述文件: {e})")


async def _ensure_mock_ready() -> None:
    """向导启动:按需拉起全新 mock 服务器并造数。"""
    if not await server_mgr.is_healthy():
        print("[向导] 未检测到压测服务器,自动启动全新 mock 服务器(临时库,约 15s)…")
        server_mgr.start_mock_server(wipe=True)
        if not await server_mgr.wait_ready():
            raise SystemExit("mock 服务器启动失败,请查看 data/_loadtest/server.log")
        print("[向导] 服务器就绪(mock 模式)")
    # 全新库必然无账号 → 自动造数
    if not user_mod.load_accounts():
        print("[向导] 未发现账号数据,自动造数(演示知识库 + 100 账号,约 40s)…")
        await seeding.run_setup(API_BASE)


async def wizard(_args) -> None:
    """交互向导主循环。"""
    print("=" * 60)
    print("  RAG 系统压测向导(手动执行)")
    print("  场景: s0 校准 / s1 登录 / s2 读并发 / s3 问答 100 并发 / s5 混合旅程 / s4 真实链路")
    print("=" * 60)

    mode = _ask("服务器模式", "A").upper()
    if mode == "A":
        await _ensure_mock_ready()
    elif mode == "U":
        if not await server_mgr.is_healthy():
            print("! 未检测到运行中的服务器,请先启动(start_mock_backend.bat 或 start_real_backend.bat)")
            return
        print("[向导] 使用当前运行中的服务器")
    else:
        return

    while True:
        print("\n可选场景:")
        for k, v in SCENARIO_NAMES.items():
            print(f"  {k}  {v}")
        print("  q   退出")
        sc = _ask("输入场景", "").lower()
        if sc in ("q", "quit", "exit", ""):
            break
        if sc == "s4":
            print("\nS4 真实链路需准备快照库(停开发后端后复制 data → data\\_loadtest_snapshot),")
            print("再执行 start_real_backend.bat 与:")
            print("  .venv\\Scripts\\python -m scripts.loadtest.main --scenario s4 --real")
            print("(烧少量百炼额度,总量 ≤150 asks;步骤详见 scripts/loadtest/README.md)")
            continue
        if sc not in SCENARIO_NAMES:
            print(f"! 未知场景 {sc},请重新输入")
            continue
        if sc not in ("s0",) and mode == "A" and not await server_mgr.is_healthy():
            print("! 服务器掉线,尝试重启…")
            server_mgr.start_mock_server(wipe=False)
            if not await server_mgr.wait_ready():
                print("! 重启失败,退出向导")
                break

        # 收集参数(回车用默认)
        cfg = SCENARIOS.get(sc, SCENARIOS["s0"])
        users = int(_ask("虚拟用户数", str(cfg["users"])) or cfg["users"])
        dur = int(_ask("时长(秒)", str(SCENARIO_DEFAULT_DURATION.get(sc, cfg["duration"]))))
        ramp = int(_ask("起压斜率(用户/秒)", str(cfg["ramp_per_sec"])) or cfg["ramp_per_sec"])

        args = build_parser().parse_args(
            ["--scenario", sc, "--users", str(users), "--duration", str(dur),
             "--ramp-per-sec", str(ramp), "--expect-mock"]
        )
        print(f"\n▶ 开始场景 {sc}: {users} VU × {dur}s …")
        t0 = time.monotonic()
        try:
            summary = await run_scenario(args)
        except SystemExit as e:
            print(f"! 场景失败: {e}")
            continue
        print(f"  场景 {sc} 完成,耗时 {time.monotonic() - t0:.0f}s")
        if summary and summary.get("tag"):
            _open_html(summary["tag"])

    # 退出清理
    if mode == "A" and await server_mgr.is_healthy():
        if _ask("停止压测服务器", "Y").upper() in ("Y", "YES"):
            server_mgr.stop_server()
            print("[向导] 服务器已停止。所有报告位于 backend/data/loadtest_reports/")
    print("再见。")


async def quick() -> None:
    """非交互小冒烟(--quick,自检用):全自动小规模跑通并生成报告。"""
    print("[quick] 自动:起 mock 服务器 → 造数 → S1 小规模 → 报告")
    if not await server_mgr.is_healthy():
        server_mgr.start_mock_server(wipe=True)
        if not await server_mgr.wait_ready():
            raise SystemExit("mock 服务器启动失败")
    if not user_mod.load_accounts():
        await seeding.run_setup(API_BASE)
    args = build_parser().parse_args(
        ["--scenario", "s1", "--users", "3", "--duration", "15",
         "--ramp-per-sec", "50", "--expect-mock"]
    )
    summary = await run_scenario(args)
    if summary and summary.get("tag"):
        _open_html(summary["tag"])
    server_mgr.stop_server()
    print("[quick] 完成(服务器已停止)")
