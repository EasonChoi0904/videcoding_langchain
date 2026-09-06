# -*- coding: utf-8 -*-
"""压测服务器启动器(经 bat 调用)。

以独立进程启动 uvicorn,命令行含 loadtest_server.py 标记,
stop_backend.bat 按该标记精确结束进程(绝不误杀其它 python)。
环境变量(由 loadtest_env.bat / start_*_backend.bat 提供):
    DATA_DIR              临时数据目录(mock 用 data\\_loadtest;真实用快照目录)
    LOADTEST_MOCK_PROVIDER  true=装 mock 层跳过探测;留空=真实百炼
    STREAM_CONCURRENCY      流式并发(默认 4;mock 主场景设 100)
    RATE_*                 造数/登录限流放大(真实模式勿设)
"""
import os
import sys
from pathlib import Path

import uvicorn

if __name__ == "__main__":
    # 确保以 backend/ 为工作目录且可导入 app 包(脚本方式运行时
    # sys.path[0] 是脚本所在目录而非 cwd,须显式把 backend 加入 sys.path)
    here = Path(__file__).resolve().parent
    backend_dir = here.parent.parent
    os.chdir(backend_dir)
    sys.path.insert(0, str(backend_dir))

    port = int(os.getenv("LOADTEST_PORT", "8000"))
    print(f"[loadtest_server] cwd={backend_dir} DATA_DIR={os.getenv('DATA_DIR')} "
          f"mock={os.getenv('LOADTEST_MOCK_PROVIDER')} stream_concurrency={os.getenv('STREAM_CONCURRENCY')}")
    sys.stdout.flush()
    uvicorn.run("app.main:app", host="127.0.0.1", port=port, log_level="info")
