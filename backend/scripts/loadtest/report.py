# -*- coding: utf-8 -*-
"""报告落盘与控制台汇总:summary.json + metrics.csv + rps.csv + health_probe.csv。

门禁判定按场景适用:
  A1-A4(ask 完成率/错误率/全流延迟/TTFB)    —— 存在 ask 记录即判定(S0/S3/S4/S5)
  A5(读操作 p95)                            —— 存在读操作记录即判定(S2/S5/S6 的 docs_list 等)
  A2-sqlite_lock、A7(health)                —— 恒判定(A7 无 health 样本时列入 skipped)
不适用判据不会出现在 passes 中,而列入 skipped,避免"无数据却 FAIL"的噪音;
比率类判据(A1/A2)用未取整值比较,展示值才四舍五入。
"""
import csv
import json
import time
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

from . import metrics as M
from .config import REPORT_ROOT

# 通过线初值(与实施计划一致;S0 校准后可在此微调)
GATES = {
    "s3_done_rate_min": 0.995,      # A1 完成率 ≥99.5%
    "s3_err_rate_max": 0.005,       # A2 错误率 <0.5%
    "s3_sqlite_lock_max": 0,        # A2 sqlite_lock = 0
    "s3_ask_p95_total_max": 7200,   # A3 全流 p95 ≤2.5×2.9s 预算
    "s3_ask_p99_total_max": 10000,  # A3 p99 ≤10s
    "s3_ask_p95_ttfb_max": 1500,    # A4 首 token/TTFB p95 ≤1.5s
    "read_p95_max": 400,            # A5 读操作 p95 ≤400ms
    "health_p95_max": 500,          # A7 health p95 <500ms
    "health_spike_max": 2000,       # A7 无 >2s 尖峰
}
_ERROR_CLS = {"5xx", "sse_disconnect", "stall", "sse_app_error", "sqlite_lock",
              "protocol", "connect_error", "auth_fail"}
_READ_OPS = {"list_convs", "list_messages", "list_kbs", "list_kbs_admin", "auth_me", "export", "docs_list"}


def _pct(values: list[float], p: float) -> float:
    return M.percentile(values, p)


