# -*- coding: utf-8 -*-
"""本地网页压测控制台(dev-only,单机使用)。

在浏览器里输入用户数/时长/场景并启动压测:自动起 mock 服务器 → 自动造数 →
后台执行场景(独立子进程,与"被测服务器"严格分离)→ 实时进度 → HTML 报告托管。

入口:scripts\\loadtest\\web_console.bat(或 python scripts/loadtest/web_console.py)
页面: http://127.0.0.1:9100   接口: /api/run /api/status /api/stop /api/server/start|stop /report/<tag>/*

零第三方依赖(标准库 http.server);仅限本机 127.0.0.1,勿暴露到网络。
"""
import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import webbrowser
from collections import deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HOST, PORT = "127.0.0.1", 9100
BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
REPORT_ROOT = os.path.join(BACKEND_DIR, "data", "loadtest_reports")
VENV_PY = os.path.join(BACKEND_DIR, ".venv", "Scripts", "python.exe")
TARGET_HEALTH = "http://127.0.0.1:8000/api/health"

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:  # noqa: BLE001
    pass

def _server_mgr():
    """兼容两种入口(文件直接运行 / python -m 包运行)的 server_mgr 引用。"""
    try:
        from . import server_mgr as m
    except ImportError:  # 以文件方式运行时无包上下文
        from scripts.loadtest import server_mgr as m  # noqa: PLC0415
    return m


SCENARIOS = {
    "s0": {"label": "S0 校准冒烟", "hint": "1 人连续问答,验证链路与基线(约 90s)", "max_users": 1},
    "s1": {"label": "S1 登录风暴", "hint": "全部用户同时登录(bcrypt 压测)", "max_users": 500},
    "s2": {"label": "S2 读操作并发", "hint": "会话/消息/知识库浏览", "max_users": 500},
    "s3": {"label": "S3 问答 100 并发", "hint": "SSE 流式问答主场景", "max_users": 500},
    "s5": {"label": "S5 混合旅程", "hint": "100 人混合使用(问答+浏览)", "max_users": 500},
    "s6": {"label": "S6 上传风暴", "hint": "admin 持续上传文档", "max_users": 10},
}
DEFAULT_USERS = {"s0": 1, "s1": 100, "s2": 100, "s3": 100, "s5": 100, "s6": 4}
DEFAULT_DURATION = {"s0": 90, "s1": 60, "s2": 180, "s3": 300, "s5": 300, "s6": 120}
RAMP = {"s0": 1, "s1": 200, "s2": 25, "s3": 25, "s5": 25, "s6": 2}

