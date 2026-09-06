"""日志配置:控制台彩色输出 + 按天滚动文件,便于答辩演示时查看后端运行轨迹。"""
import logging
import sys
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path

from app.core.settings import BASE_DIR

LOG_FORMAT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"


def setup_logging(level: int = logging.INFO) -> None:
    """初始化根日志器。重复调用会被幂等保护,避免重复添加 handler。"""
    root = logging.getLogger()
    if getattr(root, "_rag_configured", False):
        return
    root.setLevel(level)

    console = logging.StreamHandler(sys.stdout)
    console.setFormatter(logging.Formatter(LOG_FORMAT))
    root.addHandler(console)

    log_dir = BASE_DIR / "data" / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    file_handler = TimedRotatingFileHandler(
        log_dir / "app.log", when="midnight", backupCount=7, encoding="utf-8"
    )
    file_handler.setFormatter(logging.Formatter(LOG_FORMAT))
    root.addHandler(file_handler)

    # 降低三方库噪音,保留自家模块可读性
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)

    root._rag_configured = True