def _write_csv(path: Path, rows: list[list], header: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(header)
        w.writerows(rows)


def _ok_latencies(records: list[dict], op: str | None = None) -> list[float]:
    return [
        r["latency_ms"] for r in records
        if r["cls"] == "ok" and (op is None or r["op"] == op) and r["latency_ms"] > 0
    ]


def finalize(meta: dict, health: list[dict], tag: str) -> dict:
    """聚合全部记录,写报告文件,返回 summary 字典。"""
    records = M.snapshot()
    total = len(records)
    counts = Counter((r["op"], r["cls"]) for r in records)
    op_counts = Counter(r["op"] for r in records)
    err_of = lambda cls: sum(v for (op, c), v in counts.items() if c == cls)  # noqa: E731
    err_total = sum(err_of(c) for c in _ERROR_CLS)

    ask_records = [r for r in records if r["op"] == "ask"]
    ask_ok = [r for r in ask_records if r["cls"] == "ok"]
    has_ask = len(ask_records) > 0
    ask_done_rate = (len(ask_ok) / len(ask_records)) if has_ask else None
    # 错误率口径:ask 存在时以 ask 计(与 A1 口径一致);否则以全部记录计(排除预期 429)
    if has_ask:
        err_denom = len(ask_records)
        err_numer = sum(1 for r in ask_records if r["cls"] in _ERROR_CLS)
    else:
        err_denom = total
        err_numer = err_total
    err_rate = (err_numer / err_denom) if err_denom else 0.0
    sqlite_locks = err_of("sqlite_lock")

    # 每操作延迟分位(ok 样本)
    per_op: dict[str, dict] = {}
    read_p95s: list[float] = []
    for op in sorted(op_counts):
        vals = _ok_latencies(records, op)
        per_op[op] = {
            "n": len(vals),
            "p50": round(_pct(vals, 0.50), 1),
            "p95": round(_pct(vals, 0.95), 1),
            "p99": round(_pct(vals, 0.99), 1),
        }
        if op in _READ_OPS and vals:
            read_p95s.append(per_op[op]["p95"])
    has_read = len(read_p95s) > 0

    # ask 阶段:全流(ok)与首 token/TTFB(ok 且 ttfb_ms>0)
    ask_total = [r["latency_ms"] for r in ask_ok]
    ask_ttfb = [r["ttfb_ms"] for r in ask_ok if r["ttfb_ms"] > 0]

    # 每秒 RPS 窗口
    rps_rows = []
    if records:
        t0 = int(min(r["ts"] for r in records))
        t1 = int(max(r["ts"] for r in records)) + 1
        by_sec = defaultdict(list)
        for r in records:
            by_sec[int(r["ts"])].append(r)
        for s in range(t0, t1):
            rs = by_sec.get(s, [])
            rps_rows.append([s - t0, len(rs), sum(1 for x in rs if x["cls"] == "ok"),
                             sum(1 for x in rs if x["cls"] in _ERROR_CLS)])

    health_ms = [h["ms"] for h in health]
    health_p95 = _pct(health_ms, 0.95)
    health_max = max(health_ms) if health_ms else 0
    health_spikes = sum(1 for h in health if h["ms"] > GATES["health_spike_max"])

    # ---------- 门禁:按场景适用性组装 ----------
    gates = {
        "s3_done_rate": round(ask_done_rate, 4) if ask_done_rate is not None else None,
        "s3_err_rate": round(err_rate, 4),
        "s3_sqlite_lock": sqlite_locks,
        "s3_ask_p95_total": round(_pct(ask_total, 0.95), 1) if ask_total else None,
        "s3_ask_p99_total": round(_pct(ask_total, 0.99), 1) if ask_total else None,
        "s3_ask_p95_ttfb": round(_pct(ask_ttfb, 0.95), 1) if ask_ttfb else None,
        "read_p95_max": round(max(read_p95s), 1) if read_p95s else None,
        "health_p95": round(health_p95, 1),
        "health_spikes_over_2s": health_spikes,
    }
    passes: dict[str, bool] = {}
    skipped: list[str] = []
    # 比率判据用未取整原始值比较(展示值在 gates 里才 round)
    if has_ask:
        passes["A1 完成率≥99.5%"] = ask_done_rate >= GATES["s3_done_rate_min"]
        passes["A2 错误率<0.5%"] = err_rate < GATES["s3_err_rate_max"]
        passes["A3 ask p95≤7.2s"] = gates["s3_ask_p95_total"] <= GATES["s3_ask_p95_total_max"]
        passes["A3 ask p99≤10s"] = gates["s3_ask_p99_total"] <= GATES["s3_ask_p99_total_max"]
        if ask_ttfb:
            passes["A4 TTFB p95≤1.5s"] = gates["s3_ask_p95_ttfb"] <= GATES["s3_ask_p95_ttfb_max"]
        else:
            skipped.append("A4(无 TTFB 样本)")
    else:
        skipped += ["A1", "A3", "A4(无 ask 记录)"]
        passes["A2 全局错误率<0.5%"] = err_rate < GATES["s3_err_rate_max"]
    if read_p95s:
        passes["A5 读操作 p95≤400ms"] = gates["read_p95_max"] <= GATES["read_p95_max"]
    else:
        skipped.append("A5(无读操作记录)")
    passes["A2 sqlite_lock=0"] = gates["s3_sqlite_lock"] <= GATES["s3_sqlite_lock_max"]
    if health_ms:
        passes["A7 health p95<500ms"] = gates["health_p95"] < GATES["health_p95_max"]
        passes["A7 无>2s尖峰"] = health_spikes == 0
    else:
        skipped.append("A7(无 health 样本)")

    dir_ = REPORT_ROOT / tag
    dir_.mkdir(parents=True, exist_ok=True)
    _write_csv(
        dir_ / "metrics.csv",
        [[r["ts"], r["op"], r["cls"], r["status"], r["latency_ms"], r["ttfb_ms"], r["tokens"], r["extra"]]
         for r in records],
        ["ts", "op", "cls", "status", "latency_ms", "ttfb_ms", "tokens", "extra"],
    )
    _write_csv(dir_ / "rps.csv", rps_rows, ["sec", "req", "ok", "err"])
    _write_csv(dir_ / "health_probe.csv", [[h["ts"], h["ms"]] for h in health], ["ts", "ms"])

    summary = {
        "tag": tag,
        "time": datetime.now().isoformat(timespec="seconds"),
        "meta": meta,
        "total_requests": total,
        "ok": err_of("ok"),
        "errors": err_total,
        "error_detail": {c: err_of(c) for c in sorted(_ERROR_CLS)},
        "throttled_429": err_of("429"),
        "client_4xx": err_of("4xx"),
        "per_op": per_op,
        "ask": ({"n": len(ask_records), "done": len(ask_ok),
                 "done_rate": round(ask_done_rate, 4)} if has_ask else None),
        "health_probe": {"n": len(health_ms), "p95_ms": round(health_p95, 1),
                         "max_ms": round(health_max, 1), "spikes_over_2s": health_spikes},
        "gates": gates,
        "passes": passes,
        "skipped_gates": skipped,
    }
    with open(dir_ / "summary.json", "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)

    # 控制台汇总
    print("\n================ 场景汇总:", tag, "================")
    print(f"请求总数 {total} | ok {summary['ok']} | 错误 {err_total}(详情 {dict(summary['error_detail'])}) "
          f"| 429 {summary['throttled_429']} | 4xx {summary['client_4xx']}")
    print(f"{'操作':<14}{'次数':>7}{'p50(ms)':>10}{'p95(ms)':>10}{'p99(ms)':>10}")
    for op, d in per_op.items():
        print(f"{op:<14}{d['n']:>7}{d['p50']:>10}{d['p95']:>10}{d['p99']:>10}")
    if has_ask:
        print(f"ask 完成率 {gates['s3_done_rate']:.2%} | TTFB p95 {gates['s3_ask_p95_ttfb']}ms | "
              f"全流 p95 {gates['s3_ask_p95_total']}ms")
    print(f"health p95 {gates['health_p95']}ms 尖峰>2s ×{gates['health_spikes_over_2s']}")
    print("门禁:", " | ".join(f"{k}:{'PASS' if v else 'FAIL'}" for k, v in passes.items())
          or "(本场景无适用判据)")
    if skipped:
        print("跳过(不适用):", ", ".join(skipped))
    print(f"报告目录: {dir_}")
    return summary