# ==================== 运行工作线程(独立子进程跑 CLI,输出实时收集) ====================
class Runner:
    """单任务执行器:串行处理,带日志环与停止能力。"""

    def __init__(self):
        self.lock = threading.Lock()
        self.busy = False
        self.log: deque[str] = deque(maxlen=800)
        self.proc: subprocess.Popen | None = None
        self.last_report: str | None = None
        self.phase = "idle"          # idle / server / setup / scenario / done / error
        self.stopping = False

    def _log(self, line: str) -> None:
        ts = time.strftime("%H:%M:%S")
        with self.lock:
            self.log.append(f"[{ts}] {line}")

    def tail(self, n: int = 400) -> list[str]:
        with self.lock:
            return list(self.log)[-n:]

    def start(self, scenario: str, users: int, duration: int, auto_server: bool) -> dict:
        """启动一次压测;已在运行时返回 busy。"""
        with self.lock:
            if self.busy:
                return {"ok": False, "error": "已有任务在运行,请等待完成或先停止"}
            self.busy, self.stopping, self.last_report = True, False, None
            self.log.clear()
            self.phase = "starting"
        threading.Thread(
            target=self._run, args=(scenario, users, duration, auto_server),
            daemon=True, name="loadtest-runner",
        ).start()
        return {"ok": True}

    # ---- 子进程助手 ----
    def _spawn(self, args: list[str], create_window=False):
        flags = 0 if create_window else getattr(subprocess, "CREATE_NO_WINDOW", 0)
        return subprocess.Popen(
            args, cwd=BACKEND_DIR, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, encoding="utf-8", errors="replace", bufsize=1,
            creationflags=flags,
        )

    def _pump(self, proc: subprocess.Popen) -> int:
        """逐行读子进程输出进日志环,返回退出码。"""
        self.proc = proc
        try:
            for line in proc.stdout:  # type: ignore[union-attr]
                self._log(line.rstrip())
                if self.stopping:
                    break
        finally:
            self.proc = None
        proc.kill() if proc.poll() is None else None
        return proc.wait()

    def _run_cli(self, scenario: str, users: int, duration: int) -> int:
        """跑一个场景 CLI(独立进程),日志里出现 HTML 报告行时记录 tag。"""
        args = [VENV_PY, "-u", "-m", "scripts.loadtest.main",
                "--scenario", scenario, "--users", str(users),
                "--duration", str(duration), "--expect-mock"]
        proc = self._spawn(args)
        self.phase = "scenario"
        code = self._pump(proc)
        # 从日志解析报告位置(存相对 REPORT_ROOT 的斜杠路径,供网页直链)
        for ln in reversed(self.tail(2000)):
            m = re.search(r"HTML 报告: (.+index\.html)$", ln.strip())
            if m:
                rel = os.path.relpath(m.group(1), REPORT_ROOT).replace("\\", "/")
                self.last_report = rel
                break
        return code

    def _run(self, scenario: str, users: int, duration: int, auto_server: bool) -> None:
        try:
            # 1) 目标服务器(mock)
            if auto_server:
                self.phase = "server"
                if not self._healthy():
                    self._log("启动 mock 压测服务器(全新临时库)…")
                    _server_mgr().start_mock_server(wipe=True)
                    if not self._wait_ready(60):
                        raise RuntimeError("mock 服务器启动失败(查看 data/_loadtest/server.log)")
                    self._log("mock 服务器就绪")
                # 2) 造数(全新临时库没有账号文件 → 自动补)
                accounts_file = os.path.join(BACKEND_DIR, "data", "_loadtest", "accounts.json")
                if not os.path.exists(accounts_file):
                    self.phase = "setup"
                    self._log("自动造数(演示知识库 + 100 账号,约 40s)…")
                    code = self._run_cli_setup()
                    if code != 0:
                        raise RuntimeError(f"造数失败(exit={code})")
            else:
                if not self._healthy():
                    raise RuntimeError("目标服务器未运行——请先手动启动,或勾选自动管理")
            # 3) 场景
            self._log(f"开始场景 {scenario}: {users} 用户 × {duration}s")
            code = self._run_cli(scenario, users, duration)
            if self.stopping:
                self.phase = "done"
                self._log("[已停止]")
                return
            if code != 0:
                self.phase = "error"
                self._log(f"场景退出码 {code},详见上方输出")
                return
            self.phase = "done"
            self._log(f"场景完成 → 报告: {self.last_report or '(未生成)'}")
        except Exception as e:  # noqa: BLE001
            self.phase = "error"
            self._log(f"运行失败: {e}")
        finally:
            with self.lock:
                self.busy = False

    def _run_cli_setup(self) -> int:
        proc = self._spawn([VENV_PY, "-u", "-m", "scripts.loadtest.main", "--scenario", "setup"])
        return self._pump(proc)

    def stop(self) -> None:
        """停止当前子进程(置标志让其退出;再补杀兜底)。"""
        with self.lock:
            self.stopping = True
            proc = self.proc
        if proc is not None:
            try:
                proc.kill()
            except Exception:  # noqa: BLE001
                pass

    def _healthy(self, timeout=3.0) -> bool:
        try:
            import httpx

            return httpx.get(TARGET_HEALTH, timeout=timeout).status_code == 200
        except Exception:  # noqa: BLE001
            return False

    def _wait_ready(self, timeout_s: float) -> bool:
        t0 = time.monotonic()
        while time.monotonic() - t0 < timeout_s:
            if self._healthy():
                return True
            time.sleep(0.5)
        return False


RUNNER = Runner()


# ==================== 目标服务器管理(与压测进程解耦) ====================
def _server_state() -> dict:
    return {"healthy": RUNNER._healthy()}


def _server_start(wipe: bool) -> dict:
    if RUNNER.busy:
        return {"ok": False, "error": "压测运行中,请先停止"}
    _server_mgr().start_mock_server(wipe=wipe)
    RUNNER._log("等待 mock 服务器就绪…")
    ok = RUNNER._wait_ready(60)
    return {"ok": ok, "error": "" if ok else "启动超时"}


def _server_stop() -> dict:
    _server_mgr().stop_server()
    return {"ok": True}


