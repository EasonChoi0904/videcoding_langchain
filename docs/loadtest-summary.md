# 100 并发压力测试报告（2026-09-06）

## 一、测试目标与环境

模拟 **100 人同时使用** 系统（登录/浏览/会话管理/问答/反馈），量化容量与瓶颈。

| 项 | 说明 |
|---|---|
| 被测对象 | 本仓库单机形态：FastAPI 单进程（uvicorn :8000）+ SQLite(WAL) + Qdrant 嵌入式 + Vue3 |
| 压测工具 | 自写 asyncio + httpx 套件（`backend/scripts/loadtest/`，零新依赖） |
| 数据隔离 | 全部跑在临时库 `backend/data/_loadtest`（含 4 份演示文档知识库 + 100 个压测账号），不触碰开发数据 |
| Mock 模式 | `LOADTEST_MOCK_PROVIDER=1` 时后端装入 dev-only mock 层（假 embedding/rerank/流式 LLM），**零真实外呼**；检索/缓存/落库/SQLite/Qdrant 机制全部真实执行 |
| 流式并发 | `STREAM_CONCURRENCY`（默认 4，env 可调）；mock 流节奏 ≈2.9s/问（45ms/chunk × 520 字符） |

> 口径声明：mock 结果只回答"系统自身容量"（SQLite 写锁/Qdrant 同步调用/事件循环/落库节奏）；
> 真实阿里云百炼链路的上限以 S4 冒烟为准（本报告时点未执行，步骤见 `scripts/loadtest/README.md`）。

## 二、场景矩阵与结果

| 场景 | 负载 | 关键结果 |
|---|---|---|
| **S1 登录风暴** | 100 用户同时登录（+10% 注册） | 110/110 成功、0 429；**login p50=28.2s / p95=37.6s**（bcrypt-12 线程池排队），health 同段 5 次 >2s 尖峰 |
| **S2 读操作并发** | 100 人 × 150s 轮转会话/消息/知识库/导出/统计 | 55,238 请求 ≈370 RPS **全部成功**；读 p95 ≤80ms；admin stats（6 次 COUNT 全表扫）p95=189ms；health p95=7ms |
| **S3-v1 问答 100 并发** | 100 人 × 480s，`STREAM_CONCURRENCY=100` | 7,476 次 ask **完成率 100%**、0 错误、0 sqlite 锁；吞吐 15.6 ask/s；TTFB p95=409ms；全流 p95=3.71s |
| **S3-v2 现状闸门对照** | 同 S3-v1，`STREAM_CONCURRENCY=4`（默认值） | 吞吐跌至 **1.8 ask/s**；ask p50=**80.7s**、TTFB p95=78.3s；系统仍 0 错误（排队发生在信号量，事件循环健康） |
| **S5 混合旅程** | 100 人 × 300s（问答 35% + 会话/消息/知识库/反馈/改名等，指数思考间隔均值 4s） | 7,866 请求，仅 1 次瞬时连接抖动（0.013%）；ask p95=3.46s；读操作 p95 ≤26ms；全部门禁 PASS |

### 门禁判定汇总（报告目录 `backend/data/loadtest_reports/<tag>/` 的 summary.json 逐条可查）

- S3-v1/S5：A1 完成率≥99.5%、A2 错误率<0.5%、A2 sqlite_lock=0、A3 全流 p95≤7.2s、A4 TTFB p95≤1.5s、A5 读 p95≤400ms、A7 health p95<500ms 且无 >2s 尖峰 —— **全部 PASS**
- S3-v2：A3/A4 FAIL（属闸门对比实验的预期结果，非故障）
- S1：A6 仅观测 —— 登录 p95 37.6s 作发现项记录

## 三、关键发现（论文"性能与优化"素材）

1. **流式并发闸门是问答容量的第一约束（量化）**：100 人同问时，`Semaphore(4)` 使平均排队 ≈ 等待数/并发 × 流时长（实测 p50 80.7s，与模型 ~75s 吻合）；放开到 100 后吞吐 8.6×、延迟降低 23×，且 SQLite/事件循环无新压力（零锁、health p95 3.7ms）。建议按百炼配额把默认值调到 **10~20**（env `STREAM_CONCURRENCY`），不必到 100。
2. **登录并发受 bcrypt-12 拖累**：100 并发登录 p50 28.2s，根因是同步 bcrypt 占线程池、请求排队；期间事件循环探针尖峰证实阻塞。可选优化：bcrypt 轮数降到 10（OWASP 仍达标）或登录走独立限流队列/异步化。
3. **读链路余量充足**：~370 RPS 全成功，读 p95 ≤80ms；admin 统计页的全表 COUNT 是读侧放大点（p95 189ms），数据量大后可考虑物化/异步刷新。
4. **SQLite 单写者经受住了问答风暴**：流式每 1s 快照落库 × 100 并发（全流 2.9s → 每问 ~4 次 commit）全程 0 `database is locked`（WAL + busy_timeout=30 生效）。
5. **事件循环健康**：除 S1 bcrypt 窗口外，各场景 health 探针 p95 ≤7ms、无 >2s 尖峰；Qdrant 同步 query_points 在 100 并发检索下未形成可见阻塞（检索时长短）。

## 四、复现方式（要点）

```bat
cd backend
scripts\loadtest\start_mock_backend.bat       # 默认 STREAM_CONCURRENCY=100 + 重节奏 mock
scripts\loadtest\run.bat --scenario setup     # 灌演示知识库 + 100 账号
scripts\loadtest\run.bat --scenario s1 --users 100
scripts\loadtest\run.bat --scenario s2 --users 100 --duration 150
scripts\loadtest\run.bat --scenario s3 --users 100 --duration 480
rem 对比默认闸门:重启服务器设 STREAM_CONCURRENCY=4 后重跑 s3
scripts\loadtest\run.bat --scenario s5 --users 100 --duration 300
scripts\loadtest\stop_backend.bat
```

报告/逐请求明细在 `backend/data/loadtest_reports/`（gitignore）；服务器日志 `data/_loadtest/server.log`。
真实链路冒烟（S4）步骤与费用估算见 `backend/scripts/loadtest/README.md`。
