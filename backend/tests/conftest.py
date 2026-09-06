"""pytest 公共配置:所有测试均为离线纯逻辑测试(不调用百炼 API、不起服务)。

需要网络/密钥的端到端场景由 scripts 与手动演示清单覆盖。
"""
import sys
from pathlib import Path

# 确保 app 包可导入(backend 目录)
BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))
