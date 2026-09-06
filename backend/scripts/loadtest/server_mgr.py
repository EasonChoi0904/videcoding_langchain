# -*- coding: utf-8 -*-
"""压测服务器自动起停(手动向导用):mock 模式一键拉起/停止,无需手开窗口。

约定与 bat 一致:进程命令行含 loadtest_server.py,停止时按该标记精确杀进程。
"""
import asyncio
import os
import shutil
import subprocess
import time

import httpx

from .config import API_BASE, BACKEND_DIR, MOCK_DATA_DIR, VENV_PY

LOADER = BACKEND_DIR / "scripts" / "loadtest" / "loadtest_server.py"
SERVER_LOG = MOCK_DATA_DIR / "server.log"

# mock 服务器默认环境(与 loadtest_env.bat 一致;问答限流保持产品值 20/min)
MOCK_ENV = {
    "DATA_DIR": str(MOCK_DATA_DIR),
    "LOADTEST_MOCK_PROVIDER": "true",
    "STREAM_CONCURRENCY": "100",
    "RATE_REGISTER_PER_HOUR": "100000",
    "RATE_LOGIN_PER_MINUTE": "100000",
    "RATE_ASK_PER_MINUTE": "20",
    "LOADTEST_MOCK_LLM_FIRST_DELAY_MS": "250",
    "LOADTEST_MOCK_LLM_CHUNK_DELAY_MS": "45",   # 重节奏:全流≈2.9s,逼近真实在途
    "LOADTEST_MOCK_LLM_CHUNK_SIZE": "8",
    "LOADTEST_MOCK_LLM_TOTAL_CHARS": "520",
}

_proc: subprocess.Popen | None = None


async def is_healthy(base: str = API_BASE) -> bool:
    """服务器是否已就绪(health 200)。"""
    try:
        async with httpx.AsyncClient(timeout=3.0) as c:
            r = await c.get(f"{base}/health")
            return r.status_code == 200
    except Exception:  # noqa: BLE001
        return False


def start_mock_server(wipe: bool = True) -> bool:
    """以独立进程启动 mock 服务器;wipe=True 时清空临时库(全新数据)。

    Returns: True=已拉起;False=已有服务器在跑(未重复启动)。
    """
    global _proc
    if _proc is not None and _proc.poll() is None:
        return True
    if wipe:
        shutil.rmtree(MOCK_DATA_DIR, ignore_errors=True)
    MOCK_DATA_DIR.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ)
    env.update(MOCK_ENV)
    log_f = open(SERVER_LOG, "a", encoding="utf-8", errors="replace")
    _proc = subprocess.Popen(
        [str(VENV_PY), str(LOADER)],
        cwd=str(BACKEND_DIR), env=env,
        stdout=log_f, stderr=subprocess.STDOUT,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    return True


async def wait_ready(base: str = API_BASE, timeout_s: float = 60.0) -> bool:
    """轮询 health 直到就绪。"""
    t0 = time.monotonic()
    while time.monotonic() - t0 < timeout_s:
        if await is_healthy(base):
            return True
        await asyncio.sleep(0.5)
    return False


def stop_server() -> None:
    """按命令行标记精确停止压测服务器(不影响其它 python 进程)。"""
    global _proc
    if _proc is not None and _proc.poll() is None:
        _proc.terminate()
        try:
            _proc.wait(timeout=8)
        except Exception:  # noqa: BLE001
            _proc.kill()
        _proc = None
        return
    # 兜底:可能由 bat 或别处启动的同标记进程
    try:
        subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             "Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -match "
             "'loadtest_server\\.py' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }"],
            capture_output=True, timeout=20,
        )
    except Exception:  # noqa: BLE001
        pass