# ==================== HTTP 页面与接口 ====================
def _serve_report(rel_path: str, handler: BaseHTTPRequestHandler) -> bool:
    """托管 data/loadtest_reports 下的报告文件(防路径穿越)。"""
    root = os.path.realpath(REPORT_ROOT)
    target = os.path.realpath(os.path.join(root, rel_path))
    if not (target.startswith(root + os.sep) and os.path.isfile(target)):
        return False
    ext_map = {".html": "text/html; charset=utf-8", ".json": "application/json; charset=utf-8",
               ".csv": "text/csv; charset=utf-8"}
    handler.send_response(200)
    handler.send_header("Content-Type", ext_map.get(os.path.splitext(target)[1], "application/octet-stream"))
    handler.send_header("Content-Length", str(os.path.getsize(target)))
    handler.end_headers()
    with open(target, "rb") as f:
        handler.wfile.write(f.read())
    return True


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):  # 静默访问日志
        pass

    def _json(self, code: int, obj: dict) -> None:
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):  # noqa: N802
        path = self.path.split("?", 1)[0]
        if path in ("/", "/index.html"):
            body = PAGE.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        elif path == "/favicon.ico":
            self.send_response(204); self.end_headers()
        elif path == "/api/status":
            self._json(200, {
                "busy": RUNNER.busy, "phase": RUNNER.phase,
                "last_report": RUNNER.last_report,
                "log": RUNNER.tail(500), "server": _server_state(),
            })
        elif path.startswith("/report/"):
            if not _serve_report(path[len("/report/"):], self):
                self._json(404, {"error": "not found"})
        else:
            self._json(404, {"error": "unknown api"})

    def do_POST(self):  # noqa: N802
        path = self.path.split("?", 1)[0]
        try:
            length = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(length) or b"{}") if length else {}
        except Exception:  # noqa: BLE001
            body = {}
        if path == "/api/run":
            sc = str(body.get("scenario", "s3"))
            if sc not in SCENARIOS:
                return self._json(400, {"ok": False, "error": f"unknown scenario {sc}"})
            raw = body.get("users")
            users = max(1, min(int(raw) if raw is not None else DEFAULT_USERS[sc], 500))
            duration = max(10, int(body.get("duration") or DEFAULT_DURATION[sc]))
            auto = bool(body.get("auto_server", True))
            res = RUNNER.start(sc, users, duration, auto)
            return self._json(200 if res.get("ok") else 409, res)
        elif path == "/api/stop":
            RUNNER.stop()
            return self._json(200, {"ok": True})
        elif path == "/api/server/start":
            return self._json(200, _server_start(bool(body.get("wipe", True))))
        elif path == "/api/server/stop":
            return self._json(200, _server_stop())
        elif path == "/api/open":
            # 在资源管理器打开最新报告所在目录(尽力而为)
            folder = os.path.dirname(os.path.join(REPORT_ROOT, RUNNER.last_report)) if RUNNER.last_report else REPORT_ROOT
            if os.path.isdir(folder):
                os.startfile(folder)  # noqa: S606 Windows 专用
                return self._json(200, {"ok": True})
            return self._json(404, {"ok": False, "error": "报告目录不存在"})
        else:
            return self._json(404, {"error": "unknown api"})


