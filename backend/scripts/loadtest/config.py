# -*- coding: utf-8 -*-
"""压测全局配置(纯常量,无副作用)。"""
from pathlib import Path

# ==================== 目标服务器 ====================
API_BASE = "http://127.0.0.1:8000/api"
ADMIN_USER = "admin"
ADMIN_PASS = "123456"

# ==================== 虚拟用户账号池 ====================
USER_PREFIX = "lt_u"          # lt_u0001..lt_u0100
USER_COUNT = 100
USER_PASS = "loadtest-pass-1"
ADMIN_SLOTS = [1, 2]          # 前两个槽位提升为 admin(直插 DB,供 S5/S6)
REGISTER_PER_SEC = 5          # 造数阶段慢速注册,不把 bcrypt 成本混进场景计时

# ==================== 问答节流(产品限流 20/min/用户,留 10% 余量)====================
ASK_BUDGET_PER_MIN = 18
SSE_STALL_SECONDS = 150       # SSE 字节间空闲上限(服务器 chat_timeout=120s 的兜底)

# ==================== 场景参数 ====================
SCENARIOS = {
    "s0": {"users": 1, "duration": 40, "ramp_per_sec": 1, "desc": "校准冒烟(1 VU 连续问答)"},
    "s1": {"users": 100, "duration": 60, "ramp_per_sec": 200, "desc": "登录风暴(100 用户同时登录)"},
    "s2": {"users": 100, "duration": 180, "ramp_per_sec": 25, "desc": "读操作并发(会话/消息/知识库)"},
    "s3": {"users": 100, "duration": 600, "ramp_per_sec": 25, "desc": "mock 问答 100 并发(主场景)"},
    "s5": {"users": 100, "duration": 600, "ramp_per_sec": 25, "desc": "混合用户旅程 100 人"},
    "s6": {"users": 4, "duration": 300, "ramp_per_sec": 2, "desc": "上传风暴(admin)"},
}
# 主场景建议:LOADTEST_MOCK_LLM_CHUNK_DELAY_MS=45 + TOTAL_CHARS=520(全流≈2.9s)
# 轻量冒烟档:默认 15ms + 320 字符(全流≈0.9s)

# ==================== S5 混合旅程动作概率(与 lifecycle.s5_journey 实现一一对应)====================
# 说明:ask 受 ASK_BUDGET_PER_MIN 桶约束,桶空时自动降级为读操作;refresh 不占动作——
# 令牌 401 时由 Account.request 自动轮换,无需独立动作;conv_ops 具体化为 改名。
MIX_S5 = {
    "ask": 35,           # 每 3.4s 一次的提问预算
    "list_convs": 15,
    "list_messages": 23,  # 50-65 与 85-93 两段合计
    "new_conv": 10,
    "list_kbs": 10,
    "auth_me": 3,
    "feedback": 2,
    "rename_conv": 2,
}
# 每 VU 思考间隔:指数分布均值(秒)
THINK_MEAN_SECONDS = 4.0

# ==================== 路径约定 ====================
BACKEND_DIR = Path(__file__).resolve().parent.parent.parent   # backend/
REPORT_ROOT = BACKEND_DIR / "data" / "loadtest_reports"
MOCK_DATA_DIR = BACKEND_DIR / "data" / "_loadtest"
ACCOUNTS_FILE = MOCK_DATA_DIR / "accounts.json"
VENV_PY = BACKEND_DIR / ".venv" / "Scripts" / "python.exe"    # 压测服务器启动器用

# 上传风暴素材:每份唯一 txt 的目标分块数(约 500 字/块)
UPLOAD_DOC_CHARS = 8000
