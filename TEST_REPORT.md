# 单元测试报告

> 生成方式:项目内 `/unit-test` skill(自「记账APP」迁移并适配本仓库技术栈)
> 生成日期:2026-09-05 · 报告内容:通过率 + 覆盖率(语句/分支/函数/行)

## 一、总览

| 端 | 框架 | 用例数 | 通过 | 失败 | 通过率 |
|---|---|---|---|---|---|
| 后端(backend/) | pytest + pytest-asyncio + pytest-cov | 57 | 57 | 0 | **100%** |
| 前端(frontend/) | Vitest + @vitest/coverage-v8 | 15 | 15 | 0 | **100%** |
| **合计** | — | **72** | **72** | **0** | **100%** |

执行命令:
```bash
# 后端
cd backend && .venv/Scripts/python -m pytest tests/ -q --cov=app --cov-report=term
# 前端
cd frontend && npm test            # = vitest run
npx vitest run --coverage
```

## 二、覆盖率

### 后端(全量 app 语句覆盖率 28%)

| 模块 | 语句 | 说明 |
|---|---|---|
| rag/splitter.py 文档解析分块 | 81% | txt/md/csv/docx/html + 清洗 + 长度边界 |
| rag/chain.py 生成链(提示词/语言) | 86% | 语言探测、资料编号、历史截断 |
| services/fts.py FTS5 中文检索 | 79% | 查询构造 + trigram 全链路 |
| schemas/*(校验边界) | 100% | auth / chat / kb 请求模型 |
| models/*(含 sql.py) | 100% | ORM 定义 + FTS 建表 SQL |
| rag/retriever.py | 40% | RRF 融合纯函数全覆盖;检索主链依赖向量库/API |
| rag/cache.py | 27% | 指纹纯函数全覆盖;check/store 依赖百炼 API |
| rag/history.py | 38% | 消息渲染纯函数全覆盖;压缩主链依赖 LLM |

> 说明:整体 28% 的差值主要由依赖数据库/网络/常驻 worker 的集成层构成
> (api/ 路由、services/ingest*、provider 百炼调用、seed 等)。按 skill 约定
> 「只测值得测的纯逻辑,不 mock 堆数字」,集成行为由 API 冒烟与端到端演示清单覆盖。

### 前端(语句覆盖率 33.87%,覆盖两个核心逻辑模块)

| 模块 | 语句 | 说明 |
|---|---|---|
| api/chat.ts(SSE 协议解析) | 30.18% | 4 种事件分发 + 畸形数据容错全覆盖;网络层 askStream 未测(需 mock fetch) |
| stores/chat.ts(会话状态运算) | 45.61% | 占位消息/流式追加/引用挂载/清理/防串号 reset 全覆盖 |
| stores/auth.ts | 14.28% | 会话存取(依赖 localStorage,边界有限,未刻意堆用例) |

## 三、测试用例清单(按模块)

**后端 tests/**
- `test_security.py`(12):bcrypt 盐哈希往返/错误拒绝;JWT 类型隔离、篡改/过期拒绝、jti 同秒唯一、令牌哈希
- `test_fts.py`(7):中英混排型号提取、2 字词词对、OR 语义、归一化后 "iphone16"↔"iPhone 16" 互通、kb 过滤隔离、删除索引失效
- `test_rrf.py`(5):单路保序、双路同排优先、融合分数比较、k 参数、空输入
- `test_splitter.py`(7):文本清洗、噪声过滤、md 分段切块边界、csv 行级模板与行号元数据、长文本多块顺序
- `test_chain.py`(8):中英语言探测、系统提示词规则注入、资料编号块、四段式用户消息、历史截断保近
- `test_cache.py`(3):知识库指纹顺序无关/内容敏感/空集
- `test_history.py`(4):角色标注、空内容过滤、超长截断、换行拍平
- `test_parsers.py`(5):docx 段落+表格行、html 噪声剔除、GBK 编码容错
- `test_schemas.py`(6):用户名/密码边界、空/超长问题拒绝、语言枚举、kb 必填

**前端 src/**
- `api/chat.test.ts`(7):SSE citations/token/done/error 解析、畸形 JSON 容错、非事件块跳过、done 缺字段降级
- `stores/chat.test.ts`(8):提问占位、流式 token 拼接、引用挂载、完成/拒答收尾、失败清理、clearAll 防串号、顺序保持

## 四、测试过程中发现并修复的问题

1. **[前端] 失败清理不彻底**:`removeLocal()` 只移除用户提问占位,流式助手占位("正在思考中…")残留。
   修复:同时清理 `local-` / `streaming-` 两类本地临时消息(stores/chat.ts)。
2. **[后端] HTML 解析缺少编码容错**:仅按 UTF-8 读取,GBK 老页面解析为空。
   修复:UTF-8 解码失败自动回退 gbk(splitter.py `_parse_html`)。

## 五、运行环境

- 后端:Python 3.14 · SQLAlchemy 2.0 · pytest 8+ (依赖见 backend/requirements.txt)
- 前端:Vite 6 · Vitest 5 · happy-dom 未用(node 环境纯逻辑)
- 全部用例离线运行,不依赖百炼 API Key 与外网
