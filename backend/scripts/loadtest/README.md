# 100 并发压力测试套件

模拟 **100 人同时使用**的负载测试。**mock 为主体**（不消耗阿里云百炼额度、测系统自身容量），
真实链路冒烟为辅（预算硬上限 150 次 ask）。

## 架构

```
压测客户端(asyncio + httpx,零新依赖)  →  压测后端(uvicorn :8000)
  每个虚拟用户 = 独立账号 + 独立连接        DATA_DIR=data/_loadtest(临时库,与开发数据隔离)
  问答走 SSE 流(测 TTFB/首token/全流/断连)   LOADTEST_MOCK_PROVIDER=true → mock 层(零真实外呼)
```

产品侧配套改动（默认全部关闭，不影响正常运行）：
- `backend/.env` 可设 `LOADTEST_MOCK_PROVIDER=true`（dev-only mock 层）与 `STREAM_CONCURRENCY=N`（流式并发，默认 4）；
- mock 层实现：`backend/app/rag/mock_provider.py`（假 embedding/rerank/流式 LLM，由 lifespan 安装）。

## 快速开始（mock 全流程）

```bat
rem 1) 确认 8000 端口空闲(停掉开发后端)
cd backend
scripts\loadtest\start_mock_backend.bat      rem 起 mock 服务器(日志: data\_loadtest\server.log)
scripts\loadtest\run.bat --scenario setup    rem 造数:灌演示知识库 + 注册登录 100 用户(约 40s)
scripts\loadtest\run.bat --scenario s0       rem S0 校准冒烟(单 VU 25 问,约 90s)
scripts\loadtest\run.bat --scenario s3 --users 100 --duration 600
                                            rem S3 主场景:100 并发问答 10 分钟
scripts\loadtest\stop_backend.bat           rem 结束后按命令行标记精确停服务器
```

场景列表：`setup`(造数) / `s0`(校准) / `s1`(登录风暴) / `s2`(读操作并发) /
`s3`(mock 问答 100 并发,主场景) / `s5`(混合用户旅程) / `s6`(上传风暴) / `s4`(真实链路冒烟)。

CLI 通用参数：`--users N` `--duration 秒` `--ramp-per-sec N` `--base-url` `--expect-mock`
（要求服务器是 mock 模式，否则中止）。

## mock LLM 节奏（影响"在途流"与排队形态）

| env | 默认 | 主场景建议(S3) |
|---|---|---|
| `LOADTEST_MOCK_LLM_FIRST_DELAY_MS` | 250 | 250 |
| `LOADTEST_MOCK_LLM_CHUNK_DELAY_MS` | 15 | **45** |
| `LOADTEST_MOCK_LLM_TOTAL_CHARS` | 320 | **520** |

默认全流 ≈0.9s（压力主要在 DB 写）；45/520 档 ≈2.9s（在途流 ≈87，可满额试探
`STREAM_CONCURRENCY=100` 的闸门效果）。修改后重启服务器生效。

## 真实链路冒烟(S4,烧少量额度)

```bat
rem 1) 停开发后端(保证 WAL checkpoint 干净),做开发库目录快照:
robocopy ..\data ..\data\_loadtest_snapshot /E /XD logs qdrant.备份… (见下)
rem    快照需含: app.db(+ -wal/-shm)、qdrant\、uploads\(演示文档已在库内则 uploads 可省)
rem 2) scripts\loadtest\start_real_backend.bat    rem 用快照启动,真实百炼,不放大限流
rem 3) 预热自检自动执行(10 问 ≥8 命中 citations,否则会告警)
scripts\loadtest\run.bat --scenario s4 --real --users 5 --duration 240
rem 4) 结束后: stop_backend.bat, 删除快照目录
```

费用估算：每 ask ≈ embedding×3 + rerank×1 + qwen-plus 流式(入 ~2-4k token / 出 ~500)，
150 asks 总量量级 <¥2（以百炼控制台单价为准，跑前建议看余额）。

## 结果与通过线

报告自动落 `backend/data/loadtest_reports/<tag>/`（gitignore）：
`summary.json`（门禁判据按场景适用：A1~A4 仅问答案、A5 仅读操作场景、A2-sqlite_lock/A7 恒判定，
不适用判据列入 `skipped_gates` 不会误报 FAIL；A6/A8/A9 为观测项见下方边界说明）、
`metrics.csv`（逐请求，含 ttfb_ms/tokens 结构化列）、`rps.csv`（每秒吞吐）、
`health_probe.csv`（事件循环旁路探针,100ms 间隔）。
服务器日志 `data/_loadtest/server.log` 供 grep `database is locked` / traceback。

结论口径（重要）：
- **mock 结论只回答"系统自身容量"**（SQLite 写锁/Qdrant 同步阻塞/事件循环/落库节奏）；
  真实链路上限以 S4 实测为准；
- 429 计数单列（产品限流与 DashScope 限流属预期行为，不进错误率分母）；
- 若 `ask_throttled`/429 出现在 S3/S5 的 ask 上，说明客户端节流有 bug（预期为 0）。

## 已知边界

- 假向量使 Qdrant 检索"质量"失真但机制全真；假 rerank 分数恒过拒答阈值 → 几乎不触发拒答路径；
- 压测客户端与服务器同机，极端并发下客户端可能成为干扰源（观测到异常可拆机对照）；
- `_conversation_locks`（会话级锁表）随会话数增长是设计现状，S3 长跑后对比 RSS 即可量化。