# ==================== 前端页面 ====================
PAGE = """<!DOCTYPE html>
<html lang="zh"><head><meta charset="utf-8"><title>RAG 压测控制台</title>
<style>
 body{font-family:'Microsoft YaHei',sans-serif;background:#0f172a;color:#e2e8f0;margin:0}
 .wrap{max-width:960px;margin:0 auto;padding:24px}
 h1{font-size:20px;display:flex;align-items:center;gap:12px}
 h1 .dot{width:10px;height:10px;border-radius:50%;background:#64748b;display:inline-block}
 h1 .dot.on{background:#22c55e;box-shadow:0 0 8px #22c55e}
 h1 .dot.off{background:#64748b}
 .cards{display:grid;grid-template-columns:repeat(auto-fill,minmax(180px,1fr));gap:10px;margin:16px 0}
 .sc{background:#1e293b;border:1px solid #334155;border-radius:10px;padding:10px 14px;cursor:pointer}
 .sc.sel{border-color:#3b82f6;background:#1d4ed833}
 .sc small{display:block;color:#94a3b8;margin-top:4px}
 .row{display:flex;gap:12px;align-items:flex-end;flex-wrap:wrap;margin:14px 0}
 .fld{display:flex;flex-direction:column;gap:4px}
 .fld input{background:#1e293b;border:1px solid #334155;color:#e2e8f0;border-radius:8px;padding:8px 10px;width:150px}
 button{border:0;border-radius:8px;padding:9px 18px;cursor:pointer;font-size:14px}
 .go{background:#2563eb;color:#fff}.go:disabled{opacity:.5;cursor:not-allowed}
 .danger{background:#7f1d1d;color:#fff}
 .ghost{background:#334155;color:#e2e8f0}
 #out{background:#0b1220;border:1px solid #1e293b;border-radius:10px;padding:10px;height:300px;
      overflow:auto;font:12px/1.6 Consolas,monospace;white-space:pre-wrap;color:#a5f3fc}
 #result{margin-top:10px;display:none}
 a.report{color:#60a5fa;word-break:break-all}
 .tag{color:#94a3b8;font-size:12px}
 .badge{display:inline-block;padding:2px 10px;border-radius:20px;font-size:12px;margin:2px 4px 2px 0}
 .b-ok{background:#14532d;color:#4ade80}.b-err{background:#450a0a;color:#f87171}
</style></head><body><div class="wrap">
<h1>RAG 系统压测控制台 <span id="sdot" class="dot"></span><span class="tag">目标服务器 127.0.0.1:8000 · mock 模式</span></h1>
<div class="cards" id="scs"></div>
<div class="row">
 <div class="fld"><label>虚拟用户数</label><input id="users" type="number" value="100" min="1" max="500"></div>
 <div class="fld"><label>时长(秒)</label><input id="dur" type="number" value="300" min="10"></div>
 <label><input id="auto" type="checkbox" checked> 自动起/造数(mock)</label>
 <button class="go" id="go">开始压测</button>
 <button class="danger" id="stop" disabled>停止</button>
 <button class="ghost" id="sstart">启动服务器</button>
 <button class="ghost" id="sstop">停止服务器</button>
</div>
<div id="result">
 <button class="ghost" id="open">打开最新报告(新标签页)</button>
 <button class="ghost" id="openFolder">在资源管理器打开报告目录</button>
 <span class="tag" id="tagline"></span>
</div>
<div id="out"></div>
</div>
<script>
const SC={"s0":["S0 校准冒烟","1 人连续问答,验证链路与基线(约 90s)"],
 "s1":["S1 登录风暴","全部用户同时登录(bcrypt 压测)"],
 "s2":["S2 读操作并发","会话/消息/知识库浏览"],
 "s3":["S3 问答并发(主场景)","SSE 流式问答"],
 "s5":["S5 混合旅程","问答+浏览+管理混合"],
 "s6":["S6 上传风暴","admin 持续上传文档"]};
let cur="s3", report=null;
const $=id=>document.getElementById(id);
function renderScs(){const box=$("scs");box.innerHTML="";
 for(const k in SC){const d=document.createElement("div");d.className="sc"+(k===cur?" sel":"");d.innerHTML="<b>"+SC[k][0]+"</b><small>"+SC[k][1]+"</small>";
  d.onclick=()=>{cur=k;renderScs();};box.appendChild(d);}}
async function api(method,path,body){const r=await fetch(path,{method,headers:{"Content-Type":"application/json"},
  body:body?JSON.stringify(body):undefined});return r.json();}
function log(msg){const o=$("out");o.textContent+=msg+"\\n";o.scrollTop=o.scrollHeight;}
async function status(){const s=await api("GET","/api/status");
 $("sdot").className="dot"+(s.server&&s.server.healthy?" on":"");
 $("go").disabled=s.busy;$("stop").disabled=!s.busy;
 if(s.log){const joined=s.log.join("\\n");if(joined!==log.last){log.last=joined;$("out").textContent=joined; $("out").scrollTop=$("out").scrollHeight;}}
 if(s.busy){setTimeout(status,800);}else if(s.last_report&&report!==s.last_report){report=s.last_report;
  $("tagline").textContent="最新报告: "+report;$("result").style.display="block";log("\\n[完成] 报告已生成(点击上方按钮查看)");}
 if(!s.busy&&s.phase==="error"){$("tagline").textContent="运行失败,见上方日志";}
}
async function run(){const body={scenario:cur,users:+$("users").value,duration:+$("dur").value,
 auto_server:$("auto").checked};report=null;$("tagline").textContent="";log("启动:场景 "+cur+" 用户 "+body.users);
 const r=await api("POST","/api/run",body);if(!r.ok)log("! "+r.error);status();}
$("go").onclick=run;
$("stop").onclick=async()=>{log("[手动停止]");await api("POST","/api/stop");};
$("sstart").onclick=async()=>{log("启动 mock 服务器(全新数据,约 15s)…");const r=await api("POST","/api/server/start",{wipe:true});
 log(r.ok?"服务器已就绪":"! 启动失败");status();};
$("sstop").onclick=async()=>{await api("POST","/api/server/stop");log("服务器已停止");status();};
$("open").onclick=()=>{if(report)window.open("/report/"+report,"报告");};
$("openFolder").onclick=async()=>{await api("POST","/api/open");};
renderScs();status();setInterval(status,5000);
</script></body></html>"""


def main() -> None:
    ap = argparse.ArgumentParser(description="RAG 压测网页控制台(本机)")
    ap.add_argument("--port", type=int, default=PORT)
    ap.add_argument("--no-browser", action="store_true")
    args = ap.parse_args()

    # 以文件方式运行时把 backend 加入 sys.path,保证 server_mgr 等包内导入可用
    if BACKEND_DIR not in sys.path:
        sys.path.insert(0, BACKEND_DIR)
    srv = ThreadingHTTPServer((HOST, args.port), Handler)
    print(f"压测控制台: http://{HOST}:{args.port}  (Ctrl+C 退出)")
    if not args.no_browser:
        try:
            webbrowser.open(f"http://{HOST}:{args.port}")
        except Exception:  # noqa: BLE001
            pass
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        srv.server_close()


if __name__ == "__main__":
    main()
